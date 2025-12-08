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
        model: str = "gemini-2.5-flash-lite",
        is_paid_plan: bool = True
    ):
        """
        Args:
            api_key: Google AI API 키
            relevance_threshold: 관련성 임계값 (이 값 이상만 통과)
            model: 사용할 Gemini 모델 (gemini-1.5-pro 권장)
            is_paid_plan: 유료 플랜 여부
        """
        self.gemini = GeminiAnalyzer(
            api_key=api_key, 
            model=model,
            is_paid_plan=is_paid_plan
        )
        self.relevance_threshold = relevance_threshold
        self.is_paid_plan = is_paid_plan
    
    def analyze_and_filter(
        self,
        articles: List[NewsArticle],
        summarize: bool = True,
        use_batch: bool = True,
        batch_size: int = 5
    ) -> Tuple[List[NewsArticle], List[NewsArticle]]:
        """뉴스 분석 및 필터링
        
        Args:
            articles: 수집된 뉴스 기사 리스트
            summarize: 요약 생성 여부
            use_batch: 배치 분석 사용 여부 (유료 플랜 권장)
            batch_size: 배치 크기
            
        Returns:
            (통과된 기사 리스트, 제외된 기사 리스트)
        """
        passed_articles = []
        filtered_articles = []
        
        logger.info(f"=== 뉴스 분석 시작: {len(articles)}건 ===")
        
        # 배치 분석 (유료 플랜에서 효율적)
        if use_batch and self.is_paid_plan:
            logger.info(f"배치 분석 모드 (배치 크기: {batch_size})")
            filter_results = self.gemini.batch_analyze(articles, batch_size=batch_size)
            
            for i, (article, result) in enumerate(zip(articles, filter_results)):
                if isinstance(result, dict):
                    article.relevance_score = result.get("relevance_score", 0)
                    article.importance_score = result.get("importance_score", 1)
                    if result.get("category"):
                        article.category = result["category"]
                    
                    is_relevant = result.get("is_relevant", False)
                    meets_threshold = article.relevance_score >= self.relevance_threshold
                    
                    if is_relevant and meets_threshold:
                        passed_articles.append(article)
                    else:
                        filtered_articles.append(article)
                else:
                    filtered_articles.append(article)
        else:
            # 개별 분석 (기존 방식)
            for i, article in enumerate(articles):
                logger.info(f"분석 중 ({i+1}/{len(articles)}): {article.title[:50]}...")
                
                filter_result = self.gemini.filter_news(
                    title=article.title,
                    description=article.description,
                    category=article.category
                )
                
                article.relevance_score = filter_result.get("relevance_score", 0)
                article.importance_score = filter_result.get("importance_score", 1)
                
                if filter_result.get("category"):
                    article.category = filter_result["category"]
                
                is_relevant = filter_result.get("is_relevant", False)
                meets_threshold = article.relevance_score >= self.relevance_threshold
                
                if is_relevant and meets_threshold:
                    passed_articles.append(article)
                else:
                    filtered_articles.append(article)
        
        # 통과된 기사만 요약 생성
        if summarize and passed_articles:
            logger.info(f"요약 생성 중: {len(passed_articles)}건...")
            for i, article in enumerate(passed_articles):
                logger.info(f"요약 중 ({i+1}/{len(passed_articles)}): {article.title[:40]}...")
                summary_result = self.gemini.summarize_news(
                    title=article.title,
                    content=article.description or article.content,
                    category=article.category
                )
                
                article.one_line_summary = summary_result.get("one_line_summary")
                article.detailed_summary = summary_result.get("detailed_summary")
                article.keywords = summary_result.get("keywords", [])
        
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

