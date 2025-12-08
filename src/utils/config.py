"""설정 관리 모듈"""

import json
from pathlib import Path
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """애플리케이션 설정"""
    
    # API Keys
    google_api_key: str = Field(default="", description="Google AI (Gemini) API Key")
    notion_api_key: str = Field(default="", description="Notion Integration Token")
    notion_database_id: str = Field(default="", description="Notion Database ID")
    naver_client_id: Optional[str] = Field(default=None, description="Naver API Client ID")
    naver_client_secret: Optional[str] = Field(default=None, description="Naver API Client Secret")
    
    # 실행 설정
    log_level: str = Field(default="INFO", description="로그 레벨")
    max_news_per_run: int = Field(default=100, description="실행당 최대 뉴스 수")
    relevance_threshold: int = Field(default=60, description="관련성 임계값")
    
    # 경로 설정
    config_path: Path = Field(
        default=Path(__file__).parent.parent.parent / "config" / "config.json",
        description="설정 파일 경로"
    )
    db_path: Path = Field(
        default=Path(__file__).parent.parent.parent / "data" / "news_cache.db",
        description="데이터베이스 경로"
    )
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }
    
    def load_config(self) -> dict:
        """JSON 설정 파일 로드"""
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    
    def get_keyword_combinations(self) -> list:
        """키워드 조합 목록 반환"""
        config = self.load_config()
        return config.get("keyword_combinations", [])
    
    def get_filtering_config(self) -> dict:
        """필터링 설정 반환"""
        config = self.load_config()
        return config.get("filtering", {})
    
    def get_news_sources(self) -> dict:
        """뉴스 소스 설정 반환"""
        config = self.load_config()
        return config.get("news_sources", {})


@lru_cache()
def get_settings() -> Settings:
    """설정 싱글톤 반환"""
    return Settings()

