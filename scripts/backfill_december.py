#!/usr/bin/env python3
"""
2025년 12월 뉴스 백필 스크립트

12월 1일부터 7일까지 뉴스를 클리핑하고 보고서를 생성합니다.
"""

import sys
from pathlib import Path
from datetime import datetime, date, timedelta

# 프로젝트 루트를 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# .env 파일 로드
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from loguru import logger
from utils.config import get_settings
from utils.logger import setup_logger
from collector import NewsCollector
from analyzer import NewsAnalyzer
from publisher import NotionPublisher
from storage import NewsDatabase
from analyzer.gemini_client import GeminiAnalyzer


def run_clipper_for_date(target_date: date, period: str, hours: int, settings, publisher, collector, analyzer, database, gemini):
    """특정 날짜와 기간에 대해 뉴스 클리핑 실행"""
    
    logger.info(f"\n{'='*60}")
    logger.info(f"📅 {target_date} {period} 뉴스 클리핑 시작")
    logger.info(f"{'='*60}")
    
    # 키워드 조합 로드
    keyword_combinations = settings.get_keyword_combinations()
    config = settings.load_config()
    
    try:
        # 1. 뉴스 수집
        when = f"{hours}h"
        logger.info(f"📰 Step 1: 뉴스 수집 중... (최근 {hours}시간)")
        
        articles = collector.collect_all(
            keyword_combinations=keyword_combinations,
            max_results_per_combo=20,
            use_naver=bool(settings.naver_client_id),
            when=when
        )
        
        if not articles:
            logger.warning("수집된 뉴스가 없습니다")
            return
        
        logger.info(f"📥 수집 완료: {len(articles)}건")
        
        # 1.5. 언론사 필터링
        logger.info("📰 Step 1.5: 언론사 필터링 중...")
        news_sources = config.get("news_sources", {})
        allowed_domains = []
        
        for media in news_sources.get("priority_media", []):
            allowed_domains.append(media.get("domain", ""))
        for media in news_sources.get("national_media", []):
            allowed_domains.append(media.get("domain", ""))
        
        if allowed_domains:
            original_count = len(articles)
            articles = [
                article for article in articles
                if any(domain in (article.url or "") for domain in allowed_domains)
            ]
            logger.info(f"🏢 언론사 필터링: {original_count}건 → {len(articles)}건")
        
        if not articles:
            logger.warning("지정된 언론사의 뉴스가 없습니다")
            return
        
        # 2. 중복 제거 (백필이므로 스킵하거나 느슨하게)
        logger.info("🔄 Step 2: 중복 확인 중...")
        # articles = database.filter_duplicates(articles)  # 백필 시 스킵
        logger.info(f"✨ 처리할 뉴스: {len(articles)}건")
        
        # 3. AI 분석 및 필터링
        logger.info("🤖 Step 3: AI 분석 중...")
        passed_articles, filtered_articles = analyzer.analyze_and_filter(
            articles=articles,
            summarize=True
        )
        
        if not passed_articles:
            logger.info("관련성 높은 뉴스가 없습니다")
            return
        
        # 중요도순 정렬
        passed_articles = analyzer.sort_by_importance(passed_articles)
        logger.info(f"✅ 분석 완료: 관련 뉴스 {len(passed_articles)}건")
        
        # 3.5. 인사이트 생성
        logger.info("💡 Step 3.5: 인사이트 생성 중...")
        insight = gemini.generate_daily_insight(passed_articles)
        logger.info(f"💡 인사이트 생성 완료: {insight.get('headline', '')[:50]}...")
        
        # 4. 노션 발행
        logger.info("📤 Step 4: 노션 발행 중...")
        results = publisher.publish_articles(
            articles=passed_articles,
            create_summary=True,
            insight=insight,
            period=period,
            target_date=target_date
        )
        
        logger.info(f"📝 발행 완료: 성공 {len(results['success'])}건")
        
        # 5. DB 저장
        logger.info("💾 Step 5: 데이터베이스 저장 중...")
        database.save_articles(passed_articles)
        
        return results
        
    except Exception as e:
        logger.exception(f"❌ {target_date} {period} 클리핑 중 오류: {e}")
        return None


def main():
    """메인 함수"""
    
    # 설정 로드
    settings = get_settings()
    
    # 로거 설정
    setup_logger(
        log_level=settings.log_level,
        log_file=Path("logs") / f"backfill_december_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    
    logger.info("=" * 60)
    logger.info("🚀 2025년 12월 뉴스 백필 시작")
    logger.info("=" * 60)
    
    # 설정 검증
    if not settings.notion_database_id:
        logger.error("❌ NOTION_DATABASE_ID가 설정되지 않았습니다")
        sys.exit(1)
    
    logger.info(f"📁 데이터베이스 ID: {settings.notion_database_id[:8]}...")
    
    # 컴포넌트 초기화
    collector = NewsCollector(
        naver_client_id=settings.naver_client_id,
        naver_client_secret=settings.naver_client_secret
    )
    
    analyzer = NewsAnalyzer(
        api_key=settings.google_api_key,
        relevance_threshold=settings.relevance_threshold
    )
    
    # 기존 DB 사용 (월별 DB 생성 문제로 인해 임시로 기존 DB 사용)
    # 월별 DB 기능은 노션에서 수동으로 DB 생성 후 사용 권장
    publisher = NotionPublisher(
        api_key=settings.notion_api_key,
        database_id=settings.notion_database_id
    )
    
    database = NewsDatabase(db_path=settings.db_path)
    
    gemini = GeminiAnalyzer(
        api_key=settings.google_api_key,
        is_paid_plan=True
    )
    
    # 12월 1일부터 7일까지 클리핑
    start_date = date(2025, 12, 1)
    end_date = date(2025, 12, 7)
    
    current_date = start_date
    while current_date <= end_date:
        # 오전 클리핑 (16시간)
        run_clipper_for_date(
            target_date=current_date,
            period="오전",
            hours=16,
            settings=settings,
            publisher=publisher,
            collector=collector,
            analyzer=analyzer,
            database=database,
            gemini=gemini
        )
        
        # 오후 클리핑 (8시간)
        run_clipper_for_date(
            target_date=current_date,
            period="오후",
            hours=8,
            settings=settings,
            publisher=publisher,
            collector=collector,
            analyzer=analyzer,
            database=database,
            gemini=gemini
        )
        
        current_date += timedelta(days=1)
        logger.info(f"\n⏳ 다음 날짜로 이동: {current_date}")
    
    logger.info("\n" + "=" * 60)
    logger.info("✅ 2025년 12월 뉴스 백필 완료!")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

