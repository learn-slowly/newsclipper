"""
주간 요약 보고서 생성 모듈

지난 7일간 DB에 저장된 기사 데이터를 집계하여
Sonnet 4.6으로 주간 뉴스 트렌드 및 핵심 이슈 요약 보고서를 생성한다.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
from loguru import logger

from src.storage import Storage

# 주간 요약 프롬프트 파일 경로
PROMPT_PATH = Path(__file__).parent / "prompts" / "weekly_summary.txt"
SONNET_MODEL = "claude-sonnet-4-6"


def _load_prompt() -> str:
    """주간 요약 프롬프트 텍스트 로드"""
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def generate_weekly_summary(
    storage: Storage, api_key: str, days: int = 7
) -> tuple[str, str, str, int, int, int]:
    """지난 N일간의 기사 데이터를 기반으로 주간 요약 생성

    Returns:
        (summary_text, start_date_str, end_date_str, total_articles, tokens_in, tokens_out)
    """
    recent_articles = storage.get_recent_articles(days=days)
    if not recent_articles:
        logger.warning("주간 요약 대상 기사가 없습니다")
        return "", "", "", 0, 0, 0

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days - 1)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    # 1. 분야별 집계
    category_counts = {}
    important_articles = []
    response_needed_articles = []

    for a in recent_articles:
        cat = a.get("category") or "기타"
        category_counts[cat] = category_counts.get(cat, 0) + 1

        if a.get("importance", 0) >= 4:
            important_articles.append({
                "title": a.get("title"),
                "source": a.get("source"),
                "category": a.get("category"),
                "importance": a.get("importance"),
                "summary": a.get("ai_summary") or a.get("summary"),
                "comment": a.get("ai_comment"),
                "date": a.get("briefing_date"),
            })

        if a.get("response_needed") == "high":
            response_needed_articles.append({
                "title": a.get("title"),
                "source": a.get("source"),
                "category": a.get("category"),
                "date": a.get("briefing_date"),
            })

    # 상위 중요 기사 15건으로 제한 (토큰 절약 및 노이즈 방지)
    important_articles = important_articles[:15]

    data_payload = {
        "period": f"{start_str} ~ {end_str}",
        "total_articles": len(recent_articles),
        "category_counts": category_counts,
        "top_important_articles": important_articles,
        "action_needed_articles": response_needed_articles[:5],
    }

    prompt_template = _load_prompt()
    prompt = prompt_template.replace(
        "{weekly_data_json}", json.dumps(data_payload, ensure_ascii=False, indent=2)
    )

    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model=SONNET_MODEL,
            max_tokens=1500,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )

        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens
        summary_text = response.content[0].text.strip()

        logger.info(
            f"주간 요약 생성 완료 (기사 {len(recent_articles)}건, 토큰 In: {tokens_in}, Out: {tokens_out})"
        )
        return summary_text, start_str, end_str, len(recent_articles), tokens_in, tokens_out

    except Exception as e:
        logger.error(f"주간 요약 생성 실패: {e}")
        return "", start_str, end_str, len(recent_articles), 0, 0
