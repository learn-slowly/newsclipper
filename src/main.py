"""
clipboard055 메인 파이프라인

전체 실행 흐름:
1. RSS 수집 (collect)
2. DB 중복 제거 (dedupe - seen 테이블)
3. 제목 유사도 중복 제거 (dedupe - 유사 제목)
4. 1차 분류 (classify - Haiku)
5. 2차 요약 (summarize - Sonnet, 중요도 3점 이상)
6. 섹션 구성 (section_builder)
7. 텔레그램 발송 (telegram_push)
8. DB 기록 (storage - briefings)
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from src.collect import Article, collect_all, load_feeds
from src.classify import classify_articles
from src.keyword_boost import apply_keyword_boost, apply_trusted_boost, prefilter_articles
from src.scrape import scrape_all
from src.dedupe import deduplicate_similar, filter_seen
from src.section_builder import PHASE1_ACTIVE, build_sections
from src.storage import Storage
from src.summarize import summarize_articles
from src.telegram_push import format_briefing, send_error_alert, send_telegram


# ── 로거 설정 ─────────────────────────────────
def setup_logger():
    """로거 초기화"""
    logger.remove()  # 기본 핸들러 제거
    logger.add(
        sys.stderr,
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="<level>{level: <8}</level> | {message}",
    )

    # 파일 로그
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(
        log_dir / f"briefing_{datetime.now().strftime('%Y%m%d')}.log",
        level="DEBUG",
        rotation="1 day",
        retention="7 days",
        encoding="utf-8",
    )


# ── 비용 계산 ──────────��──────────────────────
# Haiku: 입력 $0.80/M, 출력 $4.00/M
# Sonnet: 입력 $3.00/M, 출력 $15.00/M
HAIKU_INPUT_COST_PER_TOKEN = 0.80 / 1_000_000
HAIKU_OUTPUT_COST_PER_TOKEN = 4.00 / 1_000_000
SONNET_INPUT_COST_PER_TOKEN = 3.00 / 1_000_000
SONNET_OUTPUT_COST_PER_TOKEN = 15.00 / 1_000_000

# 일일 비용 경고 임계값
DAILY_COST_WARNING = 1.5


def calculate_cost(
    haiku_in: int, haiku_out: int, sonnet_in: int, sonnet_out: int
) -> float:
    """토큰 사용량에서 비용 계산 (USD)"""
    return (
        haiku_in * HAIKU_INPUT_COST_PER_TOKEN
        + haiku_out * HAIKU_OUTPUT_COST_PER_TOKEN
        + sonnet_in * SONNET_INPUT_COST_PER_TOKEN
        + sonnet_out * SONNET_OUTPUT_COST_PER_TOKEN
    )


# ── 메인 파이프라인 ──────────────────────────────
async def run_pipeline():
    """브리핑 파이프라인 실행"""
    setup_logger()

    logger.info("=" * 50)
    logger.info("📰 clipboard055 브리핑 시작")
    logger.info(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)

    # 환경변수 로드
    load_dotenv()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")
    admin_id = os.getenv("TELEGRAM_ADMIN_USER_ID", "")

    if not api_key:
        logger.error("ANTHROPIC_API_KEY가 설정되지 않았습니다")
        sys.exit(1)
    if not bot_token or not channel_id:
        logger.error("TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHANNEL_ID가 설정되지 않았습니다")
        sys.exit(1)

    storage = Storage()

    try:
        # 신뢰 매체 목록 구성 (RSS: trusted 필드가 없거나 true인 매체 + 스크래핑 매체 전부)
        all_feeds = load_feeds()
        trusted_sources = {
            f["name"] for f in all_feeds
            if f.get("trusted", True) is True
        }
        # 스크래핑 매체도 신뢰 매체에 포함 (MBC경남, KNN, KBS경남 등)
        from src.scrape import load_scrape_config
        scrape_sources = load_scrape_config()
        for s in scrape_sources:
            trusted_sources.add(s["name"])
        logger.info(f"신뢰 매체: {len(trusted_sources)}개")

        # 1. RSS 수집 + 웹 스크래핑
        logger.info("📥 Step 1-a: RSS 수집")
        articles = collect_all(hours=24)

        logger.info("📥 Step 1-b: 웹 스크래핑 (경남 지역 매체)")
        scraped = scrape_all()
        articles.extend(scraped)

        if not articles:
            logger.warning("수집된 기사가 없습니다")
            return

        # URL 기준 중복 제거 (RSS와 스크래핑 간 겹칠 수 있음)
        seen_urls = set()
        unique = []
        for a in articles:
            if a.url not in seen_urls:
                seen_urls.add(a.url)
                unique.append(a)
        articles = unique

        total_collected = len(articles)

        # 2. DB 중복 제거
        logger.info("🔄 Step 2: 중복 제거")
        articles = filter_seen(articles, storage)

        if not articles:
            logger.info("새로운 기사가 없습니다")
            return

        # 3. 제목 유사도 중복 제거
        logger.info("🔗 Step 3: 유사 제목 중복 제��")
        articles = deduplicate_similar(articles)

        if not articles:
            logger.info("유사 중복 제거 후 기사가 없습니다")
            return

        logger.info(f"✨ 신규 기사: {len(articles)}건")

        # 3-b. 사전 키워드 필터 (구글 알리미 노이즈 제거)
        logger.info("🔍 Step 3-b: 사전 키워드 필터")
        articles, filtered_count = prefilter_articles(articles, trusted_sources)

        if not articles:
            logger.info("키워드 필터 후 기사가 없습니다")
            return

        # 4. 1차 분류 (Haiku)
        logger.info("🏷️ Step 4: AI 분류 (Haiku)")
        articles, haiku_in, haiku_out = classify_articles(articles, api_key)

        # 4-b. 키워드 교차 매칭 가산 (지역명 × 카테고리 키워드)
        logger.info("🔍 Step 4-b: 키워드 교차 매칭 가산")
        articles = apply_keyword_boost(articles)

        # 4-c. 신뢰 매체 가산
        logger.info("⭐ Step 4-c: 신뢰 매체 가산")
        articles = apply_trusted_boost(articles, trusted_sources)

        # 4-d. 분류 성공 기사 seen 기록 (재수집 방지)
        # 분류에 성공한 기사는 발송 여부와 무관하게 여기서 "이미 봤음"으로 기록한다.
        # 이렇게 하면 발송이 실패해도 같은 기사를 다음 실행 때 다시 수집하지 않는다.
        # 단, 크레딧 장애 등으로 분류 실패한 기사(classified_ok=False)는 기록하지 않아
        # 다음 실행 때 다시 시도할 수 있게 한다(복구 가능).
        classified_ok = [a for a in articles if a.classified_ok]
        for article in classified_ok:
            storage.mark_seen(article.url_hash, article.url, article.title)
        logger.info(f"💾 Step 4-d: 분류 성공 {len(classified_ok)}건 seen 기록")

        # 중요도 1점 제거
        articles = [a for a in articles if a.importance > 1]
        logger.info(f"중요도 2점 이상: {len(articles)}건")

        if not articles:
            logger.info("관련성 높은 기사가 없습니다")
            return

        # 5. 2차 요약 (Sonnet)
        logger.info("📝 Step 5: AI 요약 (Sonnet)")
        monthly_cost = storage.get_monthly_cost()
        articles, sonnet_in, sonnet_out = summarize_articles(
            articles, api_key, monthly_cost
        )

        # 비용 계산
        cost = calculate_cost(haiku_in, haiku_out, sonnet_in, sonnet_out)
        logger.info(f"💰 오늘 비용: ${cost:.4f}")

        if cost > DAILY_COST_WARNING:
            logger.warning(f"⚠️ 일일 비용 경고! ${cost:.4f} > ${DAILY_COST_WARNING}")

        # 6. 섹션 구성 (Phase 1: 5개 섹션)
        logger.info("📋 Step 6: 섹션 구성")
        sections = build_sections(articles, active_sections=PHASE1_ACTIVE)

        if not sections:
            logger.info("활성 섹션에 배치된 기사가 없습니다")
            return

        for s in sections:
            logger.info(f"  {s.emoji} {s.name}: {len(s.articles)}건")

        # 7. 텔레그램 발송
        logger.info("📤 Step 7: 텔레그램 발송")
        briefing_text = format_briefing(sections, total_collected)
        sent = await send_telegram(briefing_text, bot_token, channel_id)

        if not sent:
            logger.error("텔레그램 발송 실패")
            if admin_id:
                await send_error_alert("텔레그램 브리핑 발송 실패", bot_token, admin_id)

        # 8. DB 기록
        logger.info("💾 Step 8: 실행 기록 저장")
        today = datetime.now().strftime("%Y-%m-%d")

        # 처리한 기사를 seen에 기록 (안전망)
        # 대부분 Step 4-d에서 이미 기록됐지만, 분류 실패했어도 가산점으로
        # 브리핑에 포함돼 발송된 기사를 마저 기록한다. mark_seen은 중복 무시(IGNORE)라 안전하다.
        for article in articles:
            storage.mark_seen(article.url_hash, article.url, article.title)

        # 기사 개별 저장
        storage.save_articles(articles, briefing_date=today)

        # 브리핑 실행 기록 저장
        storage.save_briefing(
            date=today,
            article_count=len(articles),
            sent_telegram=sent,
            haiku_tokens_in=haiku_in,
            haiku_tokens_out=haiku_out,
            sonnet_tokens_in=sonnet_in,
            sonnet_tokens_out=sonnet_out,
            estimated_cost_usd=cost,
        )

        # 오래된 레코드 정리
        storage.cleanup_old_records(days=30)

    except Exception as e:
        logger.exception(f"파이프라인 오류: {e}")
        if admin_id and bot_token:
            await send_error_alert(f"파이프라인 오류: {e}", bot_token, admin_id)
        raise

    logger.info("=" * 50)
    logger.info("✅ 브리핑 완료")
    logger.info("=" * 50)


def main():
    """진입점"""
    asyncio.run(run_pipeline())


if __name__ == "__main__":
    main()
