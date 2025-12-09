"""통합 뉴스 수집 모듈"""

from typing import List, Optional

from loguru import logger

from .models import NewsArticle
from .google_news import GoogleNewsCollector
from .naver_news import NaverNewsCollector
from .local_news import LocalNewsCollector


class NewsCollector:
    """여러 소스에서 뉴스를 통합 수집하는 클래스"""
    
    def __init__(
        self,
        naver_client_id: Optional[str] = None,
        naver_client_secret: Optional[str] = None,
        use_local_rss: bool = True
    ):
        """
        Args:
            naver_client_id: 네이버 API 클라이언트 ID (선택)
            naver_client_secret: 네이버 API 클라이언트 시크릿 (선택)
            use_local_rss: 경남 지역 언론사 RSS 직접 수집 여부
        """
        self.google_collector = GoogleNewsCollector()
        
        # 경남 지역 언론사 RSS 수집기
        self.local_collector = LocalNewsCollector() if use_local_rss else None
        if use_local_rss:
            logger.info("경남 지역 언론사 RSS 수집기 활성화됨")
        
        self.naver_collector = None
        if naver_client_id and naver_client_secret:
            self.naver_collector = NaverNewsCollector(
                client_id=naver_client_id,
                client_secret=naver_client_secret
            )
            logger.info("네이버 뉴스 수집기 활성화됨")
        else:
            logger.info("네이버 API 키가 없어 Google News만 사용합니다")
    
    def collect_all(
        self,
        keyword_combinations: List[dict],
        max_results_per_combo: int = 30,
        use_naver: bool = True,
        when: str = "1d"
    ) -> List[NewsArticle]:
        """모든 소스에서 뉴스 수집
        
        Args:
            keyword_combinations: 키워드 조합 리스트
            max_results_per_combo: 조합당 최대 결과 수
            use_naver: 네이버 API 사용 여부
            when: 기간 필터 (Google News용)
            
        Returns:
            수집된 뉴스 기사 리스트 (중복 제거됨)
        """
        all_articles = []
        seen_urls = set()
        
        # 1. Google News 수집
        logger.info("=== Google News 수집 시작 ===")
        google_articles = self.google_collector.collect_from_combinations(
            keyword_combinations=keyword_combinations,
            max_results_per_combo=max_results_per_combo,
            when=when
        )
        
        for article in google_articles:
            if article.url not in seen_urls:
                all_articles.append(article)
                seen_urls.add(article.url)
        
        # 2. 경남 지역 언론사 RSS 직접 수집 (우선!)
        if self.local_collector:
            # when 파라미터에서 시간 추출 (예: "16h" -> 16, "1d" -> 24)
            hours = 24
            if when.endswith('h'):
                hours = int(when[:-1])
            elif when.endswith('d'):
                hours = int(when[:-1]) * 24
            
            local_articles = self.local_collector.collect_all(hours=hours)
            
            for article in local_articles:
                if article.url not in seen_urls:
                    all_articles.append(article)
                    seen_urls.add(article.url)
        
        # 3. 네이버 뉴스 수집 (선택)
        if use_naver and self.naver_collector:
            logger.info("=== 네이버 뉴스 수집 시작 ===")
            naver_articles = self.naver_collector.collect_from_combinations(
                keyword_combinations=keyword_combinations,
                max_results_per_combo=max_results_per_combo
            )
            
            for article in naver_articles:
                if article.url not in seen_urls:
                    all_articles.append(article)
                    seen_urls.add(article.url)
        
        logger.info(f"=== 총 수집 완료: {len(all_articles)}건 ===")
        return all_articles
    
    def filter_by_priority_media(
        self,
        articles: List[NewsArticle],
        priority_domains: List[str]
    ) -> tuple[List[NewsArticle], List[NewsArticle]]:
        """우선순위 언론사로 분류
        
        Args:
            articles: 뉴스 기사 리스트
            priority_domains: 우선순위 언론사 도메인 리스트
            
        Returns:
            (우선순위 기사 리스트, 나머지 기사 리스트)
        """
        priority_articles = []
        other_articles = []
        
        for article in articles:
            is_priority = any(
                domain in article.url 
                for domain in priority_domains
            )
            
            if is_priority:
                priority_articles.append(article)
            else:
                other_articles.append(article)
        
        logger.info(
            f"언론사 분류: 우선순위 {len(priority_articles)}건, "
            f"기타 {len(other_articles)}건"
        )
        
        return priority_articles, other_articles

