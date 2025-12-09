#!/usr/bin/env python3
"""
특정 날짜 뉴스 클리핑 스크립트

수집된 뉴스 중 특정 날짜에 발행된 뉴스만 필터링하여 클리핑합니다.
"""

import sys
import argparse
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


def run_clipper_for_date(target_date: date, period: str, settings, publisher, collector, analyzer, database, gemini):
    """특정 날짜에 대해 뉴스 클리핑 실행"""
    
    logger.info(f"\n{'='*60}")
    logger.info(f"📅 {target_date} {period} 뉴스 클리핑 시작")
    logger.info(f"{'='*60}")
    
    # 키워드 조합 로드
    keyword_combinations = settings.get_keyword_combinations()
    config = settings.load_config()
    
    try:
        # 1. 뉴스 수집 (최대 범위로 수집)
        logger.info(f"📰 Step 1: 뉴스 수집 중... (최근 7일)")
        
        articles = collector.collect_all(
            keyword_combinations=keyword_combinations,
            max_results_per_combo=50,  # 더 많이 수집
            use_naver=bool(settings.naver_client_id),
            when="7d"  # 최근 7일
        )
        
        if not articles:
            logger.warning("수집된 뉴스가 없습니다")
            return None
        
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
        
        # 2. 날짜 필터링 (핵심!)
        logger.info(f"📅 Step 2: {target_date} 날짜 필터링 중...")
        
        # 오전/오후에 따른 시간 범위 설정
        if period == "오전":
            # 전날 18시 ~ 당일 10시
            start_time = datetime.combine(target_date - timedelta(days=1), datetime.strptime("18:00", "%H:%M").time())
            end_time = datetime.combine(target_date, datetime.strptime("10:00", "%H:%M").time())
        else:  # 오후
            # 당일 10시 ~ 당일 18시
            start_time = datetime.combine(target_date, datetime.strptime("10:00", "%H:%M").time())
            end_time = datetime.combine(target_date, datetime.strptime("18:00", "%H:%M").time())
        
        date_filtered = []
        for article in articles:
            if article.published_at:
                # published_at이 datetime인 경우
                if isinstance(article.published_at, datetime):
                    pub_date = article.published_at.date()
                else:
                    pub_date = article.published_at
                
                # 해당 날짜의 뉴스만 포함
                if pub_date == target_date:
                    date_filtered.append(article)
            else:
                # 발행일이 없으면 제목/설명에서 날짜 추론 시도 (스킵)
                pass
        
        if not date_filtered:
            # 날짜 필터링이 안 되면 전체 중 일부만 사용
            logger.warning(f"⚠️ {target_date} 날짜의 뉴스를 찾을 수 없습니다. 최근 뉴스로 대체합니다.")
            date_filtered = articles[:30]  # 최근 30개만
        
        articles = date_filtered
        logger.info(f"📅 날짜 필터링 완료: {len(articles)}건")
        
        if not articles:
            logger.warning("필터링 후 뉴스가 없습니다")
            return None
        
        # 3. AI 분석 및 필터링
        logger.info("🤖 Step 3: AI 분석 중...")
        passed_articles, filtered_articles = analyzer.analyze_and_filter(
            articles=articles,
            summarize=True
        )
        
        if not passed_articles:
            logger.info("관련성 높은 뉴스가 없습니다")
            return None
        
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
    parser = argparse.ArgumentParser(description="특정 날짜 뉴스 클리핑")
    parser.add_argument("--date", "-d", type=str, required=True, help="클리핑할 날짜 (YYYY-MM-DD)")
    parser.add_argument("--period", "-p", type=str, choices=["오전", "오후", "both"], default="both", help="기간")
    args = parser.parse_args()
    
    # 날짜 파싱
    try:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    except ValueError:
        print("❌ 날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식을 사용하세요.")
        sys.exit(1)
    
    # 설정 로드
    settings = get_settings()
    
    # 로거 설정
    setup_logger(
        log_level=settings.log_level,
        log_file=Path("logs") / f"clip_{target_date}_{datetime.now().strftime('%H%M%S')}.log"
    )
    
    logger.info("=" * 60)
    logger.info(f"🚀 {target_date} 뉴스 클리핑 시작")
    logger.info("=" * 60)
    
    # 설정 검증
    if not settings.notion_database_id:
        logger.error("❌ NOTION_DATABASE_ID가 설정되지 않았습니다")
        sys.exit(1)
    
    # 컴포넌트 초기화
    collector = NewsCollector(
        naver_client_id=settings.naver_client_id,
        naver_client_secret=settings.naver_client_secret
    )
    
    analyzer = NewsAnalyzer(
        api_key=settings.google_api_key,
        relevance_threshold=settings.relevance_threshold
    )
    
    publisher = NotionPublisher(
        api_key=settings.notion_api_key,
        database_id=settings.notion_database_id
    )
    
    database = NewsDatabase(db_path=settings.db_path)
    
    gemini = GeminiAnalyzer(
        api_key=settings.google_api_key,
        is_paid_plan=True
    )
    
    # 클리핑 실행
    if args.period == "both":
        # 오전
        run_clipper_for_date(
            target_date=target_date,
            period="오전",
            settings=settings,
            publisher=publisher,
            collector=collector,
            analyzer=analyzer,
            database=database,
            gemini=gemini
        )
        
        # 오후
        run_clipper_for_date(
            target_date=target_date,
            period="오후",
            settings=settings,
            publisher=publisher,
            collector=collector,
            analyzer=analyzer,
            database=database,
            gemini=gemini
        )
    else:
        run_clipper_for_date(
            target_date=target_date,
            period=args.period,
            settings=settings,
            publisher=publisher,
            collector=collector,
            analyzer=analyzer,
            database=database,
            gemini=gemini
        )
    
    logger.info("\n" + "=" * 60)
    logger.info(f"✅ {target_date} 뉴스 클리핑 완료!")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

