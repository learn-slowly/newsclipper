"""Google Gemini API 클라이언트 모듈"""

import json
import time
from pathlib import Path
from typing import Optional

import google.generativeai as genai
from loguru import logger


class GeminiAnalyzer:
    """Google Gemini API를 사용한 뉴스 분석"""
    
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        prompts_dir: Optional[Path] = None
    ):
        """
        Args:
            api_key: Google AI API 키
            model: 사용할 모델명 (gemini-2.0-flash, gemini-1.5-pro 등)
            prompts_dir: 프롬프트 파일 디렉토리
        """
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model)
        self.prompts_dir = prompts_dir or Path(__file__).parent.parent.parent / "config" / "prompts"
        
        # 프롬프트 로드
        self.filter_prompt = self._load_prompt("filter_prompt.txt")
        self.summarize_prompt = self._load_prompt("summarize_prompt.txt")
    
    def _load_prompt(self, filename: str) -> str:
        """프롬프트 파일 로드"""
        prompt_path = self.prompts_dir / filename
        if prompt_path.exists():
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        logger.warning(f"프롬프트 파일 없음: {prompt_path}")
        return ""
    
    def _call_api(self, system_prompt: str, user_message: str, retry_count: int = 3) -> str:
        """Gemini API 호출 (Rate Limit 대응)
        
        Args:
            system_prompt: 시스템 프롬프트
            user_message: 사용자 메시지
            retry_count: 재시도 횟수
            
        Returns:
            응답 텍스트
        """
        # 시스템 프롬프트와 사용자 메시지 결합
        full_prompt = f"{system_prompt}\n\n---\n\n{user_message}"
        
        for attempt in range(retry_count):
            try:
                response = self.model.generate_content(
                    full_prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.3,
                        max_output_tokens=1024,
                    )
                )
                # Rate limit 방지를 위한 딜레이 (분당 15회 = 4초 간격)
                time.sleep(4)
                return response.text
                
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "quota" in error_str.lower():
                    wait_time = 30 * (attempt + 1)  # 30초, 60초, 90초
                    logger.warning(f"Rate limit 도달. {wait_time}초 대기 후 재시도... ({attempt+1}/{retry_count})")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Gemini API 호출 실패: {e}")
                    raise
        
        raise Exception("Gemini API 호출 최대 재시도 횟수 초과")
    
    def _parse_json_response(self, response: str) -> dict:
        """JSON 응답 파싱"""
        try:
            # JSON 블록 추출 시도
            if "```json" in response:
                start = response.find("```json") + 7
                end = response.find("```", start)
                response = response[start:end].strip()
            elif "```" in response:
                start = response.find("```") + 3
                end = response.find("```", start)
                response = response[start:end].strip()
            
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 실패: {e}")
            logger.debug(f"원본 응답: {response}")
            return {}
    
    def filter_news(self, title: str, description: str, category: str = None) -> dict:
        """뉴스 필터링 및 관련성/중요도 평가
        
        Args:
            title: 뉴스 제목
            description: 뉴스 설명/요약
            category: 카테고리 힌트
            
        Returns:
            평가 결과 딕셔너리
        """
        user_message = f"""다음 뉴스를 평가해주세요.

## 뉴스 정보
- 제목: {title}
- 내용: {description or '(내용 없음)'}
- 카테고리 힌트: {category or '(없음)'}

## 요청
위 뉴스의 관련성과 중요도를 평가하고, JSON 형식으로 응답해주세요."""

        try:
            response = self._call_api(
                system_prompt=self.filter_prompt,
                user_message=user_message
            )
            result = self._parse_json_response(response)
            
            # 기본값 설정
            if not result:
                result = {
                    "relevance_score": 0,
                    "importance_score": 1,
                    "category": category or "일반",
                    "is_relevant": False,
                    "reason": "분석 실패"
                }
            
            return result
            
        except Exception as e:
            logger.error(f"뉴스 필터링 실패: {e}")
            return {
                "relevance_score": 0,
                "importance_score": 1,
                "category": category or "일반",
                "is_relevant": False,
                "reason": f"오류: {str(e)}"
            }
    
    def summarize_news(self, title: str, content: str, category: str = None) -> dict:
        """뉴스 요약 생성
        
        Args:
            title: 뉴스 제목
            content: 뉴스 본문
            category: 카테고리
            
        Returns:
            요약 결과 딕셔너리
        """
        user_message = f"""다음 뉴스를 요약해주세요.

## 뉴스 정보
- 제목: {title}
- 카테고리: {category or '일반'}
- 본문:
{content or '(본문 없음 - 제목만으로 요약해주세요)'}

## 요청
위 뉴스를 구조화된 형식으로 요약하고, JSON 형식으로 응답해주세요."""

        try:
            response = self._call_api(
                system_prompt=self.summarize_prompt,
                user_message=user_message
            )
            result = self._parse_json_response(response)
            
            # 기본값 설정
            if not result:
                result = {
                    "one_line_summary": title,
                    "detailed_summary": {
                        "background": "",
                        "current_situation": "",
                        "impact": "",
                        "action_items": []
                    },
                    "keywords": [],
                    "urgency_note": None
                }
            
            return result
            
        except Exception as e:
            logger.error(f"뉴스 요약 실패: {e}")
            return {
                "one_line_summary": title,
                "detailed_summary": {
                    "background": "",
                    "current_situation": "",
                    "impact": "",
                    "action_items": []
                },
                "keywords": [],
                "urgency_note": None
            }
    
    def batch_filter(self, articles: list) -> list:
        """여러 뉴스 일괄 필터링
        
        Args:
            articles: 뉴스 기사 리스트 (dict 또는 NewsArticle)
            
        Returns:
            필터링 결과가 추가된 리스트
        """
        results = []
        
        for i, article in enumerate(articles):
            if hasattr(article, "title"):
                title = article.title
                description = article.description
                category = article.category
            else:
                title = article.get("title", "")
                description = article.get("description", "")
                category = article.get("category")
            
            logger.info(f"필터링 중 ({i+1}/{len(articles)}): {title[:50]}...")
            
            filter_result = self.filter_news(title, description, category)
            
            if hasattr(article, "relevance_score"):
                article.relevance_score = filter_result.get("relevance_score", 0)
                article.importance_score = filter_result.get("importance_score", 1)
                if filter_result.get("category"):
                    article.category = filter_result["category"]
            else:
                article.update(filter_result)
            
            results.append((article, filter_result))
        
        return results

