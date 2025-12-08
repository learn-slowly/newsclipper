"""뉴스 분석 통합 모듈"""

import sys
from pathlib import Path
from typing import List, Tuple

from loguru import logger

# 상위 디렉토리 import를 위한 경로 설정
src_dir = Path(__file__).parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from collector.models import NewsArticle
from analyzer.gemini_client import GeminiAnalyzer


class NewsAnalyzer:
    """뉴스 분석 및 필터링 통합 클래스"""
    
    def __init__(
        self,
        api_key: str,
        relevance_threshold: int = 60,
        model: str = "gemini-2.0-flash"
    ):
        """
        Args:
            api_key: Google AI API 키
            relevance_threshold: 관련성 임계값 (이 값 이상만 통과)
            model: 사용할 Gemini 모델
        """
        self.gemini = GeminiAnalyzer(api_key=api_key, model=model)
        self.relevance_threshold = relevance_threshold
    
    def analyze_and_filter(
        self,
        articles: List[NewsArticle],
        summarize: bool = True
    ) -> Tuple[List[NewsArticle], List[NewsArticle]]:
        """뉴스 분석 및 필터링
        
        Args:
            articles: 수집된 뉴스 기사 리스트
            summarize: 요약 생성 여부
            
        Returns:
            (통과된 기사 리스트, 제외된 기사 리스트)
        """
        passed_articles = []
        filtered_articles = []
        
        logger.info(f"=== 뉴스 분석 시작: {len(articles)}건 ===")
        
        for i, article in enumerate(articles):
            logger.info(f"분석 중 ({i+1}/{len(articles)}): {article.title[:50]}...")
            
            # 1. 필터링 및 평가
            filter_result = self.gemini.filter_news(
                title=article.title,
                description=article.description,
                category=article.category
            )
            
            # 결과 적용
            article.relevance_score = filter_result.get("relevance_score", 0)
            article.importance_score = filter_result.get("importance_score", 1)
            
            if filter_result.get("category"):
                article.category = filter_result["category"]
            
            # 2. 임계값 확인
            is_relevant = filter_result.get("is_relevant", False)
            meets_threshold = article.relevance_score >= self.relevance_threshold
            
            if is_relevant and meets_threshold:
                # 3. 요약 생성 (통과된 기사만)
                if summarize:
                    summary_result = self.gemini.summarize_news(
                        title=article.title,
                        content=article.description or article.content,
                        category=article.category
                    )
                    
                    article.one_line_summary = summary_result.get("one_line_summary")
                    article.detailed_summary = summary_result.get("detailed_summary")
                    article.keywords = summary_result.get("keywords", [])
                
                passed_articles.append(article)
                logger.debug(
                    f"✅ 통과: {article.title[:30]}... "
                    f"(관련성: {article.relevance_score}, 중요도: {article.importance_score})"
                )
            else:
                filtered_articles.append(article)
                logger.debug(
                    f"❌ 제외: {article.title[:30]}... "
                    f"(관련성: {article.relevance_score}, 이유: {filter_result.get('reason', 'N/A')})"
                )
        
        logger.info(
            f"=== 분석 완료: 통과 {len(passed_articles)}건, "
            f"제외 {len(filtered_articles)}건 ==="
        )
        
        return passed_articles, filtered_articles
    
    def sort_by_importance(
        self,
        articles: List[NewsArticle],
        reverse: bool = True
    ) -> List[NewsArticle]:
        """중요도순 정렬
        
        Args:
            articles: 뉴스 기사 리스트
            reverse: 내림차순 여부 (True면 높은 순)
            
        Returns:
            정렬된 기사 리스트
        """
        return sorted(
            articles,
            key=lambda x: (x.importance_score or 0, x.relevance_score or 0),
            reverse=reverse
        )
    
    def group_by_category(
        self,
        articles: List[NewsArticle]
    ) -> dict:
        """카테고리별 그룹화
        
        Args:
            articles: 뉴스 기사 리스트
            
        Returns:
            카테고리별 기사 딕셔너리
        """
        grouped = {}
        
        for article in articles:
            category = article.category or "일반"
            if category not in grouped:
                grouped[category] = []
            grouped[category].append(article)
        
        return grouped
    
    def group_by_importance(
        self,
        articles: List[NewsArticle]
    ) -> dict:
        """중요도별 그룹화
        
        Args:
            articles: 뉴스 기사 리스트
            
        Returns:
            중요도별 기사 딕셔너리
        """
        grouped = {
            "urgent": [],      # 5점
            "important": [],   # 4점
            "normal": [],      # 3점
            "low": []          # 1-2점
        }
        
        for article in articles:
            score = article.importance_score or 1
            
            if score >= 5:
                grouped["urgent"].append(article)
            elif score >= 4:
                grouped["important"].append(article)
            elif score >= 3:
                grouped["normal"].append(article)
            else:
                grouped["low"].append(article)
        
        return grouped

