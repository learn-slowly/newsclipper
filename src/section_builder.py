"""
섹션 구성 모듈

분류된 기사를 9개 섹션으로 조직한다.
Phase 1에서는 5개 섹션만 활성화 (노동, 기후, 경남정치, 정의당경남, 정의당전국).
"""

from dataclasses import dataclass

from src.collect import Article


@dataclass
class Section:
    """브리핑 섹션"""

    number: int
    name: str
    emoji: str
    articles: list[Article]


# ── 9개 섹션 정의 ────────────────────────────
# (번호, 이름, 이모지, 카테고리, 스코프 필터)
SECTION_DEFS = [
    (1, "노동·파업·산재", "💼", "labor", None),
    (2, "기후·환경", "🌱", "climate", None),
    (3, "여성·소수자", "⚧", "gender_minority", None),
    (4, "청년·청소년", "🎓", "youth", None),
    (5, "복지·돌봄", "🤝", "welfare_care", None),
    (6, "경남 지역 정치·선거", "🗳", "regional_politics", "gyeongnam"),
    (7, "정의당 — 경남", "🟡", "justice_party", "gyeongnam"),
    (8, "정의당 — 전국", "🟨", "justice_party", "national"),
    (9, "노동당·녹색당 동향", "🤝🌿", "allied_parties", None),
]

# Phase 1 활성화 섹션 번호
PHASE1_ACTIVE = {1, 2, 6, 7, 8}


def build_sections(
    articles: list[Article],
    active_sections: set[int] | None = None,
) -> list[Section]:
    """기사를 섹션별로 분류

    Args:
        articles: 분류 완료된 기사 리스트
        active_sections: 활성화할 섹션 번호 (None이면 전체)

    Returns:
        기사가 있는 섹션만 반환 (빈 섹션은 생략)
    """
    active = active_sections if active_sections is not None else set(range(1, 10))

    sections = []

    for number, name, emoji, category, scope_filter in SECTION_DEFS:
        if number not in active:
            continue

        # 카테고리 매칭
        matched = [a for a in articles if a.category == category]

        # 스코프 필터 적용
        if scope_filter == "gyeongnam":
            # 경남 또는 both만
            matched = [a for a in matched if a.scope in ("gyeongnam", "both")]
        elif scope_filter == "national":
            # 전국만 (both 제외 — both는 경남 섹션에서 다룸)
            matched = [a for a in matched if a.scope == "national"]
        # None이면 스코프 필터 없음 (전국+지역 모두 포함)

        # 중요도 높은 순 정렬
        matched.sort(key=lambda a: a.importance, reverse=True)

        # 빈 섹션 생략
        if matched:
            sections.append(Section(
                number=number,
                name=name,
                emoji=emoji,
                articles=matched,
            ))

    return sections
