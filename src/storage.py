"""
SQLite 데이터베이스 관리 모듈

- seen: 중복 체크용 (URL 해시)
- articles: 기사 개별 저장 (나중에 사용자별 저장/검색용)
- briefings: 브리핑 실행 기록 (비용 추적)
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Set

from loguru import logger


# 기본 DB 경로
DEFAULT_DB_PATH = Path(__file__).parent.parent / "state" / "seen.db"

# 보존 정책 (state/seen.db는 매 실행마다 git에 커밋되므로 크기를 관리해야 한다)
# GitHub은 파일 하나가 100MB를 넘으면 push를 거부하므로, 한참 아래에서 상한을 잡는다.
DEFAULT_ARTICLE_RETENTION_DAYS = 45   # articles: 이슈 추적(7일)·주간 요약(7일)에 충분한 여유
DEFAULT_SEEN_RETENTION_DAYS = 30      # seen/alert_seen: 중복 체크는 최근 7일만 조회
DEFAULT_MAX_DB_SIZE_MB = 50.0         # 이 크기를 넘으면 오래된 기사부터 추가 삭제


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

            # 기사 개별 저장 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url_hash TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    summary TEXT DEFAULT '',
                    published_at TEXT,
                    category TEXT DEFAULT '',
                    importance INTEGER DEFAULT 0,
                    scope TEXT DEFAULT '',
                    ai_summary TEXT DEFAULT '',
                    ai_comment TEXT DEFAULT '',
                    response_needed TEXT DEFAULT 'none',
                    briefing_date TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(url_hash, briefing_date)
                )
            """)

            # 마이그레이션: response_needed 컬럼이 없으면 추가
            cursor.execute("PRAGMA table_info(articles)")
            cols = {row[1] for row in cursor.fetchall()}
            if "response_needed" not in cols:
                cursor.execute(
                    "ALTER TABLE articles ADD COLUMN response_needed TEXT DEFAULT 'none'"
                )

            # 브리핑 실행 기록 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS briefings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    article_count INTEGER DEFAULT 0,
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

            # 속보 점검 기록 테이블 (속보 모드에서 분류된 기사 추적)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alert_seen (
                    url_hash TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    importance INTEGER DEFAULT 0,
                    sent_alert INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)

            # 인덱스
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_seen_first_seen
                ON seen(first_seen_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_briefings_date
                ON briefings(date)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_articles_date
                ON articles(briefing_date)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_articles_category
                ON articles(category)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_articles_importance
                ON articles(importance)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_alert_seen_created
                ON alert_seen(created_at)
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

    def save_article(self, article, briefing_date: str):
        """기사 하나를 articles 테이블에 저장"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR IGNORE INTO articles
                   (url_hash, url, title, source, summary, published_at,
                    category, importance, scope, ai_summary, ai_comment,
                    response_needed, briefing_date, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    article.url_hash,
                    article.url,
                    article.title,
                    article.source,
                    article.summary,
                    article.published_at.isoformat() if article.published_at else None,
                    article.category,
                    article.importance,
                    article.scope,
                    article.ai_summary,
                    article.ai_comment,
                    getattr(article, "response_needed", "none"),
                    briefing_date,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

    def save_articles(self, articles: list, briefing_date: str):
        """여러 기사를 articles 테이블에 일괄 저장"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for article in articles:
                cursor.execute(
                    """INSERT OR IGNORE INTO articles
                       (url_hash, url, title, source, summary, published_at,
                        category, importance, scope, ai_summary, ai_comment,
                        response_needed, briefing_date, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        article.url_hash,
                        article.url,
                        article.title,
                        article.source,
                        article.summary,
                        article.published_at.isoformat() if article.published_at else None,
                        article.category,
                        article.importance,
                        article.scope,
                        article.ai_summary,
                        article.ai_comment,
                        getattr(article, "response_needed", "none"),
                        briefing_date,
                        datetime.now().isoformat(),
                    ),
                )
            conn.commit()
        logger.info(f"기사 {len(articles)}건 개별 저장 완료")

    def save_briefing(
        self,
        date: str,
        article_count: int = 0,
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
                   (date, article_count, sent_telegram, sent_email,
                    haiku_tokens_in, haiku_tokens_out,
                    sonnet_tokens_in, sonnet_tokens_out,
                    estimated_cost_usd, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    date,
                    article_count,
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
            logger.info(f"브리핑 기록 저장 완료 (기사 {article_count}건, 비용: ${estimated_cost_usd:.4f})")

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
        """오래된 seen 및 alert_seen 레코드 삭제 (articles는 보존)"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM seen WHERE first_seen_at < ?", (cutoff,))
            deleted_seen = cursor.rowcount
            cursor.execute("DELETE FROM alert_seen WHERE created_at < ?", (cutoff,))
            deleted_alert = cursor.rowcount
            conn.commit()

        if deleted_seen > 0 or deleted_alert > 0:
            logger.info(f"오래된 기록 정리 완료 (seen {deleted_seen}건, alert_seen {deleted_alert}건 삭제)")

    def prune(
        self,
        article_days: int = DEFAULT_ARTICLE_RETENTION_DAYS,
        seen_days: int = DEFAULT_SEEN_RETENTION_DAYS,
        max_db_size_mb: float = DEFAULT_MAX_DB_SIZE_MB,
    ) -> dict:
        """보존 기간이 지난 레코드를 삭제하고, DB 파일을 상한 크기 아래로 유지한다.

        state/seen.db는 모든 실행에서 git에 커밋되고, GitHub은 파일 하나가
        100MB를 넘으면 push를 거부한다(2026-11 오류의 원인).
        articles는 계속 쌓이기만 하고 VACUUM도 하지 않아 파일이 100MB까지
        자랐으므로, 여기서

        1. 보존 기간(기본 45일)이 지난 기사와 중복 기록(30일)을 지우고,
        2. 남은 빈 페이지를 VACUUM으로 회수하며,
        3. 그래도 max_db_size_mb를 넘으면 오래된 기사부터 추가로 지워
           파일 크기가 항상 상한 아래에 있도록 보장한다.

        Returns:
            실행 결과 통계 dict (before/after 크기, 삭제 건수)
        """
        max_bytes = int(max_db_size_mb * 1024 * 1024)
        before = self.db_path.stat().st_size if self.db_path.exists() else 0

        deleted_articles = 0
        deleted_seen = 0
        deleted_alerts = 0
        forced_deleted = 0

        # VACUUM은 트랜잭션 밖에서 실행해야 하므로 autocommit 모드로 연결
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        try:
            cursor = conn.cursor()
            art_cutoff = (datetime.now() - timedelta(days=article_days)).strftime("%Y-%m-%d")
            seen_cutoff = (datetime.now() - timedelta(days=seen_days)).isoformat()

            cursor.execute("DELETE FROM articles WHERE briefing_date < ?", (art_cutoff,))
            deleted_articles = cursor.rowcount if cursor.rowcount > 0 else 0
            cursor.execute("DELETE FROM seen WHERE first_seen_at < ?", (seen_cutoff,))
            deleted_seen = cursor.rowcount if cursor.rowcount > 0 else 0
            cursor.execute("DELETE FROM alert_seen WHERE created_at < ?", (seen_cutoff,))
            deleted_alerts = cursor.rowcount if cursor.rowcount > 0 else 0

            # 지운 페이지가 있을 때만 파일을 다시 쓴다(불필요한 전체 재작성 방지)
            freelist = cursor.execute("PRAGMA freelist_count").fetchone()[0]
            if deleted_articles or deleted_seen or deleted_alerts or freelist:
                cursor.execute("VACUUM")

            size = self.db_path.stat().st_size

            # 상한을 넘으면 오래된 기사부터 10%씩 추가 삭제 (안전망)
            for _ in range(20):
                if size <= max_bytes:
                    break

                total = cursor.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
                if total > 0:
                    chunk = max(100, total // 10)
                    cursor.execute(
                        """DELETE FROM articles WHERE id IN (
                               SELECT id FROM articles
                               ORDER BY briefing_date, id
                               LIMIT ?)""",
                        (chunk,),
                    )
                else:
                    total_seen = cursor.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
                    if total_seen == 0:
                        break
                    chunk = max(100, total_seen // 10)
                    cursor.execute(
                        """DELETE FROM seen WHERE url_hash IN (
                               SELECT url_hash FROM seen
                               ORDER BY first_seen_at
                               LIMIT ?)""",
                        (chunk,),
                    )

                removed = cursor.rowcount if cursor.rowcount > 0 else 0
                if removed == 0:
                    break
                forced_deleted += removed
                cursor.execute("VACUUM")
                size = self.db_path.stat().st_size
        finally:
            conn.close()

        after = self.db_path.stat().st_size if self.db_path.exists() else 0
        stats = {
            "size_before_bytes": before,
            "size_after_bytes": after,
            "deleted_articles": deleted_articles,
            "deleted_seen": deleted_seen,
            "deleted_alerts": deleted_alerts,
            "forced_deleted": forced_deleted,
        }

        forced_note = f", 상한 초과로 {forced_deleted}건 추가 삭제" if forced_deleted else ""
        logger.info(
            "DB 정리 완료: {:.2f}MB → {:.2f}MB (기사 {}건, seen {}건, alert_seen {}건 삭제{})".format(
                before / 1024 / 1024,
                after / 1024 / 1024,
                deleted_articles,
                deleted_seen,
                deleted_alerts,
                forced_note,
            )
        )

        if after > max_bytes:
            logger.warning(
                "DB 크기가 상한({:.0f}MB)을 넘었습니다: {:.2f}MB".format(
                    max_db_size_mb, after / 1024 / 1024
                )
            )

        return stats

    def get_recent_articles(self, days: int = 7) -> list[dict]:
        """최근 N일간 저장된 기사 목록 반환 (이슈 추적 및 주간 요약용, 오늘 포함 N일)"""
        cutoff = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """SELECT url_hash, url, title, source, summary, published_at,
                          category, importance, scope, ai_summary, ai_comment,
                          response_needed, briefing_date, created_at
                   FROM articles
                   WHERE briefing_date >= ?
                   ORDER BY briefing_date DESC, importance DESC""",
                (cutoff,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def is_alert_processed(self, url_hash: str) -> bool:
        """속보 점검에서 이미 처리했는지 확인"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM alert_seen WHERE url_hash = ?",
                (url_hash,),
            )
            return cursor.fetchone() is not None
    def get_alert_seen_hashes(self, days: int = 7) -> Set[str]:
        """최근 N일간 속보 점검으로 처리된 url_hash 목록"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT url_hash FROM alert_seen WHERE created_at >= ?",
                (cutoff,),
            )
            return {row[0] for row in cursor.fetchall()}

    def mark_alert_processed(
        self, url_hash: str, url: str, title: str, importance: int, sent_alert: bool
    ):
        """속보 점검 기사 처리 기록"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR REPLACE INTO alert_seen
                   (url_hash, url, title, importance, sent_alert, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    url_hash,
                    url,
                    title,
                    importance,
                    1 if sent_alert else 0,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
