"""대응 필요도 + 중앙당 논평 매칭 + 브리핑 표시 테스트"""

import pytest
from src.collect import Article
from src.section_builder import ArticleGroup, Section
from src.jpnews_reader import Statement, find_matching_statement
from src.telegram_push import _format_group, _format_section, format_briefing


# ── 헬퍼 ──

def _art(title, url="https://test.com/1", category="labor", importance=5,
         scope="gyeongnam", response_needed="none"):
    a = Article(title=title, url=url, source="test")
    a.category = category
    a.importance = importance
    a.scope = scope
    a.response_needed = response_needed
    a.ai_comment = "코멘트"
    return a


STMTS = [
    Statement(date="2026-08-10", type="성명",
              title="HL만도 위험의 외주화 책임 인정하라", topic="labor",
              link="https://t.me/justicekr/100"),
    Statement(date="2026-08-05", type="논평",
              title="기후위기 대응 촉구", topic="climate",
              link="https://t.me/justicekr/101"),
    Statement(date="2026-07-20", type="성명",
              title="노동자 산재 즉각 승인하라", topic="labor",
              link="https://t.me/justicekr/102"),
]


# ── 매칭 ──

def test_high_with_matching_statement():
    """대응 필요(high) + 관련 논평 → 📢 + 📌 표시"""
    art = _art("HL만도 하청 노동자 사망사고 위험 외주화 책임", url="u1", response_needed="high")
    match = find_matching_statement(STMTS, "labor", art.title)
    assert match is not None
    assert "HL만도" in match.title

    text = _format_group(ArticleGroup(primary=art), statement=match)
    assert "📢" in text
    assert "📌 참고 논평:" in text
    assert "t.me/justicekr/100" in text


def test_high_without_statement():
    """대응 필요(high) + 논평 없음 → 📢 + '없음' 표시"""
    art = _art("청년 주거 문제", url="u2", category="youth", response_needed="high")
    match = find_matching_statement(STMTS, "youth", art.title)
    assert match is None

    text = _format_group(ArticleGroup(primary=art))
    assert "📢" in text
    assert "중앙당 참고 논평 없음" in text
    assert "도당 자체 대응 검토" in text


def test_medium_no_display():
    """medium → 📢/📌 없어야 함"""
    art = _art("노동 통계", url="u3", response_needed="medium")
    text = _format_group(ArticleGroup(primary=art))
    assert "📢" not in text
    assert "📌" not in text


def test_none_no_display():
    """none → 📢/📌 없어야 함"""
    art = _art("일반 뉴스", url="u4", importance=3, response_needed="none")
    text = _format_group(ArticleGroup(primary=art))
    assert "📢" not in text
    assert "📌" not in text


def test_per_article_matching():
    """같은 카테고리 다른 기사 → 키워드에 따라 다른 논평"""
    a = _art("HL만도 위험 외주화 사고", url="u5a", response_needed="high")
    b = _art("청년 노동자 산재 승인 지연", url="u5b", response_needed="high")
    ma = find_matching_statement(STMTS, "labor", a.title)
    mb = find_matching_statement(STMTS, "labor", b.title)
    assert ma is not None and "HL만도" in ma.title
    assert mb is not None and "산재" in mb.title
    assert ma.link != mb.link


def test_keyword_threshold_rejects():
    """키워드 겹침 부족 → 매칭 거부"""
    art = _art("플랫폼 배달 처우 개선", url="u6", response_needed="high")
    match = find_matching_statement(STMTS, "labor", art.title)
    assert match is None


# ── 섹션 포맷 ──

def test_section_with_groups():
    """섹션 포맷(그룹 있음) — 기사별 매칭"""
    art1 = _art("HL만도 위험 외주화", url="u7a", response_needed="high")
    art2 = _art("노동 통계", url="u7b", response_needed="medium")
    m1 = find_matching_statement(STMTS, "labor", art1.title)

    sec = Section(number=1, name="노동", emoji="💼", articles=[art1, art2])
    sec.groups = [ArticleGroup(primary=art1), ArticleGroup(primary=art2)]
    text = _format_section(sec, {art1.url: m1})
    assert text.count("📌 참고 논평:") == 1


def test_section_without_groups():
    """섹션 포맷(그룹 없음) — 정상 동작"""
    art = _art("일반 뉴스", url="u8", importance=3)
    sec = Section(number=2, name="기후", emoji="🌱", articles=[art])
    sec.groups = []
    text = _format_section(sec, {})
    assert "일반 뉴스" in text
    assert "📌" not in text


def test_section_without_groups_high_with_match():
    """섹션(그룹 없음) + high 기사 + 논평 있음 → 📢 + 📌"""
    art = _art("HL만도 위험 외주화", url="u8a", response_needed="high")
    m = find_matching_statement(STMTS, "labor", art.title)
    sec = Section(number=2, name="노동", emoji="💼", articles=[art])
    sec.groups = []
    text = _format_section(sec, {art.url: m})
    assert "📢" in text
    assert "📌 참고 논평:" in text


def test_section_without_groups_high_no_match():
    """섹션(그룹 없음) + high 기사 + 논평 없음 → 📢 + '없음'"""
    art = _art("청년 주거 문제", url="u8b", category="youth", response_needed="high")
    sec = Section(number=2, name="청년", emoji="🎓", articles=[art])
    sec.groups = []
    text = _format_section(sec, {})
    assert "📢" in text
    assert "중앙당 참고 논평 없음" in text


# ── 브리핑 전체 ──

def test_format_briefing_no_map():
    """format_briefing — statement_map 없이 호환"""
    art = _art("HL만도 사고", url="u9", response_needed="high")
    sec = Section(number=1, name="노동", emoji="💼", articles=[art])
    sec.groups = [ArticleGroup(primary=art)]
    text = format_briefing([sec], 100)
    assert "📰" in text


def test_format_briefing_empty_map_shows_none():
    """format_briefing — 빈 map이면 high 기사에 '없음' 표시"""
    art = _art("HL만도 사고", url="u10", response_needed="high")
    sec = Section(number=1, name="노동", emoji="💼", articles=[art])
    sec.groups = [ArticleGroup(primary=art)]
    text = format_briefing([sec], 100, {})
    assert "중앙당 참고 논평 없음" in text


def test_format_briefing_with_match():
    """format_briefing — 매칭 있으면 논평 표시"""
    art = _art("HL만도 위험 외주화", url="u11", response_needed="high")
    m = find_matching_statement(STMTS, "labor", art.title)
    sec = Section(number=1, name="노동", emoji="💼", articles=[art])
    sec.groups = [ArticleGroup(primary=art)]
    text = format_briefing([sec], 100, {art.url: m})
    assert "📌 참고 논평:" in text
    assert "HL만도" in text
