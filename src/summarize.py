"""
2차 요약 모듈 (Claude Sonnet)

중요도 기준 통과한 기사에 대해 AI 요약 + 도당 활동 관점 코멘트를 생성한다.
"""

import json
from pathlib import Path
from typing import Optional

import anthropic
from loguru import logger

from src.collect import Article


# ── 상수 ────────────────────────────────────
SONNET_MODEL = "claude-sonnet-4-6-20250514"

# 요약 프롬프트 파일 경로
PROMPT_PATH = Path(__file__).parent / "prompts" / "summarize.txt"

# 중요도 임계값: 이 점수 이상만 Sonnet 요약 처리
IMPORTANCE_THRESHOLD = 3

# 월 비용 초과 시 상향되는 임계값
IMPORTANCE_THRESHOLD_HIGH = 4

# 월 비용 한도 (달러)
MONTHLY_COST_LIMIT = 30.0


def _load_prompt() -> str:
    """요약 프롬프트 텍스트 로드"""
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def summarize_article(
    article: Article,
    client: anthropic.Anthropic,
    prompt_template: Optional[str] = None,
) -> dict:
    """단일 기사 요약

    Args:
        article: 요약할 기사
        client: Anthropic 클라이언트
        prompt_template: 프롬프트 템플릿 (테스트용)

    Returns:
        {"summary": str, "comment": str,
         "tokens_in": int, "tokens_out": int}
    """
    template = prompt_template or _load_prompt()

    # 본문이 없으면 RSS 요약문을 사용
    content = article.summary or article.title

    prompt = template.format(
        title=article.title,
        source=article.source,
        category=article.category,
        scope=article.scope,
        content=content,
    )

    try:
        response = client.messages.create(
            model=SONNET_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens

        text = response.content[0].text.strip()
        result = json.loads(text)

        return {
            "summary": result.get("summary", ""),
            "comment": result.get("comment", ""),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }

    except json.JSONDecodeError as e:
        logger.warning(f"요약 JSON 파싱 실패 [{article.title[:30]}]: {e}")
        return {"summary": "", "comment": "", "tokens_in": 0, "tokens_out": 0}
    except anthropic.APIError as e:
        logger.error(f"Sonnet API 오류 [{article.title[:30]}]: {e}")
        return {"summary": "", "comment": "", "tokens_in": 0, "tokens_out": 0}


def summarize_articles(
    articles: list[Article],
    api_key: str,
    monthly_cost: float = 0.0,
) -> tuple[list[Article], int, int]:
    """중요도 기준 통과한 기사만 요약

    Args:
        articles: 분류 완료된 기사 리스트
        api_key: Anthropic API 키
        monthly_cost: 이번 달 누적 비용 (비용 관리용)

    Returns:
        (요약 완료된 기사 리스트, 총 입력 토큰, 총 출력 토큰)
    """
    # 월 비용 한도 초과 시 임계값 상향
    threshold = IMPORTANCE_THRESHOLD
    if monthly_cost >= MONTHLY_COST_LIMIT:
        threshold = IMPORTANCE_THRESHOLD_HIGH
        logger.warning(
            f"월 비용 ${monthly_cost:.2f} → 임계값 {threshold}점으로 상향"
        )

    # 임계값 이상인 기사만 필터링
    to_summarize = [a for a in articles if a.importance >= threshold]

    logger.info(
        f"요약 대상: {len(to_summarize)}건 "
        f"(전체 {len(articles)}건 중 중요도 {threshold}점 이상)"
    )

    if not to_summarize:
        return articles, 0, 0

    client = anthropic.Anthropic(api_key=api_key)
    prompt_template = _load_prompt()

    total_tokens_in = 0
    total_tokens_out = 0

    for article in to_summarize:
        result = summarize_article(article, client, prompt_template)

        article.ai_summary = result["summary"]
        article.ai_comment = result["comment"]
        total_tokens_in += result["tokens_in"]
        total_tokens_out += result["tokens_out"]

    logger.info(
        f"요약 완료: {len(to_summarize)}건 "
        f"(토큰: 입력 {total_tokens_in}, 출력 {total_tokens_out})"
    )

    return articles, total_tokens_in, total_tokens_out
