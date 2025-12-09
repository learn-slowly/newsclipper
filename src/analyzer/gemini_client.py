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
        model: str = "gemini-2.5-flash-lite",  # 빠르고 저렴한 모델
        prompts_dir: Optional[Path] = None,
        is_paid_plan: bool = True  # 유료 플랜 여부
    ):
        """
        Args:
            api_key: Google AI API 키
            model: 사용할 모델명 (gemini-1.5-pro 권장, gemini-2.0-flash도 가능)
            prompts_dir: 프롬프트 파일 디렉토리
            is_paid_plan: 유료 플랜 여부 (True면 딜레이 없음)
        """
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model)
        self.model_name = model
        self.is_paid_plan = is_paid_plan
        self.prompts_dir = prompts_dir or Path(__file__).parent.parent.parent / "config" / "prompts"
        
        # 프롬프트 로드
        self.filter_prompt = self._load_prompt("filter_prompt.txt")
        self.summarize_prompt = self._load_prompt("summarize_prompt.txt")
        
        logger.info(f"Gemini 모델: {model}, 유료플랜: {is_paid_plan}")
    
    def _load_prompt(self, filename: str) -> str:
        """프롬프트 파일 로드"""
        prompt_path = self.prompts_dir / filename
        if prompt_path.exists():
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        logger.warning(f"프롬프트 파일 없음: {prompt_path}")
        return ""
    
    def _call_api(self, system_prompt: str, user_message: str, retry_count: int = 3) -> str:
        """Gemini API 호출
        
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
                        temperature=0.2,  # 더 일관된 결과를 위해 낮춤
                        max_output_tokens=2048,  # 더 상세한 분석을 위해 증가
                    )
                )
                
                # 무료 플랜만 딜레이 적용
                if not self.is_paid_plan:
                    time.sleep(4)
                    
                return response.text
                
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "quota" in error_str.lower():
                    wait_time = 10 * (attempt + 1)
                    logger.warning(f"Rate limit 도달. {wait_time}초 대기 후 재시도... ({attempt+1}/{retry_count})")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Gemini API 호출 실패: {e}")
                    raise
        
        raise Exception("Gemini API 호출 최대 재시도 횟수 초과")
    
    def batch_analyze(self, articles: list, batch_size: int = 5) -> list:
        """여러 뉴스를 배치로 분석 (효율성 + 품질 향상)
        
        Args:
            articles: 뉴스 기사 리스트
            batch_size: 한 번에 분석할 기사 수
            
        Returns:
            분석 결과 리스트
        """
        results = []
        
        for i in range(0, len(articles), batch_size):
            batch = articles[i:i+batch_size]
            
            # 배치 뉴스 목록 생성
            news_list = "\n\n".join([
                f"[뉴스 {j+1}]\n제목: {a.title if hasattr(a, 'title') else a.get('title', '')}\n"
                f"내용: {(a.description if hasattr(a, 'description') else a.get('description', '')) or '(없음)'}\n"
                f"카테고리 힌트: {(a.category if hasattr(a, 'category') else a.get('category', '')) or '일반'}"
                for j, a in enumerate(batch)
            ])
            
            batch_prompt = f"""다음 {len(batch)}개의 뉴스를 각각 평가해주세요.

{news_list}

