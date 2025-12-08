"""뉴스 수집 모듈 테스트"""

import sys
from pathlib import Path

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from collector import GoogleNewsCollector


def test_google_news_collector():
    """Google News 수집 테스트"""
    
    print("=" * 60)
    print("🧪 Google News 수집 테스트")
    print("=" * 60)
    
    collector = GoogleNewsCollector()
    
    # 테스트 키워드 조합
    test_combinations = [
        {
            "name": "노동-경남",
            "issues": ["노동", "산재"],
            "regions": ["경남", "창원"],
            "category": "노동"
        },
        {
            "name": "정의당-경남",
            "issues": ["정의당"],
            "regions": ["경남", "경상남도"],
            "category": "정당"
        }
    ]
    
    # 수집 테스트
    articles = collector.collect_from_combinations(
        keyword_combinations=test_combinations,
        max_results_per_combo=5,
        when="7d"  # 테스트를 위해 7일로 확장
    )
    
    print(f"\n📰 수집된 뉴스: {len(articles)}건")
    print("-" * 60)
    
    for i, article in enumerate(articles[:10], 1):
        print(f"\n[{i}] {article.title}")
        print(f"    📰 언론사: {article.media_name or 'N/A'}")
        print(f"    🏷️ 카테고리: {article.category}")
        print(f"    📅 발행일: {article.published_at}")
        print(f"    🔗 {article.url[:80]}...")
    
    print("\n" + "=" * 60)
    print("✅ 테스트 완료")
    print("=" * 60)
    
    return articles


if __name__ == "__main__":
    test_google_news_collector()

