"""
1차 분류 모듈 (Claude Haiku)

기사 제목+요약을 Haiku에 넘겨서 카테고리·중요도·스코프를 분류한다.
"""

import json
from pathlib import Path
from typing import Optional

import anthropic
from loguru import logger

from src.collect import Article


# ── 상수 ────────────────────────────────────
HAIKU_MODEL = "claude-haiku-4-5-20241022"

# 분류 프롬프트 파일 경로
PROMPT_PATH = Path(__file__).parent / "prompts" / "classify.txt"

# 유효한 카테고리 목록
VALID_CATEGORIES = {
    "labor", "climate", "gender_minority", "youth", "welfare_care",
    "regional_politics", "justice_party", "allied_parties", "other",
}

# 유효한 스코프 목록
VALID_SCOPES = {"gyeongnam", "national", "both"}

# 분류 실패 시 기본값
FALLBACK_CATEGORY = "other"
FALLBACK_IMPORTANCE = 1
FALLBACK_SCOPE = "national"


def _load_prompt() -> str:
    """분류 프롬프트 텍스트 로드"""
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def classify_article(
    article: Article,
    client: anthropic.Anthropic,
    prompt_template: Optional[str] = None,
) -> dict:
    """단일 기사 분류

    Args:
        article: 분류할 기사
        client: Anthropic 클라이언트
        prompt_template: 프롬프트 템플릿 (테스트용, 없으면 파일에서 로드)

    Returns:
        {"category": str, "importance": int, "scope": str,
         "tokens_in": int, "tokens_out": int}
    """
    template = prompt_template or _load_prompt()

    prompt = template.format(
        title=article.title,
        summary=article.summary or "(요약 없음)",
        source=article.source,
    )

    try:
        response = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )

        # 토큰 사용량
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens

        # JSON 파싱
        text = response.content[0].text.strip()
        result = json.loads(text)

        # 값 검증
        category = result.get("category", FALLBACK_CATEGORY)
        if category not in VALID_CATEGORIES:
            logger.warning(f"유효하지 않은 카테고리 '{category}' → other로 변경")
            category = FALLBACK_CATEGORY

        importance = result.get("importance", FALLBACK_IMPORTANCE)
        if not isinstance(importance, int) or not (1 <= importance <= 5):
            importance = FALLBACK_IMPORTANCE

        scope = result.get("scope", FALLBACK_SCOPE)
        if scope not in VALID_SCOPES:
            scope = FALLBACK_SCOPE

        return {
            "category": category,
            "importance": importance,
            "scope": scope,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }

    except json.JSONDecodeError as e:
        logger.warning(f"분류 JSON 파싱 실패 [{article.title[:30]}]: {e}")
        return {
            "category": FALLBACK_CATEGORY,
            "importance": FALLBACK_IMPORTANCE,
            "scope": FALLBACK_SCOPE,
            "tokens_in": 0,
            "tokens_out": 0,
        }
    except anthropic.APIError as e:
        logger.error(f"Claude API 오류 [{article.title[:30]}]: {e}")
        return {
            "category": FALLBACK_CATEGORY,
            "importance": FALLBACK_IMPORTANCE,
            "scope": FALLBACK_SCOPE,
            "tokens_in": 0,
            "tokens_out": 0,
        }


def classify_articles(
    articles: list[Article],
    api_key: str,
) -> tuple[list[Article], int, int]:
    """여러 기사 일괄 분류

    Args:
        articles: 분류할 기사 리스트
        api_key: Anthropic API 키

    Returns:
        (분류된 기사 리스트, 총 입력 토큰, 총 출력 토큰)
    """
    client = anthropic.Anthropic(api_key=api_key)
    prompt_template = _load_prompt()

    total_tokens_in = 0
    total_tokens_out = 0

    for article in articles:
        result = classify_article(article, client, prompt_template)

        article.category = result["category"]
        article.importance = result["importance"]
        article.scope = result["scope"]
        total_tokens_in += result["tokens_in"]
        total_tokens_out += result["tokens_out"]

    # 통계 로그
    category_counts = {}
    for a in articles:
        category_counts[a.category] = category_counts.get(a.category, 0) + 1

    logger.info(
        f"분류 완료: {len(articles)}건 "
        f"(토큰: 입력 {total_tokens_in}, 출력 {total_tokens_out})"
    )
    for cat, count in sorted(category_counts.items()):
        logger.info(f"  {cat}: {count}건")

    return articles, total_tokens_in, total_tokens_out
