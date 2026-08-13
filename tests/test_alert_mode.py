"""
속보 모드 및 관련 포맷/Storage 함수 단위 테스트
"""

import tempfile
from pathlib import Path
from src.collect import Article
from src.storage import Storage
from src.telegram_push import format_alert_message


def test_format_alert_message():
    """속보 메시지 포맷팅 검증"""
    articles = [
        Article(
            title="STX 조선 대형 산재 발생",
            url="https://example.com/alert",
            source="경남도민일보",
            importance=5,
            scope="gyeongnam",
            summary="현장에서 사고 발생",
        )
    ]

    msg = format_alert_message(articles)
    assert "🚨 [속보]" in msg
    assert "🔥 [5|경남]" in msg
    assert "STX 조선 대형 산재 발생" in msg
    assert "https://example.com/alert" in msg


def test_storage_alert_seen():
    """Storage의 alert_seen 관련 동작 검증"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_seen.db"
        storage = Storage(db_path)

        url_hash = "abc123hash"
        assert not storage.is_alert_processed(url_hash)

        storage.mark_alert_processed(
            url_hash, "https://example.com", "테스트 속보", importance=5, sent_alert=True
        )

        assert storage.is_alert_processed(url_hash)
        assert url_hash in storage.get_alert_seen_hashes(days=7)
