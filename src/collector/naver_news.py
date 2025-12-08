"""네이버 뉴스 API 수집 모듈"""

from datetime import datetime
from typing import List, Optional

import requests
from loguru import logger

from .models import NewsArticle


class NaverNewsCollector:
    """네이버 뉴스 검색 API를 통한 뉴스 수집"""
    
    BASE_URL = "https://openapi.naver.com/v1/search/news.json"
    
    def __init__(self, client_id: str, client_secret: str):
        """
        Args:
            client_id: 네이버 API 클라이언트 ID
            client_secret: 네이버 API 클라이언트 시크릿
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = requests.Session()
        self.session.headers.update({
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret
        })
    
    def build_query(self, issues: List[str], regions: List[str]) -> str:
        """키워드 조합으로 검색 쿼리 생성
        
        네이버 API는 간단한 쿼리만 지원하므로 주요 키워드만 사용
        
        Args:
            issues: 이슈 키워드 리스트
            regions: 지역 키워드 리스트
            
        Returns:
            검색 쿼리 문자열
        """
        # 네이버는 복잡한 OR 연산을 잘 지원하지 않으므로
        # 가장 중요한 키워드 조합으로 검색
        keywords = []
        
        if issues:
            keywords.append(issues[0])  # 첫 번째 이슈 키워드
        if regions:
            keywords.append(regions[0])  # 첫 번째 지역 키워드
        
        return " ".join(keywords)
    
    def parse_published_date(self, date_str: str) -> Optional[datetime]:
        """발행일 파싱
        
        네이버 API 날짜 형식: "Mon, 02 Dec 2024 10:30:00 +0900"
        """
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str)
        except Exception:
            return None
    
    def clean_html(self, text: str) -> str:
        """HTML 태그 제거"""
        import re
        clean = re.sub(r'<[^>]+>', '', text)
        clean = clean.replace("&quot;", '"')
        clean = clean.replace("&amp;", '&')
        clean = clean.replace("&lt;", '<')
        clean = clean.replace("&gt;", '>')
        clean = clean.replace("&nbsp;", ' ')
        return clean.strip()
    
    def collect(
        self,
        issues: List[str],
        regions: List[str],
        max_results: int = 50,
        sort: str = "date"
    ) -> List[NewsArticle]:
        """뉴스 수집
        
        Args:
            issues: 이슈 키워드 리스트
            regions: 지역 키워드 리스트
            max_results: 최대 결과 수 (최대 100)
            sort: 정렬 방식 (date: 최신순, sim: 정확도순)
            
        Returns:
            수집된 뉴스 기사 리스트
        """
        query = self.build_query(issues, regions)
        if not query:
            logger.warning("검색 쿼리가 비어있습니다")
            return []
        
        logger.info(f"네이버 뉴스 수집 시작: {query}")
        
        params = {
            "query": query,
            "display": min(max_results, 100),
            "start": 1,
            "sort": sort
        }
        
        try:
            response = self.session.get(self.BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()
            
            articles = []
            for item in data.get("items", []):
                article = NewsArticle(
                    title=self.clean_html(item.get("title", "")),
                    url=item.get("originallink") or item.get("link"),
                    source="naver",
                    description=self.clean_html(item.get("description", "")),
                    published_at=self.parse_published_date(item.get("pubDate", "")),
                    search_query=query
                )
                articles.append(article)
            
            logger.info(f"네이버 뉴스 수집 완료: {len(articles)}건")
            return articles
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"네이버 API HTTP 오류: {e}")
            return []
        except Exception as e:
            logger.error(f"네이버 뉴스 수집 실패: {e}")
            return []
    
    def collect_from_combinations(
        self,
        keyword_combinations: List[dict],
        max_results_per_combo: int = 30
    ) -> List[NewsArticle]:
        """여러 키워드 조합으로 뉴스 수집
        
        Args:
            keyword_combinations: 키워드 조합 리스트
            max_results_per_combo: 조합당 최대 결과 수
            
        Returns:
            수집된 뉴스 기사 리스트 (중복 제거됨)
        """
        all_articles = []
        seen_urls = set()
        
        for combo in keyword_combinations:
            name = combo.get("name", "unknown")
            issues = combo.get("issues", [])
            regions = combo.get("regions", [])
            category = combo.get("category", "일반")
            
            logger.info(f"키워드 조합 '{name}' 수집 중 (네이버)...")
            
            articles = self.collect(
                issues=issues,
                regions=regions,
                max_results=max_results_per_combo
            )
            
            # 중복 제거 및 카테고리 설정
            for article in articles:
                if article.url not in seen_urls:
                    article.category = category
                    all_articles.append(article)
                    seen_urls.add(article.url)
        
        logger.info(f"네이버 총 수집 완료: {len(all_articles)}건 (중복 제거됨)")
        return all_articles

