"""state/seen.db 정리 스크립트 (워크플로 전용)

GitHub Actions의 각 워크플로가 DB를 커밋하기 전에 실행한다.
파이프라인이 중간에 실패해 정리를 못 하고 끝나도, DB 파일이 커밋 한도
(GitHub 100MB)를 넘지 않도록 여기서 한 번 더 보장한다.

사용법:
    python scripts/prune_db.py [--article-days 45] [--seen-days 30] [--max-mb 50]
"""

import argparse
import sys
from pathlib import Path

# 스크립트를 저장소 루트에서 실행하지 않아도 src를 찾을 수 있게 한다
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.storage import (  # noqa: E402
    DEFAULT_ARTICLE_RETENTION_DAYS,
    DEFAULT_MAX_DB_SIZE_MB,
    DEFAULT_SEEN_RETENTION_DAYS,
    Storage,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="seen.db 정리 및 크기 관리")
    parser.add_argument("--article-days", type=int, default=DEFAULT_ARTICLE_RETENTION_DAYS)
    parser.add_argument("--seen-days", type=int, default=DEFAULT_SEEN_RETENTION_DAYS)
    parser.add_argument("--max-mb", type=float, default=DEFAULT_MAX_DB_SIZE_MB)
    args = parser.parse_args()

    storage = Storage()
    stats = storage.prune(
        article_days=args.article_days,
        seen_days=args.seen_days,
        max_db_size_mb=args.max_mb,
    )

    size_mb = stats["size_after_bytes"] / 1024 / 1024
    print(f"state/seen.db: {size_mb:.2f} MB (상한 {args.max_mb:.0f} MB)")

    # 상한을 넘긴 채로 push하면 원격에서 거부되므로, 여기서 먼저 명확히 알린다
    if stats["size_after_bytes"] > args.max_mb * 1024 * 1024:
        print("::error::state/seen.db is still larger than the configured limit", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
