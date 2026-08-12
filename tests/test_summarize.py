"""비용 안전장치 테스트

월 $30 한도 초과 시 요약 기준이 4→5점으로 올라가는 장치를 검증한다.
2026-08-11 발견: 기존에 올리는 값(4)과 원래 값(4)이 같아 고장 나 있었음.
이 테스트는 같은 고장이 재발하면 잡아준다.
"""

from unittest.mock import patch

from src.collect import Article
from src.summarize import summarize_articles


def _make_article(importance: int) -> Article:
    """테스트용 기사 생성"""
    a = Article.__new__(Article)
    a.title = f"테스트 기사 (중요도 {importance})"
    a.importance = importance
    a.content = "테스트 본문"
    a.ai_summary = ""
    a.ai_comment = ""
    return a


_MOCK_RESULT = {
    "summary": "요약",
    "comment": "코멘트",
    "tokens_in": 100,
    "tokens_out": 50,
}


@patch("src.summarize.summarize_article", return_value=_MOCK_RESULT)
def test_한도_미만이면_4점_기사_요약(mock_summarize):
    """월 비용이 $30 미만이면 4점 기사도 요약한다"""
    art = _make_article(importance=4)
    summarize_articles([art], "fake-key", monthly_cost=29.99)
    assert mock_summarize.called


@patch("src.summarize.summarize_article", return_value=_MOCK_RESULT)
def test_한도_도달하면_4점_기사_건너뜀(mock_summarize):
    """월 비용이 $30 이상이면 4점 기사는 요약하지 않는다"""
    art = _make_article(importance=4)
    summarize_articles([art], "fake-key", monthly_cost=30.00)
    assert not mock_summarize.called


@patch("src.summarize.summarize_article", return_value=_MOCK_RESULT)
def test_한도_도달해도_5점_기사는_요약(mock_summarize):
    """월 비용이 $30 이상이어도 5점 기사는 요약한다"""
    art = _make_article(importance=5)
    summarize_articles([art], "fake-key", monthly_cost=30.00)
    assert mock_summarize.called
