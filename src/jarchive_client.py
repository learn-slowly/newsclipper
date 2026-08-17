"""jarchive 검색 연동 모듈

jarchive(논평 아카이브) 웹사이트의 검색 기능을 불러서
뉴스 기사와 관련된 중앙당·경남도당 논평을 찾는다.

기존 구글시트 방식(jpnews_reader.py)보다 정확하다:
- 뜻으로 찾기(의미 검색) + 단어로 찾기를 함께 씀
- 경남도당 논평도 포함됨 (시트에는 중앙당만 있었음)

jarchive 접속 자체가 안 되면 JarchiveUnavailable 예외를 던진다.
main.py에서 이 예외를 잡아 시트 방식으로 전환한다.
관련 논평이 없는 것은 정상이며 None을 돌려준다.
"""

from dataclasses import dataclass

import httpx
from loguru import logger


class JarchiveUnavailable(Exception):
    """jarchive 서버 접속 실패 (네트워크·서버 오류)"""


# jarchive 검색 결과 하나
@dataclass
class MatchedStatement:
    """jarchive에서 찾은 논평"""
    title: str        # 논평 제목
    date: str         # 발표일 (YYYY-MM-DD)
    doc_type: str     # 논평, 성명, 보도자료
    issuer: str       # 중앙당 / 경남도당
    link: str         # 원문 링크
    score: int        # 검색 점수 (0~100)

# 이 점수 미만이면 관련 없는 논평으로 판단해 버린다
MIN_MATCH_SCORE = 40

# jarchive 호출 제한 시간 (초)
REQUEST_TIMEOUT = 10


def search_statements(
    api_url: str,
    query: str,
    topic: str | None = None,
    limit: int = 3,
) -> list[MatchedStatement]:
    """jarchive에서 논평을 검색한다.

    Args:
        api_url: jarchive 주소 (예: https://jarchive.vercel.app)
        query: 검색어 (보통 뉴스 기사 제목)
        topic: 주제 필터 (labor, climate 등). 없으면 전체 검색
        limit: 최대 결과 수

    Returns:
        검색된 논평 목록 (빈 목록 = 관련 논평 없음)

    Raises:
        JarchiveUnavailable: 접속 실패 시
    """
    url = f"{api_url.rstrip('/')}/api/search"
    params: dict = {"q": query, "limit": limit}
    if topic:
        params["topic"] = topic

    try:
        resp = httpx.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise JarchiveUnavailable(f"jarchive 접속 실패: {e}") from e

    data = resp.json()
    if not data.get("success"):
        raise JarchiveUnavailable(f"jarchive 응답 오류: {data.get('error', '알 수 없음')}")

    results: list[MatchedStatement] = []
    for item in data.get("results", []):
        score = item.get("score", 0)
        if score < MIN_MATCH_SCORE:
            continue
        results.append(MatchedStatement(
            title=item.get("title", ""),
            date=item.get("published_at", ""),
            doc_type=item.get("doc_type", ""),
            issuer=item.get("issuer", "중앙당"),
            link=item.get("source_url", ""),
            score=score,
        ))

    return results


def find_best_match(
    api_url: str,
    article_title: str,
    category: str,
) -> MatchedStatement | None:
    """뉴스 기사 제목으로 가장 관련 높은 논평 1건을 찾는다.

    1순위: 같은 주제(category)로 좁혀서 검색
    2순위: 주제 없이 전체 검색 (주제 분류가 다를 수 있으므로)

    둘 다 결과가 없으면 None (정상 — 관련 논평이 없는 것).
    접속 실패 시 JarchiveUnavailable 예외가 올라간다.
    """
    # 1순위: 주제 필터 있는 검색
    results = search_statements(api_url, article_title, topic=category, limit=3)

    if results:
        return results[0]

    # 2순위: 전체 검색 (주제가 다르게 분류됐을 수 있음)
    results = search_statements(api_url, article_title, topic=None, limit=3)

    return results[0] if results else None
