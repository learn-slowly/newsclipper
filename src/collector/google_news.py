"""Google News RSS 수집 모듈"""

import urllib.parse
from datetime import datetime
from typing import List, Optional
import ssl
import certifi

import feedparser
import requests
from loguru import logger

from .models import NewsArticle


class GoogleNewsCollector:
    """Google News RSS를 통한 뉴스 수집"""
    
    BASE_URL = "https://news.google.com/rss/search"
    
    def __init__(self, language: str = "ko", country: str = "KR"):
        """
        Args:
            language: 언어 코드 (ko, en, ...)
            country: 국가 코드 (KR, US, ...)
        """
        self.language = language
        self.country = country
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        
        # SSL 컨텍스트 설정 (인증서 검증 문제 해결)
        if hasattr(ssl, '_create_unverified_context'):
            ssl._create_default_https_context = ssl._create_unverified_context
    
    def build_query(self, issues: List[str], regions: List[str]) -> str:
        """키워드 조합으로 검색 쿼리 생성
        
        Args:
            issues: 이슈 키워드 리스트
            regions: 지역 키워드 리스트
            
        Returns:
            조합된 검색 쿼리 문자열
        """
        if not issues and not regions:
            return ""
        
        issues_query = " OR ".join(f'"{issue}"' if " " in issue else issue for issue in issues)
        regions_query = " OR ".join(f'"{region}"' if " " in region else region for region in regions)
        
        if issues_query and regions_query:
            return f"({issues_query}) ({regions_query})"
        elif issues_query:
            return issues_query
        else:
            return regions_query
    
    def build_rss_url(self, query: str, when: str = "1d") -> str:
        """RSS 피드 URL 생성
        
        Args:
            query: 검색 쿼리
            when: 기간 (1h, 1d, 7d, 1m, 1y)
            
        Returns:
            RSS 피드 URL
        """
        params = {
            "q": query,
            "hl": self.language,
            "gl": self.country,
            "ceid": f"{self.country}:{self.language}"
        }
        
        # 기간 필터 추가
        if when:
            params["q"] = f"{query} when:{when}"
        
        encoded_params = urllib.parse.urlencode(params)
        return f"{self.BASE_URL}?{encoded_params}"
    
    def parse_published_date(self, entry) -> Optional[datetime]:
        """발행일 파싱"""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                return datetime(*entry.published_parsed[:6])
            except Exception:
                pass
        return None
    
    def extract_media_name(self, entry) -> Optional[str]:
        """언론사명 추출"""
        # Google News RSS에서 source 태그 확인
        if hasattr(entry, "source") and hasattr(entry.source, "title"):
            return entry.source.title
        
        # 제목에서 언론사명 추출 시도 (보통 " - 언론사" 형식)
        if " - " in entry.title:
            parts = entry.title.rsplit(" - ", 1)
            if len(parts) == 2:
                return parts[1].strip()
        
        return None
    
    def clean_title(self, title: str) -> str:
        """제목에서 언론사명 제거"""
        if " - " in title:
            return title.rsplit(" - ", 1)[0].strip()
        return title
    
    def collect(
        self,
        issues: List[str],
        regions: List[str],
        max_results: int = 50,
        when: str = "1d"
    ) -> List[NewsArticle]:
        """뉴스 수집
        
        Args:
            issues: 이슈 키워드 리스트
            regions: 지역 키워드 리스트
            max_results: 최대 결과 수
            when: 기간 필터
            
        Returns:
            수집된 뉴스 기사 리스트
        """
        query = self.build_query(issues, regions)
        if not query:
            logger.warning("검색 쿼리가 비어있습니다")
            return []
        
        url = self.build_rss_url(query, when)
        logger.info(f"Google News 수집 시작: {query}")
        logger.debug(f"RSS URL: {url}")
        
        try:
            # requests로 먼저 가져온 후 feedparser로 파싱 (SSL 문제 우회)
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            
            if feed.bozo and not feed.entries:
                logger.warning(f"RSS 파싱 경고: {feed.bozo_exception}")
            
            articles = []
            for entry in feed.entries[:max_results]:
                article = NewsArticle(
                    title=self.clean_title(entry.title),
                    url=entry.link,
                    source="google_news",
                    description=getattr(entry, "summary", None),
                    published_at=self.parse_published_date(entry),
                    media_name=self.extract_media_name(entry),
                    search_query=query
                )
                articles.append(article)
            
            logger.info(f"Google News 수집 완료: {len(articles)}건")
            return articles
            
        except Exception as e:
            logger.error(f"Google News 수집 실패: {e}")
            return []
    
    def collect_from_combinations(
        self,
        keyword_combinations: List[dict],
        max_results_per_combo: int = 30,
        when: str = "1d"
    ) -> List[NewsArticle]:
        """여러 키워드 조합으로 뉴스 수집
        
        Args:
            keyword_combinations: 키워드 조합 리스트
            max_results_per_combo: 조합당 최대 결과 수
            when: 기간 필터
            
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
            
            logger.info(f"키워드 조합 '{name}' 수집 중...")
            
            articles = self.collect(
                issues=issues,
                regions=regions,
                max_results=max_results_per_combo,
                when=when
            )
            
            # 중복 제거 및 카테고리 설정
            for article in articles:
                if article.url not in seen_urls:
                    article.category = category
                    all_articles.append(article)
                    seen_urls.add(article.url)
        
        logger.info(f"총 수집 완료: {len(all_articles)}건 (중복 제거됨)")
        return all_articles