## 요청
각 뉴스에 대해 JSON 배열 형식으로 응답해주세요:
[
  {{"news_index": 1, "relevance_score": 0-100, "importance_score": 1-5, "category": "카테고리", "is_relevant": true/false, "reason": "이유"}},
  ...
]"""

            try:
                response = self._call_api(
                    system_prompt=self.filter_prompt,
                    user_message=batch_prompt
                )
                batch_results = self._parse_json_response(response)
                
                if isinstance(batch_results, list):
                    results.extend(batch_results)
                else:
                    # 개별 분석으로 폴백
                    for article in batch:
                        result = self.filter_news(
                            title=article.title if hasattr(article, 'title') else article.get('title', ''),
                            description=article.description if hasattr(article, 'description') else article.get('description', ''),
                            category=article.category if hasattr(article, 'category') else article.get('category')
                        )
                        results.append(result)
                        
            except Exception as e:
                logger.error(f"배치 분석 실패: {e}")
                # 개별 분석으로 폴백
                for article in batch:
                    result = self.filter_news(
                        title=article.title if hasattr(article, 'title') else article.get('title', ''),
                        description=article.description if hasattr(article, 'description') else article.get('description', ''),
                        category=article.category if hasattr(article, 'category') else article.get('category')
                    )
                    results.append(result)
            
            logger.info(f"배치 분석 완료: {i+len(batch)}/{len(articles)}")
        
        return results
    
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
            
            # { 로 시작하는 JSON 찾기
            if "{" in response:
                start = response.find("{")
                end = response.rfind("}") + 1
                if end > start:
                    response = response[start:end]
            
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 실패: {e}")
            logger.debug(f"원본 응답: {response[:500]}...")
            
            # 마크다운 응답에서 정보 추출 시도
            result = self._extract_insight_from_text(response)
            if result:
                return result
            return {}
    
    def _extract_insight_from_text(self, text: str) -> dict:
        """마크다운 텍스트에서 인사이트 추출"""
        try:
            result = {
                "headline": "",
                "key_trends": [],
                "political_implications": "",
                "action_suggestions": [],
                "risk_alerts": [],
                "opportunities": ""
            }
            
            lines = text.split("\n")
            current_section = None
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # 섹션 감지
                if "핵심 메시지" in line or "headline" in line.lower():
                    current_section = "headline"
                elif "트렌드" in line or "trends" in line.lower():
                    current_section = "trends"
                elif "정치적 함의" in line or "implications" in line.lower():
                    current_section = "implications"
                elif "제안" in line or "suggestions" in line.lower() or "행동" in line:
                    current_section = "suggestions"
                elif "위험" in line or "주의" in line or "risk" in line.lower() or "alert" in line.lower():
                    current_section = "risks"
                elif "기회" in line or "opportunit" in line.lower():
                    current_section = "opportunities"
                elif line.startswith(("*", "-", "1.", "2.", "3.")):
                    # 리스트 아이템 처리
                    item = line.lstrip("*-0123456789. ").strip()
                    if current_section == "trends" and item:
                        result["key_trends"].append(item)
                    elif current_section == "suggestions" and item:
                        result["action_suggestions"].append(item)
                    elif current_section == "risks" and item:
                        result["risk_alerts"].append(item)
                elif current_section == "headline" and not result["headline"]:
                    result["headline"] = line
                elif current_section == "implications":
                    result["political_implications"] += line + " "
                elif current_section == "opportunities":
                    result["opportunities"] += line + " "
            
            # 결과 정리
            result["political_implications"] = result["political_implications"].strip()
            result["opportunities"] = result["opportunities"].strip()
            
            # 최소한의 내용이 있는지 확인
            if result["headline"] or result["key_trends"]:
                logger.info("마크다운 응답에서 인사이트 추출 성공")
                return result
            return None
        except Exception as e:
            logger.debug(f"텍스트에서 인사이트 추출 실패: {e}")
            return None
    
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
    
    def generate_daily_insight(self, articles: list) -> dict:
        """오늘의 뉴스에 대한 인사이트 생성
        
        Args:
            articles: 뉴스 기사 리스트
            
        Returns:
            인사이트 딕셔너리
        """
        # 뉴스 요약 목록 생성
        news_summaries = []
        for i, article in enumerate(articles[:20]):  # 최대 20개만 분석
            title = article.title if hasattr(article, 'title') else article.get('title', '')
            category = article.category if hasattr(article, 'category') else article.get('category', '일반')
            summary = article.one_line_summary if hasattr(article, 'one_line_summary') else article.get('one_line_summary', '')
            importance = article.importance_score if hasattr(article, 'importance_score') else article.get('importance_score', 1)
            
            news_summaries.append(f"[{category}] (중요도:{importance}) {title}\n   요약: {summary or '(없음)'}")
        
        news_list = "\n".join(news_summaries)
        
        insight_prompt = f"""당신은 정의당 경남도당의 뉴스 분석가입니다.

## 오늘의 뉴스 목록 ({len(articles)}건)
{news_list}

## 중요: 반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트나 설명 없이 JSON만 출력하세요.

{{
  "headline": "오늘의 핵심 메시지 (한 문장으로 작성)",
  "key_trends": [
    "트렌드 1: 구체적인 설명",
    "트렌드 2: 구체적인 설명",
    "트렌드 3: 구체적인 설명"
  ],
  "political_implications": "정치적 함의를 2-3문장으로 작성",
  "action_suggestions": [
    "구체적인 행동 제안 1",
    "구체적인 행동 제안 2",
    "구체적인 행동 제안 3"
  ],
  "risk_alerts": [
    "주의해야 할 위험 요소 1",
    "주의해야 할 위험 요소 2"
  ],
  "opportunities": "기회 요인을 1-2문장으로 작성"
}}

위 JSON 형식을 정확히 따르세요. 마크다운이나 추가 설명 없이 순수 JSON만 출력하세요."""

        try:
            response = self._call_api(
                system_prompt="당신은 진보정당의 정치 분석가입니다. 뉴스를 종합 분석하여 정치적 인사이트를 제공합니다.",
                user_message=insight_prompt
            )
            result = self._parse_json_response(response)
            
            if not result:
                result = {
                    "headline": "오늘의 뉴스 분석",
                    "key_trends": ["분석 결과를 생성하지 못했습니다."],
                    "political_implications": "",
                    "action_suggestions": [],
                    "risk_alerts": [],
                    "opportunities": ""
                }
            
            return result
            
        except Exception as e:
            logger.error(f"인사이트 생성 실패: {e}")
            return {
                "headline": "오늘의 뉴스 분석",
                "key_trends": [f"분석 중 오류 발생: {str(e)}"],
                "political_implications": "",
                "action_suggestions": [],
                "risk_alerts": [],
                "opportunities": ""
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

