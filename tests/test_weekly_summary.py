"""
weekly_summary.py 및 관련 포맷 함수 단위 테스트
"""

from unittest.mock import MagicMock, patch
from src.telegram_push import format_weekly_summary_message
from src.weekly_summary import generate_weekly_summary


def test_format_weekly_summary_message():
    """주간 요약 메시지 포맷팅 검증"""
    msg = format_weekly_summary_message(
        summary_text="📌 이번 주 3대 이슈\n1. STX 파업",
        start_date="2026-08-01",
        end_date="2026-08-07",
        total_articles=50,
    )

    assert "📊 [주간 브리핑]" in msg
    assert "2026-08-01 ~ 2026-08-07" in msg
    assert "50건" in msg
    assert "STX 파업" in msg


@patch("src.weekly_summary.anthropic.Anthropic")
def test_generate_weekly_summary(mock_anthropic_class):
    """주간 요약 생성 함수 검증 (모킹)"""
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="요약 본문 테스트")]
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 50
    mock_client.messages.create.return_value = mock_response

    storage = MagicMock()
    storage.get_recent_articles.return_value = [
        {"title": "기사 1", "category": "labor", "importance": 4, "briefing_date": "2026-08-10"}
    ]

    summary_text, start_str, end_str, total_cnt, tokens_in, tokens_out = (
        generate_weekly_summary(storage, api_key="fake-key", days=7)
    )

    assert summary_text == "요약 본문 테스트"
    assert total_cnt == 1
    assert tokens_in == 100
    assert tokens_out == 50
