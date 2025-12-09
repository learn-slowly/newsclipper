"""뉴스 분석 통합 모듈"""

import re
import sys
from pathlib import Path
from typing import List, Tuple, Dict
from difflib import SequenceMatcher

from loguru import logger

# 상위 디렉토리 import를 위한 경로 설정
src_dir = Path(__file__).parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from collector.models import NewsArticle
from analyzer.gemini_client import GeminiAnalyzer


class NewsAnalyzer:
    """뉴스 분석 및 필터링 통합 클래스"""
    
    # 경남 지역 우선 언론사 (가산점 부여)
    PRIORITY_MEDIA_DOMAINS = {
        'idomin.com': 2,        # 경남도민일보: +2점
        'knnews.co.kr': 2,      # 경남신문: +2점
        'changwon.kbs.co.kr': 2, # KBS창원: +2점
        'mbcgn.kr': 2,          # MBC경남: +2점
    }
    
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
    
    def _get_media_bonus(self, url: str) -> int:
        """언론사 가산점 계산"""
        for domain, bonus in self.PRIORITY_MEDIA_DOMAINS.items():
            if domain in url:
                return bonus
        return 0
    
    def _is_priority_media(self, url: str) -> bool:
        """우선 언론사 여부 확인"""
        return any(domain in url for domain in self.PRIORITY_MEDIA_DOMAINS.keys())
    
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
        
        # 경남 지역 언론사 가산점 적용
        priority_count = 0
        for article in passed_articles:
            bonus = self._get_media_bonus(article.url)
            if bonus > 0:
                article.importance_score = min(5, (article.importance_score or 1) + bonus)
                priority_count += 1
        
        if priority_count > 0:
            logger.info(f"🏆 경남 지역 언론사 가산점 적용: {priority_count}건")
        
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
    
    def _normalize_title(self, title: str) -> str:
        """제목 정규화 (비교를 위해)"""
        # 언론사명 제거 (- 뒤의 내용)
        title = re.sub(r'\s*[-–—]\s*[^-–—]+$', '', title)
        # 특수문자 제거
        title = re.sub(r'[^\w\s가-힣]', '', title)
        # 공백 정규화
        title = ' '.join(title.split())
        return title.strip()
    
    def _calculate_similarity(self, title1: str, title2: str) -> float:
        """두 제목의 유사도 계산 (0~1)"""
        norm1 = self._normalize_title(title1)
        norm2 = self._normalize_title(title2)
        return SequenceMatcher(None, norm1, norm2).ratio()
    
    def deduplicate_similar_news(
        self,
        articles: List[NewsArticle],
        similarity_threshold: float = 0.6
    ) -> List[NewsArticle]:
        """유사한 뉴스를 그룹화하여 중복 제거
        
        비슷한 뉴스는 대표 뉴스 하나에 관련 링크로 묶음
        
        Args:
            articles: 뉴스 기사 리스트
            similarity_threshold: 유사도 임계값 (0.6 = 60% 이상 유사하면 같은 뉴스로 판단)
            
        Returns:
            중복 제거된 기사 리스트 (각 기사에 related_urls 속성 추가)
        """
        if not articles:
            return []
        
        # 이미 그룹에 포함된 기사 인덱스
        grouped_indices = set()
        result = []
        
        for i, article in enumerate(articles):
            if i in grouped_indices:
                continue
            
            # 이 기사와 유사한 기사들 찾기
            similar_articles = []
            
            for j, other in enumerate(articles):
                if i == j or j in grouped_indices:
                    continue
                
                similarity = self._calculate_similarity(article.title, other.title)
                
                if similarity >= similarity_threshold:
                    similar_articles.append(other)
                    grouped_indices.add(j)
            
            # 대표 기사 선정 (우선순위: 경남 지역 언론사 > 중요도 > 관련성 > 내용 길이)
            all_similar = [article] + similar_articles
            representative = max(
                all_similar,
                key=lambda x: (
                    self._is_priority_media(x.url),  # 경남 지역 언론사 우선
                    x.importance_score or 0,
                    x.relevance_score or 0,
                    len(x.description or '')
                )
            )
            
            # 관련 URL 목록 생성 (대표 기사 제외)
            related_urls = []
            for similar in all_similar:
                if similar.url != representative.url:
                    related_urls.append({
                        'title': similar.title,
                        'url': similar.url,
                        'media': similar.media_name or '알 수 없음'
                    })
            
            # 대표 기사에 관련 URL 추가
            representative.related_urls = related_urls
            
            result.append(representative)
            grouped_indices.add(i)
        
        logger.info(f"중복 제거: {len(articles)}건 → {len(result)}건 ({len(articles) - len(result)}건 그룹화)")
        
        return result

