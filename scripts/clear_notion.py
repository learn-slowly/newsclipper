#!/usr/bin/env python3
"""노션 데이터베이스의 모든 페이지 삭제"""

import os
import sys
from pathlib import Path
import requests

# 프로젝트 루트를 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# .env 파일 로드
from dotenv import load_dotenv
load_dotenv(project_root / ".env")


def main():
    api_key = os.getenv("NOTION_API_KEY")
    database_id = os.getenv("NOTION_DATABASE_ID")
    
    if not api_key or not database_id:
        print("❌ NOTION_API_KEY 또는 NOTION_DATABASE_ID가 설정되지 않았습니다")
        sys.exit(1)
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    print(f"데이터베이스 ID: {database_id[:8]}...")
    
    # 데이터베이스의 모든 페이지 조회
    results = []
    has_more = True
    start_cursor = None
    
    print("페이지 목록 조회 중...")
    while has_more:
        body = {}
        if start_cursor:
            body["start_cursor"] = start_cursor
        
        response = requests.post(
            f"https://api.notion.com/v1/databases/{database_id}/query",
            headers=headers,
            json=body
        )
        
        if response.status_code != 200:
            print(f"❌ 조회 실패: {response.text}")
            sys.exit(1)
        
        data = response.json()
        results.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")
    
    print(f"총 {len(results)}개 페이지 발견")
    
    if len(results) == 0:
        print("삭제할 페이지가 없습니다")
        return
    
    # 확인
    confirm = input(f"\n⚠️ {len(results)}개 페이지를 모두 삭제하시겠습니까? (yes/no): ")
    if confirm.lower() != "yes":
        print("취소되었습니다")
        return
    
    # 각 페이지 삭제 (아카이브)
    deleted = 0
    for page in results:
        try:
            response = requests.patch(
                f"https://api.notion.com/v1/pages/{page['id']}",
                headers=headers,
                json={"archived": True}
            )
            if response.status_code == 200:
                deleted += 1
                if deleted % 10 == 0:
                    print(f"삭제 진행 중: {deleted}/{len(results)}")
            else:
                print(f"삭제 실패: {response.text}")
        except Exception as e:
            print(f"삭제 실패: {e}")
    
    print(f"\n✅ 총 {deleted}개 페이지 삭제 완료")


if __name__ == "__main__":
    main()
