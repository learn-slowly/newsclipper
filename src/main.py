"""
뉴스 클리핑 자동화 서비스 메인 모듈

정의당 경남도당 뉴스 클리핑 자동화 서비스
- Google News RSS로 뉴스 수집
- Claude API로 분석 및 요약
- 노션에 자동 발행
"""

import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

import sys
from pathlib import Path

# src 디렉토리를 경로에 추가
src_dir = Path(__file__).parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from utils.config import get_settings
from utils.logger import setup_logger
from collector import NewsCollector
from analyzer import NewsAnalyzer
from publisher import NotionPublisher
from storage import NewsDatabase


def run_news_clipper():
    """뉴스 클리핑 실행"""
    
    # 설정 로드
    settings = get_settings()
    
    # 로거 설정
    setup_logger(
        log_level=settings.log_level,
        log_file=Path("logs") / f"clipper_{datetime.now().strftime('%Y%m%d')}.log"
    )
    
    logger.info("=" * 60)
    logger.info("🚀 뉴스 클리핑 서비스 시작")
    logger.info(f"⏰ 실행 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    
    # 설정 검증
    if not settings.google_api_key:
        logger.error("❌ GOOGLE_API_KEY가 설정되지 않았습니다")
        sys.exit(1)
    
    if not settings.notion_api_key or not settings.notion_database_id:
        logger.error("❌ NOTION_API_KEY 또는 NOTION_DATABASE_ID가 설정되지 않았습니다")
        sys.exit(1)
    
    # 키워드 조합 로드
    keyword_combinations = settings.get_keyword_combinations()
    if not keyword_combinations:
        logger.error("❌ 키워드 조합이 설정되지 않았습니다")
        sys.exit(1)
    
    logger.info(f"📝 키워드 조합 {len(keyword_combinations)}개 로드됨")
    
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
    
    try:
        # 1. 뉴스 수집
        logger.info("📰 Step 1: 뉴스 수집 중...")
        articles = collector.collect_all(
            keyword_combinations=keyword_combinations,
            max_results_per_combo=10,  # API 한도 고려하여 조합당 10개로 제한
            use_naver=bool(settings.naver_client_id),
            when="1d"
        )
        
        if not articles:
            logger.warning("수집된 뉴스가 없습니다")
            return
        
        logger.info(f"📥 수집 완료: {len(articles)}건")
        
        # 2. 중복 제거
        logger.info("🔄 Step 2: 중복 제거 중...")
        articles = database.filter_duplicates(articles)
        
        if not articles:
            logger.info("새로운 뉴스가 없습니다")
            return
        
        logger.info(f"✨ 신규 뉴스: {len(articles)}건")
        
        # 3. AI 분석 및 필터링
        logger.info("🤖 Step 3: AI 분석 중...")
        passed_articles, filtered_articles = analyzer.analyze_and_filter(
            articles=articles,
            summarize=True
        )
        
        if not passed_articles:
            logger.info("관련성 높은 뉴스가 없습니다")
            # 필터링된 기사도 DB에 저장 (중복 방지용)
            database.save_articles(filtered_articles)
            return
        
        # 중요도순 정렬
        passed_articles = analyzer.sort_by_importance(passed_articles)
        
        logger.info(f"✅ 분석 완료: 관련 뉴스 {len(passed_articles)}건")
        
        # 4. 노션 발행
        logger.info("📤 Step 4: 노션 발행 중...")
        results = publisher.publish_articles(
            articles=passed_articles,
            create_summary=True
        )
        
        logger.info(f"📝 발행 완료: 성공 {len(results['success'])}건")
        
        # 5. DB 저장
        logger.info("💾 Step 5: 데이터베이스 저장 중...")
        database.save_articles(passed_articles)
        database.save_articles(filtered_articles)
        
        # 오래된 레코드 정리
        database.cleanup_old_records(days=30)
        
        # 통계 출력
        stats = database.get_stats()
        logger.info(f"📊 DB 통계: 전체 {stats['total']}건, 오늘 {stats['today']}건")
        
    except Exception as e:
        logger.exception(f"❌ 실행 중 오류 발생: {e}")
        raise
    
    logger.info("=" * 60)
    logger.info("✅ 뉴스 클리핑 완료")
    logger.info("=" * 60)


def main():
    """메인 함수"""
    run_news_clipper()


if __name__ == "__main__":
    main()

