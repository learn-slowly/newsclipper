#!/usr/bin/env python3
"""
뉴스 수집만 테스트하는 스크립트

API 키 없이도 Google News RSS 수집을 테스트할 수 있습니다.
"""

import sys
from pathlib import Path

# 프로젝트 루트를 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from collector import GoogleNewsCollector
import json


def main():
    print("=" * 60)
    print("🧪 뉴스 수집 테스트 (API 키 불필요)")
    print("=" * 60)
    
    # 설정 파일 로드
    config_path = project_root / "config" / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    keyword_combinations = config.get("keyword_combinations", [])
    print(f"\n📝 키워드 조합 {len(keyword_combinations)}개 로드됨")
    
    for combo in keyword_combinations:
        print(f"  - {combo['name']}: {combo['issues'][:2]}... + {combo['regions'][:2]}...")
    
    # Google News 수집
    collector = GoogleNewsCollector()
    
    print("\n" + "-" * 60)
    print("📰 Google News RSS 수집 중...")
    print("-" * 60)
    
    articles = collector.collect_from_combinations(
        keyword_combinations=keyword_combinations,
        max_results_per_combo=10,
        when="1d"
    )
    
    print(f"\n✅ 총 {len(articles)}건 수집됨")
    print("\n" + "=" * 60)
    print("📋 수집된 뉴스 목록")
    print("=" * 60)
    
    # 카테고리별 그룹화
    by_category = {}
    for article in articles:
        cat = article.category or "일반"
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(article)
    
    for category, cat_articles in by_category.items():
        print(f"\n📁 [{category}] - {len(cat_articles)}건")
        print("-" * 40)
        
        for article in cat_articles[:5]:  # 카테고리당 5개만 출력
            title = article.title[:50] + "..." if len(article.title) > 50 else article.title
            media = article.media_name or "알 수 없음"
            print(f"  • {title}")
            print(f"    └ {media} | {article.published_at or 'N/A'}")
    
    print("\n" + "=" * 60)
    print("✅ 테스트 완료!")
    print("=" * 60)
    
    return articles


if __name__ == "__main__":
    main()

