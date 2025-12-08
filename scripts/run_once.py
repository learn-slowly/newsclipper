#!/usr/bin/env python3
"""
수동 실행 스크립트

환경 변수 설정 후 뉴스 클리핑을 1회 실행합니다.
"""

import sys
from pathlib import Path

# 프로젝트 루트를 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# .env 파일 로드
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from main import run_news_clipper


if __name__ == "__main__":
    print("🚀 뉴스 클리핑 수동 실행")
    run_news_clipper()

