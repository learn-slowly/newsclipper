"""
[일회성 시험 스크립트] Haiku vs GPT-5.6 Luna 분류 비교

운영 파이프라인과 무관하다. state/seen.db에 저장된 과거 기사(Haiku가 분류한 결과)를
GPT-5.6 Luna에게 같은 프롬프트로 다시 분류시켜 일치율을 잰다.

실행: .venv/bin/python scripts/compare_luna.py
출력: 화면 요약 + logs/luna_compare_YYYYMMDD.md (불일치 목록 포함)
"""

import asyncio
import json
import random
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).parent.parent
PROMPT_PATH = ROOT / "src" / "prompts" / "classify.txt"
DB_PATH = ROOT / "state" / "seen.db"

LUNA_MODEL = "gpt-5.6-luna"
SAMPLE_SIZE = 200          # 무작위 표본 크기 (정당 기사는 전수 포함)
CONCURRENCY = 8            # 동시 요청 수
SINCE_DATE = "2026-08-01"  # 이 날짜 이후 기사만

# Luna 단가 (USD / 1M tokens) — 2026-08 기준
LUNA_INPUT_COST = 0.20 / 1_000_000
LUNA_OUTPUT_COST = 1.20 / 1_000_000

VALID_CATEGORIES = {
    "labor", "climate", "gender_minority", "youth", "welfare_care",
    "regional_politics", "justice_party", "allied_parties", "other",
}


