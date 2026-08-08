"""classify 모듈 단위 테스트

분류 성공/실패에 따라 classified_ok 플래그가 올바르게 세팅되는지 검증한다.
이 플래그는 수집 단계 seen 기록(재수집 방지 + 장애 기사 복구)의 기준이 되므로 중요하다.
OpenAI API 호출은 모두 모킹한다 — 실제 호출 금지(CLAUDE.md 규칙).
"""

from unittest.mock import MagicMock

import httpx

from src.classify import classify_article
from src.collect import Article


def _make_client(text: str = None, raise_exc: Exception = None) -> MagicMock:
    """OpenAI용 httpx 클라이언트 모킹 헬퍼"""
    client = MagicMock()
    if raise_exc is not None:
        client.post.side_effect = raise_exc
    else:
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        client.post.return_value = resp
    return client


# 본문 길이 가드를 넘기 위한 충분히 긴 요약
_LONG_SUMMARY = "정의당 경남도당이 노동 정책을 발표했다. " * 5
_TEMPLATE = "제목:{title}\n요약:{summary}\n매체:{source}"


def _make_article() -> Article:
    return Article(
        title="정의당 경남도당 노동 정책 발표",
        url="http://example.com/1",
        source="경남도민일보",
        summary=_LONG_SUMMARY,
    )


def test_분류_성공시_classified_ok_True():
    """정상 JSON 응답이면 classified_ok=True"""
    client = _make_client(
        text='{"category":"justice_party","importance":4,"scope":"gyeongnam"}'
    )
    result = classify_article(_make_article(), client, _TEMPLATE)

    assert result["classified_ok"] is True
    assert result["category"] == "justice_party"
    assert result["importance"] == 4


def test_API_오류시_classified_ok_False():
    """크레딧 소진 등 API 오류면 classified_ok=False (재시도 대상)"""
    client = _make_client(raise_exc=httpx.ConnectError("connection failed"))
    result = classify_article(_make_article(), client, _TEMPLATE)

    assert result["classified_ok"] is False
    assert result["importance"] == 1  # FALLBACK_IMPORTANCE


def test_HTTP_오류시_classified_ok_False():
    """서버가 오류 코드를 돌려주면 classified_ok=False"""
    client = MagicMock()
    resp = MagicMock()
    resp.status_code = 429
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "rate limited", request=MagicMock(), response=MagicMock(status_code=429)
    )
    client.post.return_value = resp
    result = classify_article(_make_article(), client, _TEMPLATE)

    assert result["classified_ok"] is False


def test_JSON_파싱_실패시_classified_ok_False():
    """응답이 JSON이 아니면 classified_ok=False"""
    client = _make_client(text="이건 JSON이 아닙니다")
    result = classify_article(_make_article(), client, _TEMPLATE)

    assert result["classified_ok"] is False
