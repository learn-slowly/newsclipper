"""뉴스 수집 모듈"""

from .google_news import GoogleNewsCollector
from .naver_news import NaverNewsCollector
from .collector import NewsCollector

__all__ = ["GoogleNewsCollector", "NaverNewsCollector", "NewsCollector"]

