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
        ),
        Article(
            title="중대재해 관련 긴급 대응",
            url="https://example.com/alert4",
            source="경남도민일보",
            importance=4,
            scope="gyeongnam",
            summary="중대재해 수사 진행",
        ),
    ]

    msg = format_alert_message(articles)
    assert "🚨 [속보]" in msg
    assert "🔥 [5|경남]" in msg
    assert "🔥 [4|경남]" in msg
    assert "STX 조선 대형 산재 발생" in msg
    assert "중대재해 관련 긴급 대응" in msg

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
from src.telegram_push import split_message, MAX_MESSAGE_LENGTH


def test_split_message_oversized_no_double_newline():
    """\n\n이 없는 4096자 초과 단락도 4096자 이하로 안전하게 분할된다"""
    oversized_text = "A" * 5000
    chunks = split_message(oversized_text)

    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= MAX_MESSAGE_LENGTH

    oversized_lines = ("B" * 3000) + "\n" + ("C" * 3000)
    chunks_lines = split_message(oversized_lines)

    assert len(chunks_lines) == 2
    for c in chunks_lines:
        assert len(c) <= MAX_MESSAGE_LENGTH
from src.keyword_boost import load_keywords

def test_urgent_keywords_configuration():
    """config/keywords.yaml에 urgent_keywords 항목이 올바르게 정의되어 있는지 검증"""
    settings = load_keywords()
    urgent = settings.get("urgent_keywords", [])
    assert isinstance(urgent, list)
    assert "중대재해" in urgent
    assert "탄핵" in urgent
from src.main import is_urgent_article


def test_is_urgent_article_conditions():
    """is_urgent_article 조건 검증 (5점 항상 알림, 4점+키워드 알림, 4점 미키워드 및 3점 미발송)"""
    keywords = ["중대재해", "탄핵"]

    # 1. 5점 기사는 키워드 없어도 항상 True
    a5 = Article(title="보통 뉴스", url="u1", source="s1", importance=5)
    assert is_urgent_article(a5, keywords) is True

    # 2. 4점 기사 + 속보 키워드 -> True
    a4_kw = Article(title="현장 중대재해 발생", url="u2", source="s2", importance=4)
    assert is_urgent_article(a4_kw, keywords) is True

    # 3. 4점 기사 + 키워드 없음 -> False
    a4_nokw = Article(title="지방의회 일상 회의", url="u3", source="s3", importance=4)
    assert is_urgent_article(a4_nokw, keywords) is False

    # 4. 3점 이하 기사 + 속보 키워드 -> False (4점 이상 필수)
    a3_kw = Article(title="중대재해 토론회 개최", url="u4", source="s4", importance=3)
    assert is_urgent_article(a3_kw, keywords) is False
