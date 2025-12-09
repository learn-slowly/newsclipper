"""경남 지역 언론사 RSS 직접 수집"""

import re
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import urljoin

import feedparser
import requests
from loguru import logger

from .models import NewsArticle


class LocalNewsCollector:
    """경남 지역 언론사 RSS 수집기"""
    
    # 경남 지역 언론사 RSS 피드
    # 참고: 경남신문, KBS창원, MBC경남은 RSS를 제공하지 않음
    LOCAL_RSS_FEEDS = {
        "경남도민일보": {
            "rss_url": "https://www.idomin.com/rss/allArticle.xml",
            "domain": "idomin.com",
        },
    }
    
    # 관심 키워드 (이 키워드가 포함된 뉴스만 수집)
    INTEREST_KEYWORDS = [
        "노동", "산재", "산업재해", "노동자",
        "환경", "기후", "탄소", "생태",
        "여성", "성평등", "성폭력",
        "동물", "유기동물", "동물복지",
        "선거", "도의회", "시의회", "의원",
        "정의당", "진보", "민주노총", "노조",
        "창원", "김해", "진주", "양산", "거제", "통영", "밀양"
    ]
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; NewsClipper/1.0)"
        })
    
    def _is_interesting(self, title: str, description: str = "") -> bool:
        """관심 키워드가 포함된 뉴스인지 확인"""
        text = f"{title} {description}".lower()
        return any(keyword in text for keyword in self.INTEREST_KEYWORDS)
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """날짜 문자열 파싱"""
        if not date_str:
            return None
        
        # 다양한 날짜 형식 시도
        formats = [
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        return None
    
    def collect_from_feed(
        self,
        media_name: str,
        rss_url: str,
        domain: str,
        hours: int = 24
    ) -> List[NewsArticle]:
        """단일 RSS 피드에서 뉴스 수집"""
        articles = []
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        try:
            response = self.session.get(rss_url, timeout=10)
            response.raise_for_status()
            
            feed = feedparser.parse(response.content)
            
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                link = entry.get("link", "")
                description = entry.get("summary", entry.get("description", "")).strip()
                
                # HTML 태그 제거
                description = re.sub(r'<[^>]+>', '', description)
                
                # 날짜 파싱
                pub_date = self._parse_date(
                    entry.get("published", entry.get("pubDate", ""))
                )
                
                # 시간 필터링 (timezone-naive로 비교)
                if pub_date:
                    pub_date_naive = pub_date.replace(tzinfo=None) if pub_date.tzinfo else pub_date
                    if pub_date_naive < cutoff_time:
                        continue
                
                # 관심 키워드 필터링
                if not self._is_interesting(title, description):
                    continue
                
                article = NewsArticle(
                    title=title,
                    url=link,
                    source="local_rss",
                    description=description[:500] if description else None,
                    published_at=pub_date.replace(tzinfo=None) if pub_date and pub_date.tzinfo else pub_date,
                    media_name=media_name,
                )
                
                articles.append(article)
            
            logger.info(f"[{media_name}] RSS 수집 완료: {len(articles)}건")
            
        except Exception as e:
            logger.warning(f"[{media_name}] RSS 수집 실패: {e}")
        
        return articles
    
    def collect_all(self, hours: int = 24) -> List[NewsArticle]:
        """모든 지역 언론사에서 뉴스 수집
        
        Args:
            hours: 최근 N시간 이내 뉴스만 수집
            
        Returns:
            수집된 뉴스 기사 리스트
        """
        all_articles = []
        
        logger.info(f"=== 경남 지역 언론사 RSS 수집 시작 (최근 {hours}시간) ===")
        
        for media_name, config in self.LOCAL_RSS_FEEDS.items():
            articles = self.collect_from_feed(
                media_name=media_name,
                rss_url=config["rss_url"],
                domain=config["domain"],
                hours=hours
            )
            all_articles.extend(articles)
        
        # URL 기준 중복 제거
        seen_urls = set()
        unique_articles = []
        for article in all_articles:
            if article.url not in seen_urls:
                seen_urls.add(article.url)
                unique_articles.append(article)
        
        logger.info(f"=== 경남 지역 언론사 수집 완료: {len(unique_articles)}건 ===")
        
        return unique_articles

