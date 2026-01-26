"""노션 API 클라이언트 모듈

Notion API 2025-09-03 버전 대응
- data_source_id 사용 필요
- https://developers.notion.com/docs/upgrade-guide-2025-09-03
- 월별 데이터베이스 자동 생성 기능
"""

import sys
from pathlib import Path
from datetime import datetime, date
from typing import List, Optional, Dict

from notion_client import Client
from loguru import logger

# 상위 디렉토리 import를 위한 경로 설정
src_dir = Path(__file__).parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from collector.models import NewsArticle


class NotionPublisher:
    """노션에 뉴스 클리핑 페이지 생성
    
    Notion API 2025-09-03 버전 대응
    """
    
    # 중요도 이모지 매핑
    IMPORTANCE_EMOJI = {
        5: "🚨",
        4: "⭐",
        3: "📌",
        2: "📄",
        1: "📋"
    }
    
    # 카테고리 이모지 매핑
    CATEGORY_EMOJI = {
        "정당": "🏛️",
        "노동": "👷",
        "환경": "🌱",
        "여성": "👩",
        "동물복지": "🐾",
        "선거": "🗳️",
        "지역": "📍",
        "일반": "📰"
    }
    
    # 지역 키워드 매핑 (6개 주요 지역 + 경상남도)
    REGION_KEYWORDS = {
        "창원": ["창원", "마산", "진해", "창원시"],
        "김해": ["김해", "김해시"],
        "진주": ["진주", "진주시"],
        "양산": ["양산", "양산시"],
        "거제": ["거제", "거제시"],
        "경상남도": ["경남", "경상남도", "도청", "경남도"]
    }
    
    def __init__(self, api_key: str, database_id: str = None, parent_page_id: str = None):
        """
        Args:
            api_key: 노션 Integration 토큰
            database_id: 노션 데이터베이스 ID (기존 DB 사용시)
            parent_page_id: 월별 DB를 생성할 상위 페이지 ID (자동 생성시)
        """
        # 2022-06-28 버전 사용 (안정성 확보)
        self.client = Client(auth=api_key, notion_version="2022-06-28")
        self.parent_page_id = parent_page_id
        self.database_id = database_id
        self.data_source_id = None
        self._monthly_db_cache: Dict[str, str] = {}  # 월별 DB ID 캐시
        self._monthly_data_source_cache: Dict[str, str] = {}  # 월별 data_source_id 캐시
        
        # 기존 database_id가 있으면 data_source_id 가져오기
        if database_id:
            self._fetch_data_source_id()
    
    def _fetch_data_source_id(self, db_id: str = None):
        """데이터베이스에서 data_source_id 가져오기 (2025-09-03 API 필수)"""
        target_db_id = db_id or self.database_id
        try:
            response = self.client.databases.retrieve(database_id=target_db_id)
            data_sources = response.get("data_sources", [])
            
            if data_sources:
                data_source_id = data_sources[0]["id"]
                logger.info(f"data_source_id 획득: {data_source_id[:8]}...")
                if not db_id:  # 기본 DB인 경우 저장
                    self.data_source_id = data_source_id
                return data_source_id
            else:
                # 이전 버전 API 또는 단일 소스 DB의 경우
                logger.warning("data_sources가 없습니다. database_id를 사용합니다.")
                if not db_id:
                    self.data_source_id = target_db_id
                return target_db_id
                
        except Exception as e:
            logger.error(f"data_source_id 획득 실패: {e}")
            # fallback으로 database_id 사용
            if not db_id:
                self.data_source_id = target_db_id
            return target_db_id
    
    def _get_week_number(self, d: date) -> int:
        """
        날짜의 주차를 계산합니다 (월요일 시작 기준).
        2026년 1월 예시:
        - 1주차: 1.1 ~ 1.4
        - 2주차: 1.5 ~ 1.11
        - 3주차: 1.12 ~ 1.18
        - 4주차: 1.19 ~ 1.25
        - 5주차: 1.26 ~ 1.31
        """
        # 2026년 1월 하드코딩 (안전성 확보)
        if d.year == 2026 and d.month == 1:
            if d.day <= 4: return 1
            elif d.day <= 11: return 2
            elif d.day <= 18: return 3
            elif d.day <= 25: return 4
            else: return 5
            
        # 일반적인 주차 계산 (ISO 달력 기준과 유사하게)
        # 여기서는 단순하게 해당 월의 n번째 주차로 계산
        # 1일이 속한 주를 1주차로 시작
        first_day = d.replace(day=1)
        adjusted_day = d.day + first_day.weekday()
        return (adjusted_day - 1) // 7 + 1

    def _get_weekly_summary_page_title(self, d: date) -> str:
        week_num = self._get_week_number(d)
        return f"{d.strftime('%Y-%m')} {week_num}주차 요약"

    def _get_or_create_weekly_summary_page(self, target_date: date) -> str:
        """주차별 요약 페이지를 가져오거나 생성합니다."""
        if not self.parent_page_id:
            logger.error("parent_page_id가 설정되지 않았습니다.")
            return ""

        page_title = self._get_weekly_summary_page_title(target_date)
        
        # 1. 이미 존재하는지 검색
        # (성능을 위해 parent_page_id의 자식을 스캔하는 것이 좋음)
        children = self.client.blocks.children.list(block_id=self.parent_page_id)
        for block in children.get("results", []):
            if block["type"] == "child_page":
                title = block.get("child_page", {}).get("title", "")
                if title == page_title:
                    return block["id"]
        
        # 2. 없으면 생성
        logger.info(f"주차별 요약 페이지 생성: {page_title}")
        try:
            response = self.client.pages.create(
                parent={"page_id": self.parent_page_id},
                icon={"type": "emoji", "emoji": "📁"},
                properties={
                    "title": {
                        "title": [{"text": {"content": page_title}}]
                    }
                }
            )
            return response["id"]
        except Exception as e:
            logger.error(f"주차별 요약 페이지 생성 실패: {e}")
            return ""

    def _get_weekly_db_name(self, target_date: date) -> str:
        """주차별 DB 이름 생성"""
        week_num = self._get_week_number(target_date)
        return f"📰 {target_date.strftime('%Y-%m')} {week_num}주차 뉴스클리핑"

    def _get_monthly_db_name(self, target_date: date) -> str:
        # Backward compatibility or unused now
        return f"📰 {target_date.strftime('%Y-%m')} 뉴스클리핑"
    
    def _find_weekly_database(self, summary_page_id: str, target_date: date) -> Optional[str]:
        """주차별 요약 페이지 내에서 주차별 데이터베이스 찾기"""
        db_name = self._get_weekly_db_name(target_date)
        
        try:
            # 페이지 내 자식 블록 검색
            children = self.client.blocks.children.list(block_id=summary_page_id)
            
            for block in children.get("results", []):
                if block.get("type") == "child_database":
                    db_id = block["id"]
                    db_info = self.client.databases.retrieve(database_id=db_id)
                    title_parts = db_info.get("title", [])
                    if title_parts:
                        title = "".join([t.get("plain_text", "") for t in title_parts])
                        if db_name == title:
                            logger.info(f"기존 주차별 DB 발견: {title}")
                            return db_id
            return None
        except Exception as e:
            logger.error(f"주차별 DB 검색 실패: {e}")
            return None
    
    def get_or_create_weekly_database(self, target_date: date) -> Optional[str]:
        db_name = self._get_weekly_db_name(target_date)
        if db_name in self._monthly_db_cache:
            return self._monthly_db_cache[db_name]

        # [Modified] 전역 검색(search) 제거 - 잘못된 DB(예: 12월 DB)가 검색되는 문제 방지
        # 대신, 상위 페이지 내에서 주차별 요약 페이지를 찾고, 그 안의 DB를 찾거나 새로 생성하는 방식 사용
        
        # 1. 주차별 요약 페이지 ID 찾기 (또는 생성)
        summary_page_id = self._get_or_create_weekly_summary_page(target_date)
        if not summary_page_id:
            logger.error("주차별 요약 페이지를 준비할 수 없습니다.")
            return None

        # 2. 요약 페이지 내에 이미 DB가 있는지 확인
        existing_db_id = self._find_weekly_database(summary_page_id, target_date)
        if existing_db_id:
            self._monthly_db_cache[db_name] = existing_db_id
            return existing_db_id

        # Summary Page는 위에서 이미 확보함

        
        # 데이터베이스 속성 정의
        properties = {
            "제목": {"title": {}},
            "카테고리": {
                "select": {
                    "options": [
                        {"name": "정당", "color": "purple"},
                        {"name": "노동", "color": "red"},
                        {"name": "환경", "color": "green"},
                        {"name": "여성", "color": "pink"},
                        {"name": "동물복지", "color": "orange"},
                        {"name": "선거", "color": "blue"},
                        {"name": "복지", "color": "yellow"},
                        {"name": "인권", "color": "brown"},
                        {"name": "지역", "color": "gray"},
                        {"name": "일반", "color": "default"}
                    ]
                }
            },
            "지역": {
                "select": {
                    "options": [
                        {"name": "창원", "color": "blue"},
                        {"name": "김해", "color": "green"},
                        {"name": "진주", "color": "purple"},
                        {"name": "양산", "color": "orange"},
                        {"name": "거제", "color": "pink"},
                        {"name": "경상남도", "color": "red"},
                        {"name": "그외", "color": "gray"}
                    ]
                }
            },
            "중요도": {"number": {}},
            "언론사": {"rich_text": {}},
            "원문링크": {"url": {}},
            "발행일시": {"date": {}},
            "키워드": {"multi_select": {}},
            "대응완료": {"checkbox": {}}
        }
        
        try:
            # 데이터베이스 생성 (2022-06-28 API Spec)
            # Global Parent 하위에 생성
            response = self.client.request(
                path="databases",
                method="POST",
                body={
                    "parent": {"type": "page_id", "page_id": self.parent_page_id},
                    "title": [{"type": "text", "text": {"content": db_name}}],
                    "icon": {"type": "emoji", "emoji": "📰"},
                    "properties": properties
                }
            )
            
            db_id = response["id"]
            logger.info(f"주차별 DB 생성 완료: {db_name} ({db_id})")

            # [Optional] 요약 페이지에 링크 추가
            if summary_page_id:
                try:
                    self.client.blocks.children.append(
                        block_id=summary_page_id,
                        children=[
                            {
                                "object": "block", 
                                "type": "paragraph", 
                                "paragraph": {
                                    "rich_text": [
                                        {"type": "text", "text": {"content": "🔗 관련 뉴스 데이터베이스: "}},
                                        {"type": "mention", "mention": {"type": "database", "database": {"id": db_id}}}
                                    ]
                                }
                            }
                        ]
                    )
                except Exception as e:
                    logger.warning(f"요약 페이지에 DB 링크 추가 실패: {e}")

            self._monthly_db_cache[db_name] = db_id
            return db_id
            
        except Exception as e:
            logger.error(f"주차별 DB 생성 실패: {e}")
            return None

    def get_or_create_monthly_database(self, target_date: date) -> Optional[str]:
        # Alias for backward compatibility
        return self.get_or_create_weekly_database(target_date)
    
    def _get_data_source_id_for_db(self, db_id: str, target_date: date = None) -> str:
        """특정 데이터베이스의 data_source_id 가져오기"""
        # 기본 DB인 경우
        if db_id == self.database_id and self.data_source_id:
            return self.data_source_id
        
        # 월별 DB 캐시 확인
        if target_date:
            month_key = target_date.strftime('%Y-%m')
            if month_key in self._monthly_data_source_cache and self._monthly_data_source_cache[month_key]:
                return self._monthly_data_source_cache[month_key]
        
        # data_source_id 가져오기
        data_source_id = self._fetch_data_source_id(db_id)
        
        # 캐시에 저장
        if target_date:
            month_key = target_date.strftime('%Y-%m')
            self._monthly_data_source_cache[month_key] = data_source_id
        
        return data_source_id
    
    def _get_importance_stars(self, score: int) -> str:
        """중요도 별표 문자열 생성"""
        return "⭐" * score + "☆" * (5 - score)
    
    def _format_keywords(self, keywords: List[str]) -> str:
        """키워드를 해시태그 형식으로 포맷"""
        return " ".join(f"#{kw}" for kw in keywords)
    
    def _extract_region(self, article) -> str:
        """뉴스에서 지역 추출 (제목 기준)
        
        Args:
            article: 뉴스 기사
            
        Returns:
            지역명 (창원, 김해, 진주, 양산, 거제, 경상남도, 그외)
        """
        # 제목에서만 지역 키워드 검색 (description은 부정확할 수 있음)
        title = article.title or ""
        
        # 우선순위 순서대로 체크 (시 단위 먼저, 경상남도는 마지막)
        priority_order = ["김해", "진주", "양산", "거제", "창원"]
        
        for region in priority_order:
            keywords = self.REGION_KEYWORDS.get(region, [])
            for keyword in keywords:
                if keyword in title:
                    return region
        
        # 경상남도 체크 (마지막) - "경남도", "경상남도", "도청" 등
        for keyword in self.REGION_KEYWORDS["경상남도"]:
            if keyword in title:
                return "경상남도"
        
        return "그외"
    
    def _build_summary_blocks(self, article: NewsArticle) -> List[dict]:
        """뉴스 요약을 노션 블록으로 변환"""
        blocks = []
        
        # 한줄요약
        if article.one_line_summary:
            blocks.append({
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{"type": "text", "text": {"content": article.one_line_summary}}],
                    "icon": {"type": "emoji", "emoji": "💡"},
                    "color": "blue_background"
                }
            })
        
        # 상세요약
        if article.detailed_summary:
            summary = article.detailed_summary
            
            # 배경
            if summary.get("background"):
                blocks.append({
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [{"type": "text", "text": {"content": "📋 배경"}}]
                    }
                })
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": summary["background"]}}]
                    }
                })
            
            # 현황
            if summary.get("current_situation"):
                blocks.append({
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [{"type": "text", "text": {"content": "📊 현황"}}]
                    }
                })
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": summary["current_situation"]}}]
                    }
                })
            
            # 영향
            if summary.get("impact"):
                blocks.append({
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [{"type": "text", "text": {"content": "💥 영향"}}]
                    }
                })
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": summary["impact"]}}]
                    }
                })
            
            # 대응 (액션 아이템)
            action_items = summary.get("action_items", [])
            if action_items:
                blocks.append({
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [{"type": "text", "text": {"content": "✅ 대응 필요"}}]
                    }
                })
                for item in action_items:
                    blocks.append({
                        "object": "block",
                        "type": "to_do",
                        "to_do": {
                            "rich_text": [{"type": "text", "text": {"content": item}}],
                            "checked": False
                        }
                    })
        
        # 원문 링크
        blocks.append({
            "object": "block",
            "type": "divider",
            "divider": {}
        })
        blocks.append({
            "object": "block",
            "type": "bookmark",
            "bookmark": {
                "url": article.url
            }
        })
        
        # 관련 뉴스 링크 (중복 그룹화된 경우)
        if hasattr(article, 'related_urls') and article.related_urls:
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"type": "text", "text": {"content": f"🔗 관련 기사 ({len(article.related_urls)}건)"}}]
                }
            })
            
            for related in article.related_urls:
                # 언론사명과 함께 링크 표시
                media = related.get('media', '알 수 없음')
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [
                            {"type": "text", "text": {"content": f"[{media}] "}},
                            {
                                "type": "text",
                                "text": {
                                    "content": related.get('title', '관련 기사')[:50],
                                    "link": {"url": related.get('url', '')}
                                }
                            }
                        ]
                    }
                })
        
        return blocks
    
    def create_news_page(self, article: NewsArticle, target_date: date = None) -> Optional[str]:
        """단일 뉴스 페이지 생성
        
        Args:
            article: 뉴스 기사
            target_date: 대상 날짜 (월별 DB 선택용)
            
        Returns:
            생성된 페이지 ID (실패시 None)
        """
        try:
            # 대상 날짜 결정
            if target_date is None:
                target_date = date.today()
            
            # 월별 DB 가져오기 또는 생성
            db_id = self.get_or_create_monthly_database(target_date)
            if not db_id:
                logger.error("데이터베이스를 찾을 수 없습니다.")
                return None
            
            # data_source_id 가져오기 (SKIP: data_source_id가 잘못된 ID를 반환하는 경우 방지)
            # data_source_id = self._get_data_source_id_for_db(db_id, target_date)
            
            # 카테고리 이모지
            category = article.category or "일반"
            emoji = self.CATEGORY_EMOJI.get(category, "📰")
            
            # 지역 추출
            region = self._extract_region(article)

            # [GUARD] 2026년 기사가 2025년 12월 DB로 들어가는 문제 방지
            # Dec 2025 DB ID: 2c3bfd7bbb8e80cb8338ce1e36823e8a
            DEC_2025_DB_ID = "2c3bfd7bbb8e80cb8338ce1e36823e8a"
            if target_date.year >= 2026 and db_id.replace("-", "") == DEC_2025_DB_ID:
                logger.warning(f"⛔ [GUARD] 2026년 기사({target_date})가 12월 DB({db_id})로 저장되는 것을 차단했습니다.")
                return None
            
            # 페이지 속성
            properties = {
                "제목": {
                    "title": [{"text": {"content": article.title}}]
                },
                "카테고리": {
                    "select": {"name": category}
                },
                "지역": {
                    "select": {"name": region}
                },
                "중요도": {
                    "number": article.importance_score or 1
                },
                "언론사": {
                    "rich_text": [{"text": {"content": article.media_name or "알 수 없음"}}]
                },
                "원문링크": {
                    "url": article.url
                },
                "대응완료": {
                    "checkbox": False
                }
            }
            
            # 발행일시 (있는 경우)
            if article.published_at:
                properties["발행일시"] = {
                    "date": {"start": article.published_at.isoformat()}
                }
            
            # 키워드 (있는 경우)
            if article.keywords:
                properties["키워드"] = {
                    "multi_select": [{"name": kw} for kw in article.keywords[:5]]
                }
            
            # 페이지 생성
            response = self.client.pages.create(
                parent={
                    "type": "database_id",
                    "database_id": db_id  # Use db_id directly
                },
                icon={"type": "emoji", "emoji": emoji},
                properties=properties,
                children=self._build_summary_blocks(article)
            )
            
            page_id = response["id"]
            logger.info(f"페이지 생성 완료: {article.title[:30]}...")
            return page_id
            
        except Exception as e:
            logger.error(f"페이지 생성 실패: {e}")
            return None
    
    def create_daily_summary_page(
        self,
        target_date: date,
        articles: List[NewsArticle],
        parent_page_id: Optional[str] = None,
        insight: Optional[dict] = None,
        period: Optional[str] = None
    ) -> Optional[str]:
        """일일 요약 페이지 생성
        
        Args:
            target_date: 대상 날짜
            articles: 뉴스 기사 리스트
            parent_page_id: 부모 페이지 ID (선택)
            insight: AI가 생성한 인사이트 딕셔너리 (선택)
            period: 기간 구분 ("오전", "오후" 또는 None)
            
        Returns:
            생성된 페이지 ID
        """
        try:
            date_str = target_date.strftime("%Y-%m-%d")
            period_str = f" {period}" if period else ""
            
            # 통계 계산
            total_count = len(articles)
            urgent_count = sum(1 for a in articles if (a.importance_score or 0) >= 5)
            important_count = sum(1 for a in articles if (a.importance_score or 0) == 4)
            
            # 요약 블록 생성
            blocks = [
                # 오늘의 요약
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"type": "text", "text": {"content": "📊 오늘의 요약"}}]
                    }
                },
                {
                    "object": "block",
                    "type": "callout",
                    "callout": {
                        "rich_text": [
                            {"type": "text", "text": {"content": f"🔢 총 뉴스: {total_count}건\n"}},
                            {"type": "text", "text": {"content": f"🚨 긴급 대응: {urgent_count}건\n"}},
                            {"type": "text", "text": {"content": f"⭐ 주요 뉴스: {important_count}건"}}
                        ],
                        "icon": {"type": "emoji", "emoji": "📈"},
                        "color": "gray_background"
                    }
                },
                {"object": "block", "type": "divider", "divider": {}}
            ]
            
            # 오늘의 인사이트 섹션 (AI 생성)
            if insight:
                blocks.append({
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"type": "text", "text": {"content": "💡 오늘의 인사이트"}}]
                    }
                })
                
                # 헤드라인
                if insight.get("headline"):
                    blocks.append({
                        "object": "block",
                        "type": "callout",
                        "callout": {
                            "rich_text": [{"type": "text", "text": {"content": insight["headline"]}, "annotations": {"bold": True}}],
                            "icon": {"type": "emoji", "emoji": "🎯"},
                            "color": "yellow_background"
                        }
                    })
                
                # 주요 트렌드
                if insight.get("key_trends"):
                    blocks.append({
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {
                            "rich_text": [{"type": "text", "text": {"content": "📈 주요 트렌드"}}]
                        }
                    })
                    for trend in insight["key_trends"]:
                        blocks.append({
                            "object": "block",
                            "type": "bulleted_list_item",
                            "bulleted_list_item": {
                                "rich_text": [{"type": "text", "text": {"content": trend}}]
                            }
                        })
                
                # 정치적 함의
                if insight.get("political_implications"):
                    blocks.append({
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {
                            "rich_text": [{"type": "text", "text": {"content": "🏛️ 정치적 함의"}}]
                        }
                    })
                    blocks.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": insight["political_implications"]}}]
                        }
                    })
                
                # 대응 제안
                if insight.get("action_suggestions"):
                    blocks.append({
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {
                            "rich_text": [{"type": "text", "text": {"content": "✅ 대응 제안"}}]
                        }
                    })
                    for suggestion in insight["action_suggestions"]:
                        blocks.append({
                            "object": "block",
                            "type": "to_do",
                            "to_do": {
                                "rich_text": [{"type": "text", "text": {"content": suggestion}}],
                                "checked": False
                            }
                        })
                
                # 주의사항
                if insight.get("risk_alerts"):
                    blocks.append({
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {
                            "rich_text": [{"type": "text", "text": {"content": "⚠️ 주의사항"}}]
                        }
                    })
                    for alert in insight["risk_alerts"]:
                        blocks.append({
                            "object": "block",
                            "type": "bulleted_list_item",
                            "bulleted_list_item": {
                                "rich_text": [{"type": "text", "text": {"content": alert}}]
                            }
                        })
                
                # 기회 요인
                if insight.get("opportunities"):
                    blocks.append({
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {
                            "rich_text": [{"type": "text", "text": {"content": "🌟 기회 요인"}}]
                        }
                    })
                    blocks.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": insight["opportunities"]}}]
                        }
                    })
                
                blocks.append({"object": "block", "type": "divider", "divider": {}})
            
            # 중요도별 섹션
            importance_groups = {
                "🚨 긴급 뉴스": [a for a in articles if (a.importance_score or 0) >= 5],
                "⭐ 주요 뉴스": [a for a in articles if (a.importance_score or 0) == 4],
                "📌 일반 뉴스": [a for a in articles if (a.importance_score or 0) <= 3]
            }
            
            for section_title, section_articles in importance_groups.items():
                if section_articles:
                    blocks.append({
                        "object": "block",
                        "type": "heading_2",
                        "heading_2": {
                            "rich_text": [{"type": "text", "text": {"content": section_title}}]
                        }
                    })
                    
                    for article in section_articles:
                        # 뉴스 항목 토글
                        summary_text = article.one_line_summary or article.description or ""
                        if len(summary_text) > 100:
                            summary_text = summary_text[:100] + "..."
                        
                        blocks.append({
                            "object": "block",
                            "type": "toggle",
                            "toggle": {
                                "rich_text": [
                                    {"type": "text", "text": {"content": f"[{article.category or '일반'}] "}},
                                    {"type": "text", "text": {"content": article.title}, "annotations": {"bold": True}}
                                ],
                                "children": [
                                    {
                                        "object": "block",
                                        "type": "paragraph",
                                        "paragraph": {
                                            "rich_text": [
                                                {"type": "text", "text": {"content": f"📰 {article.media_name or '알 수 없음'} | "}},
                                                {"type": "text", "text": {"content": f"중요도: {self._get_importance_stars(article.importance_score or 1)}\n\n"}},
                                                {"type": "text", "text": {"content": summary_text}}
                                            ]
                                        }
                                    },
                                    {
                                        "object": "block",
                                        "type": "bookmark",
                                        "bookmark": {"url": article.url}
                                    }
                                ]
                            }
                        })
            
            # 주차별 요약 페이지 확보 (부모 페이지로 사용)
            weekly_page_id = self._get_or_create_weekly_summary_page(target_date)
            
            # 주차별 DB 생성 (존재 확인용)
            self.get_or_create_weekly_database(target_date)
            
            # 제목 definition moved up
            title = f"📰 {date_str}{period_str} 뉴스 클리핑"
            
            # 페이지 생성
            page_properties = {}
            parent = {}
            
            if parent_page_id:
                parent = {"type": "page_id", "page_id": parent_page_id}
                page_properties = {
                    "title": {"title": [{"text": {"content": title}}]}
                }
            elif weekly_page_id:
                parent = {"type": "page_id", "page_id": weekly_page_id}
                page_properties = {
                    "title": {"title": [{"text": {"content": title}}]}
                }
            else:
                db_id = self.get_or_create_monthly_database(target_date)
                data_source_id = self._get_data_source_id_for_db(db_id, target_date)
                # FIX: use database_id type
                parent = {"type": "database_id", "database_id": data_source_id}
                page_properties = {
                    "제목": {"title": [{"text": {"content": title}}]}
                }
            
            response = self.client.pages.create(
                parent=parent,
                icon={"type": "emoji", "emoji": "📰"},
                properties=page_properties,
                children=blocks
            )
            
            page_id = response["id"]
            logger.info(f"일일 요약 페이지 생성 완료: {date_str}{period_str}")
            return page_id
            
        except Exception as e:
            logger.error(f"일일 요약 페이지 생성 실패: {e}")
            return None
    
    def publish_articles(
        self,
        articles: List[NewsArticle],
        create_summary: bool = True,
        insight: Optional[dict] = None,
        period: Optional[str] = None,
        target_date: date = None
    ) -> dict:
        """여러 뉴스 기사 발행
        
        Args:
            articles: 뉴스 기사 리스트
            create_summary: 일일 요약 페이지 생성 여부
            insight: AI가 생성한 인사이트 딕셔너리 (선택)
            period: 기간 구분 ("오전", "오후" 또는 None)
            target_date: 대상 날짜 (기본값: 오늘)
            
        Returns:
            발행 결과 딕셔너리
        """
        results = {
            "success": [],
            "failed": [],
            "summary_page_id": None,
            "database_id": None
        }
        
        # 대상 날짜 결정
        if target_date is None:
            target_date = date.today()
        
        logger.info(f"=== 노션 발행 시작: {len(articles)}건 ({target_date}) ===")
        
        # 월별 DB 확인/생성
        db_id = self.get_or_create_monthly_database(target_date)
        if db_id:
            results["database_id"] = db_id
            logger.info(f"사용할 DB: {db_id[:8]}...")
        
        # 개별 뉴스 페이지 생성
        for article in articles:
            page_id = self.create_news_page(article, target_date)
            if page_id:
                results["success"].append(article.title)
            else:
                results["failed"].append(article.title)
        
        # 일일 요약 페이지 생성
        if create_summary and articles:
            summary_page_id = self.create_daily_summary_page(
                target_date=target_date,
                articles=articles,
                insight=insight,
                period=period
            )
            results["summary_page_id"] = summary_page_id
        
        logger.info(
            f"=== 발행 완료: 성공 {len(results['success'])}건, "
            f"실패 {len(results['failed'])}건 ==="
        )
        
        return results

