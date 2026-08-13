"""
이슈 경과 추적 모듈

DB에 축적된 최근 7일간의 기사 데이터를 바탕으로
동일 이슈가 며칠 동안 이어지고 있는지 탐지하고 맥락 정보를 부여한다.
"""

from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Optional

from loguru import logger

from src.collect import Article
from src.storage import Storage

# 같은 사건 판정 임계값 (section_builder.py와 동일)
TITLE_SIMILARITY_THRESHOLD = 0.45


def _title_similarity(a: str, b: str) -> float:
    """두 제목의 유사도 (0.0 ~ 1.0)"""
    return SequenceMatcher(None, a, b).ratio()


def attach_issue_context(
    articles: list[Article], storage: Storage, days: int = 7
) -> list[Article]:
    """기사 리스트에 최근 DB 기록 기반 이슈 경과 맥락(ongoing_context) 추가

    Args:
        articles: 분류가 완료된 기사 리스트
        storage: Storage 인스턴스
        days: 추적할 과거 기간(일 단위, 기본값 7일)

    Returns:
        ongoing_context가 채워진 기사 리스트
    """
    past_articles = storage.get_recent_articles(days=days)
    if not past_articles:
        return articles

    annotated_count = 0

    today_str = datetime.now().strftime("%Y-%m-%d")

    for article in articles:
        # 중요도 4점 미만이거나 이미 맥락이 있으면 스킵
        if article.importance < 4 or article.ongoing_context:
            continue

        matched_dates = set()
        matched_total = 1  # 현재 기사 포함

        for past in past_articles:
            # 동일 URL이면 비교 제외
            if past["url_hash"] == article.url_hash:
                continue

            similarity = _title_similarity(article.title, past["title"])
            if similarity >= TITLE_SIMILARITY_THRESHOLD:
                past_date = past.get("briefing_date") or past.get("created_at", "")[:10]
                if past_date:
                    matched_dates.add(past_date)
                matched_total += 1

        # 오늘 날짜 추가
        matched_dates.add(today_str)
        day_count = len(matched_dates)

        # 2건 이상 묶이거나 2일 이상 이어진 경우 맥락 표시
        if matched_total >= 2:
            if day_count >= 2:
                article.ongoing_context = (
                    f"📋 {day_count}일째 진행 중 (이번 주 {matched_total}건)"
                )
            else:
                article.ongoing_context = f"📋 이번 주 {matched_total}번째 관련 기사"
            annotated_count += 1

    if annotated_count > 0:
        logger.info(f"이슈 경과 맥락 부여: {annotated_count}건")

    return articles
