"""SQLite 데이터베이스 관리 모듈"""

import sys
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Set

from loguru import logger

# 상위 디렉토리 import를 위한 경로 설정
src_dir = Path(__file__).parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from collector.models import NewsArticle


class NewsDatabase:
    """뉴스 캐시 및 중복 제거용 SQLite 데이터베이스"""
    
    def __init__(self, db_path: Path):
        """
        Args:
            db_path: 데이터베이스 파일 경로
        """
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """데이터베이스 초기화"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 뉴스 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    source TEXT,
                    media_name TEXT,
                    category TEXT,
                    relevance_score INTEGER,
                    importance_score INTEGER,
                    published_at TEXT,
                    collected_at TEXT NOT NULL,
                    processed_at TEXT,
                    notion_page_id TEXT
                )
            """)
            
            # URL 인덱스
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_url ON news(url)
            """)
            
            # 수집일 인덱스
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_collected_at ON news(collected_at)
            """)
            
            conn.commit()
            logger.debug(f"데이터베이스 초기화 완료: {self.db_path}")
    
    def is_duplicate(self, url: str) -> bool:
        """URL 중복 확인
        
        Args:
            url: 뉴스 URL
            
        Returns:
            중복 여부
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM news WHERE url = ?", (url,))
            return cursor.fetchone() is not None
    
    def get_seen_urls(self, days: int = 7) -> Set[str]:
        """최근 N일간 수집된 URL 목록
        
        Args:
            days: 조회할 일수
            
        Returns:
            URL 집합
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT url FROM news WHERE collected_at >= ?",
                (cutoff,)
            )
            return {row[0] for row in cursor.fetchall()}
    
    def filter_duplicates(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        """중복 뉴스 필터링
        
        Args:
            articles: 뉴스 기사 리스트
            
        Returns:
            중복 제거된 기사 리스트
        """
        seen_urls = self.get_seen_urls()
        
        new_articles = []
        for article in articles:
            if article.url not in seen_urls:
                new_articles.append(article)
        
        filtered_count = len(articles) - len(new_articles)
        if filtered_count > 0:
            logger.info(f"중복 뉴스 {filtered_count}건 제거됨")
        
        return new_articles
    
    def save_article(self, article: NewsArticle, notion_page_id: Optional[str] = None):
        """뉴스 기사 저장
        
        Args:
            article: 뉴스 기사
            notion_page_id: 노션 페이지 ID (선택)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO news (
                        url, title, source, media_name, category,
                        relevance_score, importance_score,
                        published_at, collected_at, processed_at, notion_page_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    article.url,
                    article.title,
                    article.source,
                    article.media_name,
                    article.category,
                    article.relevance_score,
                    article.importance_score,
                    article.published_at.isoformat() if article.published_at else None,
                    article.collected_at.isoformat(),
                    datetime.now().isoformat(),
                    notion_page_id
                ))
                conn.commit()
            except Exception as e:
                logger.error(f"기사 저장 실패: {e}")
    
    def save_articles(self, articles: List[NewsArticle]):
        """여러 뉴스 기사 저장
        
        Args:
            articles: 뉴스 기사 리스트
        """
        for article in articles:
            self.save_article(article)
        
        logger.info(f"뉴스 {len(articles)}건 저장 완료")
    
    def get_recent_articles(
        self,
        days: int = 1,
        category: Optional[str] = None,
        min_importance: int = 1
    ) -> List[dict]:
        """최근 뉴스 조회
        
        Args:
            days: 조회할 일수
            category: 카테고리 필터 (선택)
            min_importance: 최소 중요도
            
        Returns:
            뉴스 기사 딕셔너리 리스트
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        query = """
            SELECT url, title, source, media_name, category,
                   relevance_score, importance_score, published_at,
                   collected_at, notion_page_id
            FROM news
            WHERE collected_at >= ?
              AND (importance_score IS NULL OR importance_score >= ?)
        """
        params = [cutoff, min_importance]
        
        if category:
            query += " AND category = ?"
            params.append(category)
        
        query += " ORDER BY importance_score DESC, collected_at DESC"
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, params)
            
            return [dict(row) for row in cursor.fetchall()]
    
    def cleanup_old_records(self, days: int = 30):
        """오래된 레코드 삭제
        
        Args:
            days: 보관 일수
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM news WHERE collected_at < ?",
                (cutoff,)
            )
            deleted = cursor.rowcount
            conn.commit()
        
        if deleted > 0:
            logger.info(f"오래된 레코드 {deleted}건 삭제됨")
    
    def get_stats(self) -> dict:
        """데이터베이스 통계
        
        Returns:
            통계 딕셔너리
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 전체 건수
            cursor.execute("SELECT COUNT(*) FROM news")
            total = cursor.fetchone()[0]
            
            # 오늘 건수
            today = datetime.now().date().isoformat()
            cursor.execute(
                "SELECT COUNT(*) FROM news WHERE collected_at >= ?",
                (today,)
            )
            today_count = cursor.fetchone()[0]
            
            # 카테고리별 건수
            cursor.execute("""
                SELECT category, COUNT(*) as cnt
                FROM news
                GROUP BY category
                ORDER BY cnt DESC
            """)
            by_category = dict(cursor.fetchall())
            
            return {
                "total": total,
                "today": today_count,
                "by_category": by_category
            }

