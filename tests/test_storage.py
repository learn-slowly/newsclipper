"""
storage.py의 response_needed 저장 및 조회 테스트
"""

import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from src.collect import Article
from src.storage import Storage


def test_storage_response_needed():
    """articles 테이블에 response_needed 저장 및 조회 검증"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_storage.db"
        storage = Storage(db_path)

        art = Article(
            title="대응 필요 테스트 기사",
            url="https://example.com/test1",
            source="도민일보",
            importance=5,
            category="labor",
            response_needed="high",
        )

        # get_recent_articles는 실행 시점 기준이므로 오늘 날짜로 저장한다
        today = datetime.now().strftime("%Y-%m-%d")
        storage.save_articles([art], briefing_date=today)

        recent = storage.get_recent_articles(days=7)
        assert len(recent) == 1
        assert recent[0]["response_needed"] == "high"
        assert recent[0]["title"] == "대응 필요 테스트 기사"


def _insert_article(conn, url_hash: str, briefing_date: str, text: str = ""):
    conn.execute(
        """INSERT INTO articles
           (url_hash, url, title, source, summary, ai_summary, ai_comment,
            briefing_date, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            url_hash,
            f"https://example.com/{url_hash}",
            f"기사 {url_hash}",
            "도민일보",
            text,
            text,
            text,
            briefing_date,
            f"{briefing_date}T08:00:00",
        ),
    )


def test_prune_removes_old_records_and_vacuums():
    """보존 기간이 지난 기사·중복 기록은 지우고 최근 것은 남긴다"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_prune.db"
        storage = Storage(db_path)

        today = datetime.now().date()
        old_day = (today - timedelta(days=100)).isoformat()
        recent_day = (today - timedelta(days=3)).isoformat()
        old_seen = (datetime.now() - timedelta(days=100)).isoformat()
        recent_seen = (datetime.now() - timedelta(days=1)).isoformat()

        conn = sqlite3.connect(db_path)
        _insert_article(conn, "old-hash", old_day, "가" * 2000)
        _insert_article(conn, "recent-hash", recent_day, "나" * 2000)
        conn.execute(
            "INSERT INTO seen (url_hash, url, title, first_seen_at) VALUES (?, ?, ?, ?)",
            ("old-hash", "https://example.com/old", "오래된 기사", old_seen),
        )
        conn.execute(
            "INSERT INTO seen (url_hash, url, title, first_seen_at) VALUES (?, ?, ?, ?)",
            ("recent-hash", "https://example.com/recent", "최근 기사", recent_seen),
        )
        conn.execute(
            """INSERT INTO alert_seen (url_hash, url, title, created_at)
               VALUES (?, ?, ?, ?)""",
            ("old-alert", "https://example.com/a", "오래된 속보", old_seen),
        )
        conn.commit()
        conn.close()

        stats = storage.prune(article_days=45, seen_days=30, max_db_size_mb=50)

        assert stats["deleted_articles"] == 1
        assert stats["deleted_seen"] == 1
        assert stats["deleted_alerts"] == 1

        conn = sqlite3.connect(db_path)
        assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1
        assert conn.execute("SELECT url_hash FROM articles").fetchone()[0] == "recent-hash"
        assert conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM alert_seen").fetchone()[0] == 0
        # VACUUM 후에는 빈 페이지가 남지 않는다
        assert conn.execute("PRAGMA freelist_count").fetchone()[0] == 0
        conn.close()


def test_prune_enforces_size_cap():
    """상한을 넘으면 오래된 기사부터 추가로 지워 파일 크기를 상한 아래로 만든다"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cap.db"
        storage = Storage(db_path)

        today = datetime.now().date()
        conn = sqlite3.connect(db_path)
        for i in range(300):
            day = (today - timedelta(days=i % 40)).isoformat()
            _insert_article(conn, f"hash-{i:04d}", day, "다" * 4000)
        conn.commit()
        conn.close()

        size_before = db_path.stat().st_size
        assert size_before > 1024 * 1024  # 1MB 이상은 되어야 상한 테스트가 의미 있다

        stats = storage.prune(article_days=45, seen_days=30, max_db_size_mb=1.0)

        assert stats["forced_deleted"] > 0
        assert stats["size_after_bytes"] <= 1024 * 1024
        assert db_path.stat().st_size == stats["size_after_bytes"]
