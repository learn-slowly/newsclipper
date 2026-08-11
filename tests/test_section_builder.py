"""section_builder 모듈 단위 테스트

발송 기준(중요도 필터)과 연대정당 섹션 활성화를 검증한다.
2026-07-03 품질 개선: 분량 폭주 방지(min_importance)와
노동당·녹색당·진보당 섹션(9번) 활성화가 핵심이다.
"""

from src.collect import Article
from src.section_builder import PHASE1_ACTIVE, build_sections, is_sendable


def _article(title: str, category: str, importance: int, scope: str = "national") -> Article:
    a = Article(title=title, url=f"http://example.com/{title}", source="테스트", summary="요약")
    a.category = category
    a.importance = importance
    a.scope = scope
    return a


def test_중요도_기준_미달_기사는_섹션에서_제외():
    """min_importance보다 낮은 기사는 발송되지 않는다"""
    articles = [
        _article("중요한 노동 기사", "labor", 4),
        _article("덜 중요한 노동 기사", "labor", 3),
        _article("참고용 노동 기사", "labor", 2),
    ]
    sections = build_sections(articles, active_sections={1}, min_importance=4)

    assert len(sections) == 1
    assert [a.title for a in sections[0].articles] == ["중요한 노동 기사"]


def test_전부_기준_미달이면_빈_섹션_생략():
    """모든 기사가 기준 미달이면 섹션 자체가 만들어지지 않는다"""
    articles = [_article("참고용 기사", "labor", 2)]
    sections = build_sections(articles, active_sections={1}, min_importance=4)

    assert sections == []


def test_연대정당_섹션_활성화():
    """섹션 9(노동당·녹색당·진보당)가 Phase 1 활성 목록에 포함된다"""
    assert 9 in PHASE1_ACTIVE

    articles = [_article("진보당 도의원 발의", "allied_parties", 4)]
    sections = build_sections(articles, active_sections=PHASE1_ACTIVE, min_importance=4)

    assert len(sections) == 1
    assert sections[0].number == 9
    assert "진보당" in sections[0].name



def test_발송_불가_기사는_요약_대상에서_제외():
    """is_sendable — 꺼진 섹션·점수 미달·other는 요약하지 않는다 (비용 절감)

    요약(Sonnet) 단계에서 build_sections와 같은 기준으로 걸러내는지 검증한다.
    꺼진 섹션(3·4·5) 기사는 점수가 높아도 False → 요약 비용 절약.
    """
    # 활성 섹션(labor) 4점 → True
    a_labor = _article("노동 기사", "labor", 4, "national")
    assert is_sendable(a_labor, active_sections=PHASE1_ACTIVE, min_importance=4)

    # 꺼진 섹션(gender_minority) 5점 → False (요약 안 함)
    a_gender = _article("여성 기사", "gender_minority", 5, "national")
    assert not is_sendable(a_gender, active_sections=PHASE1_ACTIVE, min_importance=4)

    # 점수 미달(labor 3점) → False
    a_low = _article("덜 중요 노동", "labor", 3, "national")
    assert not is_sendable(a_low, active_sections=PHASE1_ACTIVE, min_importance=4)

    # other 카테고리 4점 → 어떤 섹션에도 안 들음 → False
    a_other = _article("잡 기사", "other", 4, "national")
    assert not is_sendable(a_other, active_sections=PHASE1_ACTIVE, min_importance=4)

    # 정의당 경남(justice_party + gyeongnam) 4점 → 섹션 7 → True
    a_justice_gn = _article("정의당 경남", "justice_party", 4, "gyeongnam")
    assert is_sendable(a_justice_gn, active_sections=PHASE1_ACTIVE, min_importance=4)

    # 정의당 both 스코프 → 섹션 7(경남)에 들음 → True
    a_justice_both = _article("정의당 전국+경남", "justice_party", 4, "both")
    assert is_sendable(a_justice_both, active_sections=PHASE1_ACTIVE, min_importance=4)