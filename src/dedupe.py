"""
중복 제거 모듈

URL 해시 기반 DB 중복 체크 + 제목 유사도 기반 중복 제거를 수행한다.
"""

from difflib import SequenceMatcher

from loguru import logger

from src.collect import Article
from src.storage import Storage


# 제목 유사도 임계값 (0.0 ~ 1.0)
TITLE_SIMILARITY_THRESHOLD = 0.7


def filter_seen(articles: list[Article], storage: Storage) -> list[Article]:
    """DB에 이미 있는 기사 제거

    Args:
        articles: 수집된 기사 리스트
        storage: Storage 인스턴스

    Returns:
        새로운 기사만 남긴 리스트
    """
    seen_hashes = storage.get_seen_hashes()

    new_articles = [a for a in articles if a.url_hash not in seen_hashes]

    filtered = len(articles) - len(new_articles)
    if filtered > 0:
        logger.info(f"DB 중복 {filtered}건 제거")

    return new_articles


def _title_similarity(a: str, b: str) -> float:
    """두 제목의 유사도 (0.0 ~ 1.0)"""
    return SequenceMatcher(None, a, b).ratio()


def deduplicate_similar(articles: list[Article]) -> list[Article]:
    """제목 유사도 기반 중복 그룹화

    유사한 기사가 있으면 먼저 나온 기사만 남긴다.

    Args:
        articles: 기사 리스트

    Returns:
        유사 중복 제거된 리스트
    """
    if not articles:
        return []

    unique: list[Article] = []

    for article in articles:
        is_duplicate = False
        for kept in unique:
            if _title_similarity(article.title, kept.title) >= TITLE_SIMILARITY_THRESHOLD:
                is_duplicate = True
                break

        if not is_duplicate:
            unique.append(article)

    removed = len(articles) - len(unique)
    if removed > 0:
        logger.info(f"유사 제목 중복 {removed}건 제거")

    return unique
