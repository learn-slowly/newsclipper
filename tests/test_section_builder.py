"""section_builder 모듈 단위 테스트

발송 기준(중요도 필터)과 연대정당 섹션 활성화를 검증한다.
2026-07-03 품질 개선: 분량 폭주 방지(min_importance)와
노동당·녹색당·진보당 섹션(9번) 활성화가 핵심이다.
"""

from src.collect import Article
from src.section_builder import PHASE1_ACTIVE, build_sections


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



def test_같은_사건_기사는_하나로_묶임():
    """여러 언론사가 같은 사건을 보도하면 제목이 닮아 한 묶음이 된다

    대표 기사 1건 + 관련 기사 나머지. 발송 건수는 묶음 수로 센다.
    """
    articles = [
        _article("창원 시내버스 사전조정에서 임금협상 타결", "labor", 5),
        _article("창원 시내버스 노사, 사전조정서 임금협상 타결 1.9% 인상", "labor", 4),
        _article("우체국 택배노동자 폭염 속 겸배 중단 촉구", "labor", 4),
    ]
    sections = build_sections(articles, active_sections={1}, min_importance=4)

    assert len(sections) == 1
    # 같은 사건 2건이 묶여 총 2묶음 (창원버스, 우체국택배)
    assert len(sections[0].groups) == 2
    assert len(sections[0].articles) == 3

    버스묶음 = sections[0].groups[0]
    assert "창원 시내버스" in 버스묶음.primary.title
    assert len(버스묶음.related) == 1


def test_다른_사건은_묶이지_않음():
    """주제가 비슷해도 사건이 다르면 따로 보낸다 (제목만으로 판단)"""
    articles = [
        _article("금속노조 현대차 원청 사용자성 인정 요구", "labor", 4),
        _article("폭염 속 고공농성 택시노동자 간주근로제 촉구", "labor", 4),
    ]
    sections = build_sections(articles, active_sections={1}, min_importance=4)

    assert len(sections[0].groups) == 2


# 서로 안 묶이는 실제 기사풍 제목 (서로 간 제목 유사도 최대 0.38 < 0.45)
_별개_사건 = [
    "금속노조 현대차 원청 사용자성 인정 요구",
    "폭염 속 고공농성 택시노동자 간주근로제 촉구",
    "우체국 택배노동자 겸배 중단 촉구 기자회견",
    "한화오션 중대재해 유가족 진상규명 요구",
    "쿠팡 물류센터 야간노동 실태조사 발표",
    "건설노조 임금체불 집단진정 접수",
]


def test_분량_상한을_넘지_않음():
    """max_items를 넘으면 중요도 높은 순으로 잘라낸다"""
    # 앞 3건은 5점, 뒤 3건은 4점
    articles = [
        _article(title, "labor", 5 if i < 3 else 4)
        for i, title in enumerate(_별개_사건)
    ]
    sections = build_sections(
        articles, active_sections={1}, min_importance=4, max_items=3
    )

    총묶음 = sum(len(s.groups) for s in sections)
    assert 총묶음 == 3
    # 중요도 5점짜리가 우선 남는다
    assert all(g.primary.importance == 5 for s in sections for g in s.groups)


def test_상한보다_적으면_그대로_발송():
    """묶음 수가 상한보다 적으면 아무것도 잘리지 않는다"""
    articles = [_article(t, "labor", 4) for t in _별개_사건[:2]]
    sections = build_sections(
        articles, active_sections={1}, min_importance=4, max_items=30
    )

    assert sum(len(s.groups) for s in sections) == 2


def test_섹션당_상한이_소량에도_적용됨():
    """전체가 max_items 이하여도 한 섹션이 max_per_section을 넘지 않는다"""
    # 노동 15건(전체 상한 30 이하) — max_per_section=5이면 5건만 남아야
    articles = [_article(t, "labor", 4) for t in _별개_사건[:6]]
    sections = build_sections(
        articles, active_sections={1}, min_importance=4,
        max_items=30, max_per_section=5,
    )

    총묶음 = sum(len(s.groups) for s in sections)
    assert 총묶음 == 5  # 6건 중 5건만


def test_최소보장이_상한초과_안하고_모든섹션_최소1건():
    """active_sections × min_per_section > max_items여도 총량은 max_items 이내이고,
    후보가 있는 모든 섹션이 최소 1건은 받는다 (순서 편향 없음)."""
    # 2섹션(노동·기후) × 최소 20 = 40 > max_items 3
    articles = (
        [_article(t, "labor", 4) for t in _별개_사건[:3]]
        + [_article("경남 폭염 가뭄 비상 대응 회의 소집", "climate", 4)]
    )
    sections = build_sections(
        articles, active_sections={1, 2}, min_importance=4,
        max_items=3, min_per_section=20,
    )

    총묶음 = sum(len(s.groups) for s in sections)
    assert 총묶음 <= 3
    # 후보가 있는 두 섹션 모두 최소 1건은 받아야 한다
    섹션이름 = {s.name for s in sections}
    assert "노동·파업·산재" in 섹션이름, "노동 섹션이 빠짐"
    assert "기후·환경" in 섹션이름, "기후 섹션이 빠짐"


def test_최소보장이_최대보다_크면_최대로_내림():
    """min_per_section > max_per_section이면 max_per_section으로 자른다"""
    articles = [_article(t, "labor", 4) for t in _별개_사건[:6]]
    sections = build_sections(
        articles, active_sections={1}, min_importance=4,
        max_items=30, min_per_section=10, max_per_section=2,
    )

    총묶음 = sum(len(s.groups) for s in sections)
    assert 총묶음 == 2  # max_per_section이 이김


def test_같은_점수_기사가_섹션간_균등_배분():
    """같은 중요도의 기사가 여러 섹션에 있으면 한쪽이 독식하지 않는다

    2단계(풀 채우기)에서 동점 편향을 방지하는 돌아가며 배분 검증.
    노동 5건 + 기후 5건 전부 4점이고 max_items=6이면 3:3이어야 한다.
    """
    articles = [
        _article("금속노조 현대차 원청 사용자성 인정 요구", "labor", 4),
        _article("폭염 속 고공농성 택시노동자 간주근로제 촉구", "labor", 4),
        _article("우체국 택배노동자 겸배 중단 촉구 기자회견", "labor", 4),
        _article("한화오션 중대재해 유가족 진상규명 요구", "labor", 4),
        _article("쿠팡 물류센터 야간노동 실태조사 발표", "labor", 4),
        _article("경남 폭염 가뭄 비상 대응 회의 소집", "climate", 4),
        _article("낙동강 녹조 발생 경남 취수원 비상 상황", "climate", 4),
        _article("기후보험 개발 운영 활성화 법안 의결 발표", "climate", 4),
        _article("경남 전 해역 고수온 특보 확대 발령 조치", "climate", 4),
        _article("태양광 발전 폐패널 처리 기준 마련 착수", "climate", 4),
    ]
    sections = build_sections(
        articles, active_sections={1, 2}, min_importance=4,
        max_items=6, min_per_section=1, max_per_section=99,
    )

    노동 = next((len(s.groups) for s in sections if "노동" in s.name), 0)
    기후 = next((len(s.groups) for s in sections if "기후" in s.name), 0)
    assert 노동 + 기후 == 6
    assert abs(노동 - 기후) <= 1, f"동점 편향: 노동 {노동} vs 기후 {기후}"