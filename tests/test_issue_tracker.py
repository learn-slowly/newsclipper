"""
issue_tracker.py 단위 테스트
"""

from unittest.mock import MagicMock
from src.collect import Article
from src.issue_tracker import attach_issue_context


def test_attach_issue_context_single():
    """과거 기사가 없으면 ongoing_context가 붙지 않는다"""
    storage = MagicMock()
    storage.get_recent_articles.return_value = []

    articles = [
        Article(title="STX 조선 파업", url="https://example.com/1", source="도민일보", importance=4)
    ]

    result = attach_issue_context(articles, storage)
    assert result[0].ongoing_context == ""


def test_attach_issue_context_matched():
    """유사 제목 기사가 과거 DB에 있으면 ongoing_context가 채워진다"""
    storage = MagicMock()
    storage.get_recent_articles.return_value = [
        {
            "url_hash": "different_hash",
            "url": "https://example.com/old",
            "title": "STX 조선 하청 노동자 파업",
            "source": "도민일보",
            "briefing_date": "2026-08-10",
        }
    ]

    articles = [
        Article(url="https://example.com/new", title="STX 조선 파업 계속", source="도민일보", importance=4)
    ]

    result = attach_issue_context(articles, storage)
    assert "이어진 이슈" in result[0].ongoing_context or "관련 기사" in result[0].ongoing_context


def test_attach_issue_context_gap_dates():
    """중간에 보도가 없었던 날짜 간격도 달력 기준 일수로 정확히 계산한다"""
    storage = MagicMock()
    storage.get_recent_articles.return_value = [
        {
            "url_hash": "gap_hash",
            "url": "https://example.com/gap",
            "title": "거제 조선소 산재 이슈",
            "source": "도민일보",
            "briefing_date": "2026-08-07",  # 오늘(8/13) 기준 7일째
        }
    ]

    articles = [
        Article(url="https://example.com/new_gap", title="거제 조선소 산재 추가 후속", source="도민일보", importance=4)
    ]

    result = attach_issue_context(articles, storage)
    assert "이어진 이슈" in result[0].ongoing_context
    assert "7일째" in result[0].ongoing_context
