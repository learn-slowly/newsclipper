"""
1차 분류 모듈 (OpenAI GPT-5.6 Luna)

기사 제목+요약을 Luna에 넘겨서 카테고리·중요도·스코프를 분류한다.
2026-08-08: Claude Haiku → GPT-5.6 Luna로 교체 (비교 시험 후 결정, 분류비 약 1/4).
프롬프트와 검증 규칙은 Haiku 시절 그대로 유지한다.
"""

import json
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

from src import MIN_CONTENT_LENGTH
from src.collect import Article


# ── 본문 미확인 시 프롬프트 앞에 prepend되는 가드 문구 ─────────────
LOW_CONTENT_GUARD = (
    "⚠️ 본문이 확보되지 않았다. 제목만 보고 분류하되, "
    "정당 카테고리(justice_party, allied_parties)나 importance 4-5점은 "
    "제목에 명시적 근거가 있을 때만 부여하라. 추측 금지.\n\n"
)


# ── 상수 ────────────────────────────────────
LUNA_MODEL = "gpt-5.6-luna"
OPENAI_BASE_URL = "https://api.openai.com"

# 응답은 JSON 한 줄이지만 모델 내부 추론 토큰 여유분을 포함해 넉넉히 잡는다
MAX_COMPLETION_TOKENS = 2000

# 분류 프롬프트 파일 경로
PROMPT_PATH = Path(__file__).parent / "prompts" / "classify.txt"

# 유효한 카테고리 목록
VALID_CATEGORIES = {
    "labor", "climate", "gender_minority", "youth", "welfare_care",
    "regional_politics", "justice_party", "allied_parties", "other",
}

# 유효한 스코프 목록
VALID_SCOPES = {"gyeongnam", "national", "both"}

# 유효한 대응 필요도 목록
VALID_RESPONSE_NEEDED = {"high", "medium", "none"}

# 분류 실패 시 기본값
FALLBACK_CATEGORY = "other"
FALLBACK_IMPORTANCE = 1
FALLBACK_SCOPE = "national"
FALLBACK_RESPONSE_NEEDED = "none"

_FALLBACK_RESULT = {
    "category": FALLBACK_CATEGORY,
    "importance": FALLBACK_IMPORTANCE,
    "scope": FALLBACK_SCOPE,
    "response_needed": FALLBACK_RESPONSE_NEEDED,
    "tokens_in": 0,
    "tokens_out": 0,
    "classified_ok": False,
}


def _load_prompt() -> str:
    """분류 프롬프트 텍스트 로드"""
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def classify_article(
    article: Article,
    client: httpx.Client,
    prompt_template: Optional[str] = None,
) -> dict:
    """단일 기사 분류

    Args:
        article: 분류할 기사
        client: OpenAI용 httpx 클라이언트 (base_url·인증 헤더 설정 완료 상태)
        prompt_template: 프롬프트 템플릿 (테스트용, 없으면 파일에서 로드)

    Returns:
        {"category": str, "importance": int, "scope": str,
         "tokens_in": int, "tokens_out": int, "classified_ok": bool}
    """
    template = prompt_template or _load_prompt()

    # 본문 미확인 체크 (제목 + RSS 요약 길이)
    content_length = len((article.title or "") + (article.summary or ""))
    is_low_content = content_length < MIN_CONTENT_LENGTH

    prompt = template.format(
        title=article.title,
        summary=article.summary or "(요약 없음)",
        source=article.source,
    )

    # 본문이 너무 짧으면 환각 방지용 가드 문구를 앞에 prepend
    if is_low_content:
        prompt = LOW_CONTENT_GUARD + prompt
        article.low_content = True

    body = {
        "model": LUNA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        # 분류엔 깊은 추론이 필요 없어 최소로 (속도·비용 절약)
        "reasoning_effort": "minimal",
    }

    try:
        response = client.post("/v1/chat/completions", json=body)
        if response.status_code == 400 and "reasoning_effort" in body:
            # 파라미터 미지원 모델로 바뀌었을 때를 대비한 안전장치
            body.pop("reasoning_effort")
            response = client.post("/v1/chat/completions", json=body)
        response.raise_for_status()
        data = response.json()

        # 토큰 사용량
        usage = data.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)

        # JSON 파싱 (```json 코드 블록 제거)
        text = data["choices"][0]["message"]["content"].strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
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

        response_needed = result.get("response_needed", FALLBACK_RESPONSE_NEEDED)
        if response_needed not in VALID_RESPONSE_NEEDED:
            response_needed = FALLBACK_RESPONSE_NEEDED

        return {
            "category": category,
            "importance": importance,
            "scope": scope,
            "response_needed": response_needed,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "classified_ok": True,
        }

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning(f"분류 응답 파싱 실패 [{article.title[:30]}]: {e}")
        return dict(_FALLBACK_RESULT)
    except httpx.HTTPError as e:
        logger.error(f"OpenAI API 오류 [{article.title[:30]}]: {e}")
        return dict(_FALLBACK_RESULT)


def classify_articles(
    articles: list[Article],
    api_key: str,
) -> tuple[list[Article], int, int]:
    """여러 기사 일괄 분류

    Args:
        articles: 분류할 기사 리스트
        api_key: OpenAI API 키

    Returns:
        (분류된 기사 리스트, 총 입력 토큰, 총 출력 토큰)
    """
    prompt_template = _load_prompt()

    total_tokens_in = 0
    total_tokens_out = 0

    with httpx.Client(
        base_url=OPENAI_BASE_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=60,
    ) as client:
        for article in articles:
            result = classify_article(article, client, prompt_template)

            article.category = result["category"]
            article.importance = result["importance"]
            article.scope = result["scope"]
            article.response_needed = result["response_needed"]
            article.classified_ok = result["classified_ok"]
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
