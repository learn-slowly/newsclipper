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



def test_response_needed_high_파싱():
    """response_needed=high가 정상 파싱됨"""
    client = _make_client(
        text='{"category":"labor","importance":5,"scope":"gyeongnam","response_needed":"high"}'
    )
    result = classify_article(_make_article(), client, _TEMPLATE)
    assert result["classified_ok"] is True
    assert result["response_needed"] == "high"


def test_response_needed_medium_파싱():
    """response_needed=medium이 정상 파싱됨"""
    client = _make_client(
        text='{"category":"labor","importance":3,"scope":"national","response_needed":"medium"}'
    )
    result = classify_article(_make_article(), client, _TEMPLATE)
    assert result["response_needed"] == "medium"


def test_response_needed_없으면_none():
    """응답에 response_needed가 없으면 기본값 none"""
    client = _make_client(
        text='{"category":"labor","importance":3,"scope":"national"}'
    )
    result = classify_article(_make_article(), client, _TEMPLATE)
    assert result["response_needed"] == "none"


def test_response_needed_잘못된_값_none으로():
    """response_needed에 허용되지 않은 값이면 none으로 변경"""
    client = _make_client(
        text='{"category":"labor","importance":3,"scope":"national","response_needed":"urgent"}'
    )
    result = classify_article(_make_article(), client, _TEMPLATE)
    assert result["response_needed"] == "none"


def test_분류_실패시_response_needed_none():
    """분류 실패(API 오류)면 response_needed도 기본값 none"""
    client = _make_client(raise_exc=httpx.ConnectError("fail"))
    result = classify_article(_make_article(), client, _TEMPLATE)
    assert result["classified_ok"] is False
    assert result["response_needed"] == "none"


def test_Article_기본값_none():
    """Article 생성 시 response_needed 기본값이 none"""
    art = Article(title="테스트", url="http://x.com", source="test")
    assert art.response_needed == "none"