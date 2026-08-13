"""
storage.py의 response_needed 저장 및 조회 테스트
"""

import tempfile
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

        storage.save_articles([art], briefing_date="2026-08-13")

        recent = storage.get_recent_articles(days=7)
        assert len(recent) == 1
        assert recent[0]["response_needed"] == "high"
        assert recent[0]["title"] == "대응 필요 테스트 기사"
