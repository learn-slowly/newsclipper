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
    """is_urgent_article 조건 검증 (4점 이상 + 긴급 키워드 필수, 4점 미만 또는 키워드 없으면 미발송)"""
    keywords = ["중대재해", "탄핵"]

    # 1. 5점 기사라도 키워드 없으면 False (지역 가산점으로 5점이 된 일반 뉴스 차단)
    a5 = Article(title="보통 뉴스", url="u1", source="s1", importance=5)
    assert is_urgent_article(a5, keywords) is False

    # 2. 5점 기사 + 속보 키워드 -> True
    a5_kw = Article(title="현장 중대재해 발생", url="u1b", source="s1", importance=5)
    assert is_urgent_article(a5_kw, keywords) is True

    # 3. 4점 기사 + 속보 키워드 -> True
    a4_kw = Article(title="현장 중대재해 발생", url="u2", source="s2", importance=4)
    assert is_urgent_article(a4_kw, keywords) is True

    # 4. 4점 기사 + 키워드 없음 -> False
    a4_nokw = Article(title="지방의회 일상 회의", url="u3", source="s3", importance=4)
    assert is_urgent_article(a4_nokw, keywords) is False

    # 5. 3점 이하 기사 + 속보 키워드 -> False (4점 이상 필수)
    a3_kw = Article(title="중대재해 토론회 개최", url="u4", source="s4", importance=3)
    assert is_urgent_article(a3_kw, keywords) is False


import pytest
import src.scrape as scrape_module
import src.main as main_module
from src.main import run_alert_pipeline


async def _send_true(*args, **kwargs):
    return True


async def _send_false(*args, **kwargs):
    return False


def _patch_pipeline(monkeypatch, tmp_path, articles, send_fn):
    """run_alert_pipeline의 외부 의존성을 목으로 대체하고 임시 DB를 사용하게 한다"""
    from src.storage import Storage

    db_path = tmp_path / "test_alert.db"
    storage = Storage(db_path)
    monkeypatch.setattr(main_module, "Storage", lambda: Storage(db_path))

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "test")

    monkeypatch.setattr(main_module, "load_feeds", lambda: [])
    monkeypatch.setattr(scrape_module, "load_scrape_config", lambda: [])
    monkeypatch.setattr(main_module, "collect_all", lambda hours=6: list(articles))
    monkeypatch.setattr(main_module, "scrape_all", lambda: [])
    monkeypatch.setattr(main_module, "deduplicate_similar", lambda a: a)
    monkeypatch.setattr(main_module, "prefilter_articles", lambda a, s: (a, 0))
    monkeypatch.setattr(main_module, "classify_articles", lambda a, k: (a, 0, 0))
    monkeypatch.setattr(main_module, "apply_keyword_boost", lambda a: a)
    monkeypatch.setattr(main_module, "apply_trusted_boost", lambda a, s: a)
    monkeypatch.setattr(main_module, "load_keywords", lambda: {"urgent_keywords": ["중대재해"]})
    monkeypatch.setattr(main_module, "attach_issue_context", lambda a, s: a)
    monkeypatch.setattr(main_module, "format_alert_message", lambda a: "alert")
    monkeypatch.setattr(main_module, "send_telegram", send_fn)

    return storage


def _urgent_article(url: str) -> Article:
    return Article(
        title="경남 창원 중대재해 발생",
        url=url,
        source="도민일보",
        importance=5,
        classified_ok=True,
    )


@pytest.mark.asyncio
async def test_run_alert_pipeline_success_marks_seen(monkeypatch, tmp_path):
    """속보 발송 성공 시 정기 브리핑 장부(seen)에도 기록되어 다음 브리핑 중복을 막는다"""
    art = _urgent_article("https://example.com/urgent-success")
    storage = _patch_pipeline(monkeypatch, tmp_path, [art], _send_true)

    await run_alert_pipeline()

    assert art.url_hash in storage.get_seen_hashes()
    assert art.url_hash in storage.get_alert_seen_hashes()


@pytest.mark.asyncio
async def test_run_alert_pipeline_failure_skips_seen(monkeypatch, tmp_path):
    """속보 발송 실패 시 정기 브리핑 장부(seen)에 기록되지 않아 다음 점검에서 재시도 가능하다"""
    art = _urgent_article("https://example.com/urgent-fail")
    storage = _patch_pipeline(monkeypatch, tmp_path, [art], _send_false)

    await run_alert_pipeline()

    assert art.url_hash not in storage.get_seen_hashes()
    assert art.url_hash not in storage.get_alert_seen_hashes()
