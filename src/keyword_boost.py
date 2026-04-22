"""
키워드 매칭 모듈

1. 사전 필터 (prefilter): 구글 알리미 등 비신뢰 소스 기사 중
   키워드가 하나도 없는 노이즈를 AI 분류 전에 걸러낸다.
2. 신뢰 매체 가산 (trusted boost): 기존 등록 매체 기사에 +1점.
3. 교차 매칭 가산 (cross boost): 지역명 × 카테고리 키워드 동시 매칭 시 +1점.
"""

from pathlib import Path

import yaml
from loguru import logger

from src.collect import Article


# ── 설정 파일 경로 ─────────────────────────────
KEYWORDS_PATH = Path(__file__).parent.parent / "config" / "keywords.yaml"

# 가산 후 최대 중요도
MAX_IMPORTANCE = 5


def load_keywords(path: Path = KEYWORDS_PATH) -> dict:
    """keywords.yaml 로드"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_cross_matches(text: str, regions: list[str], category_keywords: dict) -> list[dict]:
    """텍스트에서 지역명 × 카테고리 키워드 교차 매칭 검색

    Args:
        text: 검색 대상 텍스트 (제목 + 요약)
        regions: 지역명 리스트
        category_keywords: {"labor": ["노동", "파업", ...], ...}

    Returns:
        매칭 결과 리스트: [{"region": "창원", "category": "labor", "keyword": "파업"}, ...]
    """
    matched_regions = [r for r in regions if r in text]

    if not matched_regions:
        return []

    matches = []
    for category, keywords in category_keywords.items():
        for keyword in keywords:
            if keyword in text:
                for region in matched_regions:
                    matches.append({
                        "region": region,
                        "category": category,
                        "keyword": keyword,
                    })

    return matches


def prefilter_articles(
    articles: list[Article],
    trusted_sources: set[str],
    keywords_path: Path = KEYWORDS_PATH,
) -> tuple[list[Article], int]:
    """비신뢰 소스 기사 중 키워드가 없는 노이즈를 사전 필터링

    신뢰 매체(feeds.yaml에 등록된 기존 매체) 기사는 무조건 통과.
    구글 알리미 등 비신뢰 소스 기사는 제목+요약에 키워드가 하나라도 있어야 통과.

    Args:
        articles: 전체 기사 리스트
        trusted_sources: 신뢰 매체 이름 집합 (예: {"경남도민일보", "한겨레", ...})
        keywords_path: keywords.yaml 경로

    Returns:
        (필터 통과 기사 리스트, 필터링된 건수)
    """
    config = load_keywords(keywords_path)
    prefilter_kw = config.get("prefilter_keywords", [])

    if not prefilter_kw:
        logger.warning("사전 필터 키워드가 없어서 필터링을 건너뜁니다")
        return articles, 0

    passed = []
    filtered_count = 0

    for article in articles:
        # 신뢰 매체는 무조건 통과
        if article.source in trusted_sources:
            passed.append(article)
            continue

        # 비신뢰 소스: 키워드 매칭 검사
        text = f"{article.title} {article.summary}"
        if any(kw in text for kw in prefilter_kw):
            passed.append(article)
        else:
            filtered_count += 1
            logger.debug(f"사전 필터 제거: [{article.source}] {article.title[:40]}")

    logger.info(
        f"사전 필터: {len(articles)}건 → {len(passed)}건 통과 "
        f"({filtered_count}건 노이즈 제거)"
    )
    return passed, filtered_count


def apply_trusted_boost(
    articles: list[Article],
    trusted_sources: set[str],
    keywords_path: Path = KEYWORDS_PATH,
) -> list[Article]:
    """신뢰 매체 기사에 가산점 적용

    Args:
        articles: 분류 완료된 기사 리스트
        trusted_sources: 신뢰 매체 이름 집합
        keywords_path: keywords.yaml 경로

    Returns:
        가산 적용된 기사 리스트
    """
    config = load_keywords(keywords_path)
    boost = config.get("trusted_boost", 1)

    boosted_count = 0
    for article in articles:
        if article.source in trusted_sources:
            old = article.importance
            article.importance = min(article.importance + boost, MAX_IMPORTANCE)
            if article.importance > old:
                boosted_count += 1

    logger.info(f"신뢰 매체 가산: {boosted_count}건에 +{boost}점 적용")
    return articles


def apply_keyword_boost(articles: list[Article], keywords_path: Path = KEYWORDS_PATH) -> list[Article]:
    """기사 리스트에 키워드 교차 매칭 가산 적용

    AI 분류(classify) 이후에 호출한다.
    지역명 + 카테고리 키워드가 동시에 매칭되면 중요도를 +N점 가산한다.

    Args:
        articles: 분류 완료된 기사 리스트
        keywords_path: keywords.yaml 경로

    Returns:
        가산 적용된 기사 리스트 (원본 수정)
    """
    config = load_keywords(keywords_path)
    regions = config.get("regions", [])
    category_keywords = config.get("categories", {})
    boost = config.get("boost_score", 1)

    boosted_count = 0

    for article in articles:
        # 제목 + 요약을 합쳐서 검색
        text = f"{article.title} {article.summary}"
        matches = find_cross_matches(text, regions, category_keywords)

        if matches:
            old_importance = article.importance
            article.importance = min(article.importance + boost, MAX_IMPORTANCE)

            # scope도 지역 매칭이면 gyeongnam 또는 both로 조정
            if article.scope == "national":
                article.scope = "both"

            boosted_count += 1
            matched_info = ", ".join(
                f"{m['region']}+{m['keyword']}" for m in matches[:3]
            )
            logger.debug(
                f"가산 적용: [{article.title[:30]}] "
                f"{old_importance}→{article.importance}점 ({matched_info})"
            )

    logger.info(f"키워드 교차 매칭 가산: {boosted_count}/{len(articles)}건에 +{boost}점 적용")
    return articles
