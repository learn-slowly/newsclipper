#!/usr/bin/env python3
"""
수동 실행 스크립트

환경 변수 설정 후 뉴스 클리핑을 1회 실행합니다.

사용법:
    python scripts/run_once.py                    # 오늘 뉴스 클리핑
    python scripts/run_once.py --date 2025-12-01  # 특정 날짜 뉴스 클리핑
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, date

# 프로젝트 루트를 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# .env 파일 로드
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from main import run_news_clipper


def parse_args():
    parser = argparse.ArgumentParser(description="뉴스 클리핑 수동 실행")
    parser.add_argument(
        "--date", "-d",
        type=str,
        help="클리핑할 날짜 (YYYY-MM-DD 형식, 기본값: 오늘)"
    )
    parser.add_argument(
        "--period", "-p",
        type=str,
        choices=["오전", "오후", "both"],
        default="both",
        help="클리핑 기간 (오전/오후/both, 기본값: both)"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    
    target_date = None
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
            print(f"🚀 뉴스 클리핑 수동 실행 (날짜: {target_date})")
        except ValueError:
            print("❌ 날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식을 사용하세요.")
            sys.exit(1)
    else:
        print("🚀 뉴스 클리핑 수동 실행 (오늘)")
    
    run_news_clipper()