def load_sample() -> list[dict]:
    """비교용 기사 표본 추출.

    정당 카테고리(justice_party, allied_parties)는 건수가 적고 제일 민감한
    구분이라 전수 포함하고, 나머지는 무작위로 채워 총 SAMPLE_SIZE건을 만든다.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    base = (
        "select title, summary, source, category, importance, scope "
        "from articles where briefing_date >= ? and category != ''"
    )
    party = [dict(r) for r in conn.execute(
        base + " and category in ('justice_party','allied_parties')", (SINCE_DATE,)
    )]
    others = [dict(r) for r in conn.execute(
        base + " and category not in ('justice_party','allied_parties')", (SINCE_DATE,)
    )]
    conn.close()

    random.seed(42)  # 재실행해도 같은 표본이 뽑히게 고정
    fill = max(0, SAMPLE_SIZE - len(party))
    sample = party + random.sample(others, min(fill, len(others)))
    return sample


async def classify_with_luna(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, prompt: str
) -> dict:
    """Luna에게 분류 요청. 운영 코드(classify.py)와 같은 방식으로 JSON 파싱."""
    body = {
        "model": LUNA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": 2000,   # 내부 추론 토큰 여유분 포함
        "reasoning_effort": "minimal",   # 분류엔 깊은 추론 불필요 → 최소로
    }
    async with sem:
        for attempt in (1, 2):
            try:
                r = await client.post("/v1/chat/completions", json=body)
                if r.status_code == 400 and "reasoning_effort" in body:
                    # 파라미터 미지원 모델이면 빼고 재시도
                    body.pop("reasoning_effort")
                    continue
                r.raise_for_status()
                data = r.json()
                text = data["choices"][0]["message"]["content"].strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                result = json.loads(text)
                usage = data.get("usage", {})
                cat = result.get("category", "other")
                imp = result.get("importance", 1)
                return {
                    "category": cat if cat in VALID_CATEGORIES else "other",
                    "importance": imp if isinstance(imp, int) and 1 <= imp <= 5 else 1,
                    "scope": result.get("scope", "national"),
                    "tokens_in": usage.get("prompt_tokens", 0),
                    "tokens_out": usage.get("completion_tokens", 0),
                    "ok": True,
                }
            except (json.JSONDecodeError, KeyError, IndexError):
                if attempt == 2:
                    return {"ok": False, "error": "응답 파싱 실패"}
            except httpx.HTTPStatusError as e:
                if attempt == 2:
                    return {"ok": False, "error": f"HTTP {e.response.status_code}"}
                await asyncio.sleep(2)
    return {"ok": False, "error": "재시도 소진"}


async def main():
    env = dotenv_values(ROOT / ".env")
    api_key = env.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY가 .env에 없습니다")
        sys.exit(1)

    template = PROMPT_PATH.read_text(encoding="utf-8")
    sample = load_sample()
    party_count = sum(
        1 for a in sample if a["category"] in ("justice_party", "allied_parties")
    )
    print(f"표본: {len(sample)}건 (정당 기사 전수 {party_count}건 포함)")

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(
        base_url="https://api.openai.com",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=60,
    ) as client:
        tasks = []
        for a in sample:
            prompt = template.format(
                title=a["title"],
                summary=a["summary"] or "(요약 없음)",
                source=a["source"],
            )
            tasks.append(classify_with_luna(client, sem, prompt))
        results = await asyncio.gather(*tasks)

    # ── 채점 ─────────────────────────────────
    ok = [(a, r) for a, r in zip(sample, results) if r.get("ok")]
    failed = len(sample) - len(ok)

    cat_match = sum(1 for a, r in ok if a["category"] == r["category"])
    imp_exact = sum(1 for a, r in ok if a["importance"] == r["importance"])
    imp_near = sum(1 for a, r in ok if abs(a["importance"] - r["importance"]) <= 1)
    # 발송 결정(중요도 4점 이상) 일치 — 실질적으로 제일 중요한 지표
    send_match = sum(
        1 for a, r in ok if (a["importance"] >= 4) == (r["importance"] >= 4)
    )
    # 정의당/진보당 혼동: Haiku가 allied인데 Luna가 justice로 (또는 반대)
    party_confusion = [
        (a, r) for a, r in ok
        if {a["category"], r["category"]} == {"justice_party", "allied_parties"}
    ]
    total_in = sum(r["tokens_in"] for _, r in ok)
    total_out = sum(r["tokens_out"] for _, r in ok)
    cost = total_in * LUNA_INPUT_COST + total_out * LUNA_OUTPUT_COST

    n = len(ok)
    lines = [
        f"# Luna 분류 비교 결과 ({datetime.now():%Y-%m-%d %H:%M})",
        "",
        f"- 표본 {len(sample)}건 중 성공 {n}건, 실패 {failed}건",
        f"- 카테고리 일치: {cat_match}/{n} ({cat_match/n*100:.1f}%)",
        f"- 중요도 정확 일치: {imp_exact}/{n} ({imp_exact/n*100:.1f}%)",
        f"- 중요도 ±1 이내: {imp_near}/{n} ({imp_near/n*100:.1f}%)",
        f"- 발송 결정(4점 경계) 일치: {send_match}/{n} ({send_match/n*100:.1f}%)",
        f"- 정의당↔연대정당 혼동: {len(party_confusion)}건",
        f"- 시험 비용: ${cost:.4f} (입력 {total_in:,} / 출력 {total_out:,} 토큰)",
        "",
        "## 불일치 목록 (카테고리 다르거나 발송 결정 갈린 것)",
        "",
        "| 제목 | 출처 | Haiku | Luna |",
        "|---|---|---|---|",
    ]
    for a, r in ok:
        cat_diff = a["category"] != r["category"]
        send_diff = (a["importance"] >= 4) != (r["importance"] >= 4)
        if cat_diff or send_diff:
            lines.append(
                f"| {a['title'][:40]} | {a['source']} "
                f"| {a['category']} {a['importance']}점 "
                f"| {r['category']} {r['importance']}점 |"
            )

    report = "\n".join(lines)
    out_path = ROOT / "logs" / f"luna_compare_{datetime.now():%Y%m%d}.md"
    out_path.write_text(report, encoding="utf-8")
    print()
    print("\n".join(lines[:10]))
    print(f"\n전체 보고서: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
