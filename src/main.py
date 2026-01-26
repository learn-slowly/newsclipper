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
    
    # 월별 DB 사용 여부 확인
    use_monthly = settings.use_monthly_db()
    parent_page_id = settings.get_parent_page_id()
    
    if use_monthly and not parent_page_id:
        logger.error("❌ 월별 DB를 사용하려면 NOTION_PARENT_PAGE_ID가 필요합니다")
        sys.exit(1)
    
    if not use_monthly and (not settings.notion_api_key or not settings.notion_database_id):
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
    
    # NotionPublisher 초기화
    # [Mod] parent_page_id가 있으면 무조건 월별 DB 모드(자동 타겟팅) 활성화
    # database_id가 있어도 무시하여 12월 DB 등 과거 DB로 들어가는 것을 방지
    if parent_page_id:
        logger.info(f"📅 월별 DB 모드 활성화 (상위 페이지: {parent_page_id[:8]}...) - 자동 타겟팅")
        publisher = NotionPublisher(
            api_key=settings.notion_api_key,
            parent_page_id=parent_page_id
            # database_id는 전달하지 않음
        )
    elif settings.notion_database_id:
        logger.info("📅 단일 DB 모드 활성화 (고정 DB 사용)")
        publisher = NotionPublisher(
            api_key=settings.notion_api_key,
            database_id=settings.notion_database_id
        )
    else:
        logger.error("❌ DB 설정 오류: NOTION_PARENT_PAGE_ID 또는 NOTION_DATABASE_ID 중 하나는 필수입니다.")
        sys.exit(1)
    
    database = NewsDatabase(db_path=settings.db_path)
    
    try:
        # 1. 뉴스 수집
        # 시간대에 따른 수집 기간 설정
        config = settings.load_config()
        schedule_config = config.get("schedule", {})
        current_hour = datetime.now().hour
        
        # 오전 10시 실행: 16시간, 오후 18시 실행: 8시간
        if current_hour < 14:  # 오전~오후 2시 이전
            hours = schedule_config.get("morning_hours", 16)
        else:  # 오후 2시 이후
            hours = schedule_config.get("evening_hours", 8)
        
        when = f"{hours}h"
        logger.info(f"📰 Step 1: 뉴스 수집 중... (최근 {hours}시간)")
        
        articles = collector.collect_all(
            keyword_combinations=keyword_combinations,
            max_results_per_combo=20,  # 유료 플랜: 조합당 20개
            use_naver=bool(settings.naver_client_id),
            when=when
        )
        
        if not articles:
            logger.warning("수집된 뉴스가 없습니다")
            return
        
        logger.info(f"📥 수집 완료: {len(articles)}건")
        
        # 1.5. 발행 시간 필터링 (지정된 시간 내 뉴스만)
        from datetime import timedelta
        cutoff_time = datetime.now() - timedelta(hours=hours)
        original_count = len(articles)
        
        filtered_by_time = []
        no_date_count = 0
        for article in articles:
            if article.published_at:
                # timezone-aware datetime 처리
                pub_time = article.published_at
                if pub_time.tzinfo is not None:
                    # timezone 정보 제거하여 비교
                    pub_time = pub_time.replace(tzinfo=None)
                
                if pub_time >= cutoff_time:
                    filtered_by_time.append(article)
            else:
                # 발행일이 없는 경우 제외 (오래된 뉴스일 가능성)
                no_date_count += 1
        
        articles = filtered_by_time
        logger.info(f"⏰ 시간 필터링: {original_count}건 → {len(articles)}건 (최근 {hours}시간, 날짜없음 {no_date_count}건 제외)")
        
        if not articles:
            logger.warning(f"최근 {hours}시간 내 뉴스가 없습니다")
            return
        
        # 1.6. 언론사 필터링
        logger.info("📰 Step 1.6: 언론사 필터링 중...")
        news_sources = config.get("news_sources", {})
        allowed_domains = []
        
        # priority_media와 national_media에서 도메인 추출
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
        
        # 3.5. 유사 뉴스 그룹화
        logger.info("🔗 Step 3.5: 유사 뉴스 그룹화 중...")
        passed_articles = analyzer.deduplicate_similar_news(
            articles=passed_articles,
            similarity_threshold=0.5  # 50% 이상 유사하면 같은 뉴스로 판단
        )
        logger.info(f"📦 그룹화 완료: {len(passed_articles)}건")
        
        # 3.6. 인사이트 생성
        logger.info("💡 Step 3.6: 인사이트 생성 중...")
        from analyzer.gemini_client import GeminiAnalyzer
        gemini = GeminiAnalyzer(
            api_key=settings.google_api_key,
            is_paid_plan=True
        )
        insight = gemini.generate_daily_insight(passed_articles)
        logger.info(f"💡 인사이트 생성 완료: {insight.get('headline', '')[:50]}...")
        
        # 4. 노션 발행
        logger.info("📤 Step 4: 노션 발행 중...")
        
        # 오전/오후 구분 (14시 기준)
        period = "오전" if current_hour < 14 else "오후"
        
        results = publisher.publish_articles(
            articles=passed_articles,
            create_summary=True,
            insight=insight,
            period=period
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

