"""
SQLite 데이터베이스 관리 모듈

중복 체크용 seen 테이블과 브리핑 실행 기록용 briefings 테이블을 관리한다.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Set

from loguru import logger


# 기본 DB 경로
DEFAULT_DB_PATH = Path(__file__).parent.parent / "state" / "seen.db"


class Storage:
    """SQLite 기반 저장소 관리"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """테이블 초기화"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 중복 체크용 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS seen (
                    url_hash TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL
                )
            """)

            # 브리핑 실행 기록 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS briefings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    articles_json TEXT NOT NULL,
                    sent_telegram INTEGER DEFAULT 0,
                    sent_email INTEGER DEFAULT 0,
                    haiku_tokens_in INTEGER DEFAULT 0,
                    haiku_tokens_out INTEGER DEFAULT 0,
                    sonnet_tokens_in INTEGER DEFAULT 0,
                    sonnet_tokens_out INTEGER DEFAULT 0,
                    estimated_cost_usd REAL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_seen_first_seen
                ON seen(first_seen_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_briefings_date
                ON briefings(date)
            """)

            conn.commit()
            logger.debug("데이터베이스 초기화 완료")

    def get_seen_hashes(self, days: int = 7) -> Set[str]:
        """최근 N일간 처리한 기사의 URL 해시 목록 반환"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT url_hash FROM seen WHERE first_seen_at >= ?",
                (cutoff,),
            )
            return {row[0] for row in cursor.fetchall()}

    def mark_seen(self, url_hash: str, url: str, title: str):
        """기사를 처리 완료로 기록"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR IGNORE INTO seen (url_hash, url, title, first_seen_at)
                   VALUES (?, ?, ?, ?)""",
                (url_hash, url, title, datetime.now().isoformat()),
            )
            conn.commit()

    def save_briefing(
        self,
        date: str,
        articles_json: str,
        sent_telegram: bool = False,
        sent_email: bool = False,
        haiku_tokens_in: int = 0,
        haiku_tokens_out: int = 0,
        sonnet_tokens_in: int = 0,
        sonnet_tokens_out: int = 0,
        estimated_cost_usd: float = 0.0,
    ):
        """브리핑 실행 기록 저장"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO briefings
                   (date, articles_json, sent_telegram, sent_email,
                    haiku_tokens_in, haiku_tokens_out,
                    sonnet_tokens_in, sonnet_tokens_out,
                    estimated_cost_usd, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    date,
                    articles_json,
                    int(sent_telegram),
                    int(sent_email),
                    haiku_tokens_in,
                    haiku_tokens_out,
                    sonnet_tokens_in,
                    sonnet_tokens_out,
                    estimated_cost_usd,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            logger.info(f"브리핑 기록 저장 완료 (비용: ${estimated_cost_usd:.4f})")

    def get_monthly_cost(self) -> float:
        """이번 달 누적 비용 조회"""
        month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM briefings WHERE date >= ?",
                (month_start,),
            )
            return cursor.fetchone()[0]

    def cleanup_old_records(self, days: int = 30):
        """오래된 seen 레코드 삭제"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM seen WHERE first_seen_at < ?", (cutoff,))
            deleted = cursor.rowcount
            conn.commit()

        if deleted > 0:
            logger.info(f"오래된 레코드 {deleted}건 삭제")
