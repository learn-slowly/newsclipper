"""
섹션 구성 모듈

분류된 기사를 9개 섹션으로 조직한다.
같은 이슈를 다룬 기사는 하나의 그룹으로 묶어서 보여준다.
Phase 1에서는 5개 섹션만 활성화 (노동, 기후, 경남정치, 정의당경남, 정의당전국).
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from loguru import logger

from src.collect import Article


# 같은 이슈로 묶는 임계값
TITLE_SIMILARITY_THRESHOLD = 0.45  # 제목 문자열 유사도만으로 묶기
KEYWORD_OVERLAP_MIN = 2            # 키워드 겹침 최소 개수 (이 이상이면 같은 이슈)

# 키워드 추출 시 무시할 일반적인 단어
_STOPWORDS = {
    # 조사·접속사
    "의", "에", "을", "를", "이", "가", "은", "는", "와", "과", "도", "로", "서",
    "한", "된", "및", "등", "위", "중", "후", "전", "대", "더", "것", "수", "만",
    # 기사에서 흔한 일반 동사·명사
    "했다", "한다", "밝혔다", "전했다", "보도", "관련", "기자", "뉴스",
    "발표", "��장", "지적", "설명", "강조", "예정", "계획", "결과",
    "확인", "조사", "논의", "이후", "시작", "현재", "올해", "지난",
    # 정치 기사에서 너무 흔한 단어 (이것만으로 같은 이슈 판단 방지)
    "후보", "경남", "경상남도", "부산", "울산", "지역", "정부", "국회",
}


@dataclass
class ArticleGroup:
    """같은 이슈를 다룬 기사 묶음"""

    primary: Article  # 대표 기사 (중요도 최고, 요약 있는 것 우선)
    related: list[Article] = field(default_factory=list)  # 관련 기사들

    @property
    def all_articles(self) -> list[Article]:
        return [self.primary] + self.related


@dataclass
class Section:
    """브리핑 섹션"""

    number: int
    name: str
    emoji: str
    articles: list[Article]
    groups: list[ArticleGroup] = field(default_factory=list)


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
            groups = _group_similar(matched)
            sections.append(Section(
                number=number,
                name=name,
                emoji=emoji,
                articles=matched,
                groups=groups,
            ))

    return sections


def _extract_keywords(text: str) -> set[str]:
    """텍스트에서 의미 있는 키워드 추출 (2글자 이상, 불용어 제외)"""
    words = re.findall(r"[가-힣]{2,}|[a-zA-Z]{2,}|[0-9]+", text)
    return {w for w in words if w not in _STOPWORDS}


def _is_same_issue(a: Article, b: Article) -> bool:
    """두 기사가 같은 이슈인지 판단

    다음 중 하나라도 만족하면 같은 이슈:
    1. 제목 문자열 유사도 >= 0.4
    2. 키워드 겹침 >= 2개
    """
    # 1. 제목 유사도 체크
    title_sim = SequenceMatcher(None, a.title, b.title).ratio()
    if title_sim >= TITLE_SIMILARITY_THRESHOLD:
        return True

    # 2. 키워드 겹침 체크
    kw_a = _extract_keywords(f"{a.title} {a.summary}")
    kw_b = _extract_keywords(f"{b.title} {b.summary}")
    overlap = kw_a & kw_b

    if len(overlap) >= KEYWORD_OVERLAP_MIN:
        return True

    return False


def _group_similar(articles: list[Article]) -> list[ArticleGroup]:
    """같은 이슈를 다룬 기사를 그룹으로 묶기

    중요도 높은 순으로 이미 정렬된 상태에서,
    제목 유사도 + 키워드 겹침을 종합하여 같은 이슈인지 판단한다.
    """
    groups: list[ArticleGroup] = []

    for article in articles:
        matched_group = None

        for group in groups:
            # 그룹 내 아무 기사와 같은 이슈면 매칭
            for member in group.all_articles:
                if _is_same_issue(article, member):
                    matched_group = group
                    break
            if matched_group:
                break

        if matched_group:
            matched_group.related.append(article)
        else:
            groups.append(ArticleGroup(primary=article))

    grouped_count = sum(1 for g in groups if g.related)
    if grouped_count:
        logger.info(f"  이슈 묶음: {grouped_count}개 그룹에 관련 기사 병합")

    return groups
