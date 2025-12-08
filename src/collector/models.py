"""뉴스 데이터 모델"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


@dataclass
class NewsArticle:
    """뉴스 기사 데이터 모델"""
    
    # 필수 필드
    title: str
    url: str
    source: str  # 뉴스 소스 (google_news, naver)
    
    # 선택 필드
    description: Optional[str] = None
    content: Optional[str] = None
    published_at: Optional[datetime] = None
    media_name: Optional[str] = None
    
    # 분석 결과 필드
    relevance_score: Optional[int] = None
    importance_score: Optional[int] = None
    category: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    
    # 요약 필드
    one_line_summary: Optional[str] = None
    detailed_summary: Optional[dict] = None
    
    # 메타 필드
    collected_at: datetime = field(default_factory=datetime.now)
    search_query: Optional[str] = None
    
    def __hash__(self):
        return hash(self.url)
    
    def __eq__(self, other):
        if isinstance(other, NewsArticle):
            return self.url == other.url
        return False
    
    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "description": self.description,
            "content": self.content,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "media_name": self.media_name,
            "relevance_score": self.relevance_score,
            "importance_score": self.importance_score,
            "category": self.category,
            "keywords": self.keywords,
            "one_line_summary": self.one_line_summary,
            "detailed_summary": self.detailed_summary,
            "collected_at": self.collected_at.isoformat(),
            "search_query": self.search_query
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "NewsArticle":
        """딕셔너리에서 생성"""
        if data.get("published_at"):
            data["published_at"] = datetime.fromisoformat(data["published_at"])
        if data.get("collected_at"):
            data["collected_at"] = datetime.fromisoformat(data["collected_at"])
        return cls(**data)

