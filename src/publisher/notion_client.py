"""노션 API 클라이언트 모듈

Notion API 2025-09-03 버전 대응
- data_source_id 사용 필요
- https://developers.notion.com/docs/upgrade-guide-2025-09-03
"""

import sys
from pathlib import Path
from datetime import datetime, date
from typing import List, Optional

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
    
    def __init__(self, api_key: str, database_id: str):
        """
        Args:
            api_key: 노션 Integration 토큰
            database_id: 노션 데이터베이스 ID
        """
        # 2025-09-03 버전 사용
        self.client = Client(auth=api_key, notion_version="2025-09-03")
        self.database_id = database_id
        self.data_source_id = None
        
        # data_source_id 가져오기
        self._fetch_data_source_id()
    
    def _fetch_data_source_id(self):
        """데이터베이스에서 data_source_id 가져오기 (2025-09-03 API 필수)"""
        try:
            response = self.client.databases.retrieve(database_id=self.database_id)
            data_sources = response.get("data_sources", [])
            
            if data_sources:
                self.data_source_id = data_sources[0]["id"]
                logger.info(f"data_source_id 획득: {self.data_source_id[:8]}...")
            else:
                # 이전 버전 API 또는 단일 소스 DB의 경우
                logger.warning("data_sources가 없습니다. database_id를 사용합니다.")
                self.data_source_id = self.database_id
                
        except Exception as e:
            logger.error(f"data_source_id 획득 실패: {e}")
            # fallback으로 database_id 사용
            self.data_source_id = self.database_id
    
    def _get_importance_stars(self, score: int) -> str:
        """중요도 별표 문자열 생성"""
        return "⭐" * score + "☆" * (5 - score)
    
    def _format_keywords(self, keywords: List[str]) -> str:
        """키워드를 해시태그 형식으로 포맷"""
        return " ".join(f"#{kw}" for kw in keywords)
    
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
        
        return blocks
    
    def create_news_page(self, article: NewsArticle) -> Optional[str]:
        """단일 뉴스 페이지 생성
        
        Args:
            article: 뉴스 기사
            
        Returns:
            생성된 페이지 ID (실패시 None)
        """
        try:
            # 카테고리 이모지
            category = article.category or "일반"
            emoji = self.CATEGORY_EMOJI.get(category, "📰")
            
            # 페이지 속성
            properties = {
                "제목": {
                    "title": [{"text": {"content": article.title}}]
                },
                "카테고리": {
                    "select": {"name": category}
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
            
            # 페이지 생성 (2025-09-03: data_source_id 사용)
            response = self.client.pages.create(
                parent={
                    "type": "data_source_id",
                    "data_source_id": self.data_source_id
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
        parent_page_id: Optional[str] = None
    ) -> Optional[str]:
        """일일 요약 페이지 생성
        
        Args:
            target_date: 대상 날짜
            articles: 뉴스 기사 리스트
            parent_page_id: 부모 페이지 ID (선택)
            
        Returns:
            생성된 페이지 ID
        """
        try:
            date_str = target_date.strftime("%Y-%m-%d")
            
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
            
            # 페이지 생성 (2025-09-03: data_source_id 사용)
            if parent_page_id:
                parent = {"type": "page_id", "page_id": parent_page_id}
            else:
                parent = {"type": "data_source_id", "data_source_id": self.data_source_id}
            
            response = self.client.pages.create(
                parent=parent,
                icon={"type": "emoji", "emoji": "📰"},
                properties={
                    "제목": {
                        "title": [{"text": {"content": f"📰 {date_str} 일일 뉴스 클리핑"}}]
                    }
                },
                children=blocks
            )
            
            page_id = response["id"]
            logger.info(f"일일 요약 페이지 생성 완료: {date_str}")
            return page_id
            
        except Exception as e:
            logger.error(f"일일 요약 페이지 생성 실패: {e}")
            return None
    
    def publish_articles(
        self,
        articles: List[NewsArticle],
        create_summary: bool = True
    ) -> dict:
        """여러 뉴스 기사 발행
        
        Args:
            articles: 뉴스 기사 리스트
            create_summary: 일일 요약 페이지 생성 여부
            
        Returns:
            발행 결과 딕셔너리
        """
        results = {
            "success": [],
            "failed": [],
            "summary_page_id": None
        }
        
        logger.info(f"=== 노션 발행 시작: {len(articles)}건 ===")
        
        # 개별 뉴스 페이지 생성
        for article in articles:
            page_id = self.create_news_page(article)
            if page_id:
                results["success"].append(article.title)
            else:
                results["failed"].append(article.title)
        
        # 일일 요약 페이지 생성
        if create_summary and articles:
            summary_page_id = self.create_daily_summary_page(
                target_date=date.today(),
                articles=articles
            )
            results["summary_page_id"] = summary_page_id
        
        logger.info(
            f"=== 발행 완료: 성공 {len(results['success'])}건, "
            f"실패 {len(results['failed'])}건 ==="
        )
        
        return results

