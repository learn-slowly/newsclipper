"""
섹션 구성 모듈

분류된 기사를 9개 섹션으로 조직한다.
같은 사건을 다룬 여러 언론사 기사는 하나의 묶음으로 합쳐서 보여준다.
Phase 1에서는 6개 섹션 활성화 (노동, 기후, 경남정치, 정의당경남, 정의당전국, 연대정당).
"""

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from loguru import logger

from src.collect import Article


# 같은 사건으로 묶는 제목 유사도 임계값
# 2026-08-11 실측: 같은 사건 0.53~0.68, 다른 사건 0.19~0.25 → 0.45가 안전한 경계.
# 이전에는 "키워드 2개 이상 겹침" 규칙도 있었으나, 같은 사건이 아니라 비슷한 주제까지
# 묶어버려(창원 시내버스 기사에 우체국 택배 기사가 붙는 식) 제거했다.
TITLE_SIMILARITY_THRESHOLD = 0.45


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
    (9, "노동당·녹색당·진보당 동향", "🤝🌿", "allied_parties", None),
]

# Phase 1 활성화 섹션 번호 (2026-07-03: 연대정당 섹션 9 활성화)
PHASE1_ACTIVE = {1, 2, 6, 7, 8, 9}

# 발송 기준 중요도 기본값 (keywords.yaml의 min_importance로 재정의 가능)
DEFAULT_MIN_IMPORTANCE = 4

# 회당 최대 발송 묶음 수 기본값 (keywords.yaml의 max_items로 재정의 가능)
DEFAULT_MAX_ITEMS = 30

# 섹션당 최소 보장 (이 건수만큼은 어떤 섹션이든 우선 채움, keywords.yaml의 min_per_section)
DEFAULT_MIN_PER_SECTION = 3

# 섹션당 최대 (한 섹션이 브리핑을 독식하지 않게, keywords.yaml의 max_per_section)
DEFAULT_MAX_PER_SECTION = 10


def _matches_section(article: Article, category: str, scope_filter: str | None) -> bool:
    """기사가 이 섹션에 들어가는 기사인지 판정 (카테고리 + 지역 범위)

    섹션 배치 규칙은 이 함수 한 곳에만 둔다.
    build_sections가 섹션마다 이 규칙으로 기사를 고른다.
    """
    if article.category != category:
        return False
    if scope_filter == "gyeongnam":
        # 경남 또는 both만
        return article.scope in ("gyeongnam", "both")
    if scope_filter == "national":
        # 전국만 (both 제외 — both는 경남 섹션에서 다룸)
        return article.scope == "national"
    # None이면 스코프 필터 없음 (전국+지역 모두 포함)
    return True


def build_sections(
    articles: list[Article],
    active_sections: set[int] | None = None,
    min_importance: int = DEFAULT_MIN_IMPORTANCE,
    max_items: int | None = DEFAULT_MAX_ITEMS,
    min_per_section: int = DEFAULT_MIN_PER_SECTION,
    max_per_section: int = DEFAULT_MAX_PER_SECTION,
) -> list[Section]:
    """기사를 섹션별로 조직하고, 같은 사건은 하나로 묶고, 분량을 제한한다

    순서:
    1. 발송 기준 점수 미달 기사 제외
    2. 섹션별로 배치 (카테고리 + 지역 범위)
    3. 같은 사건을 다룬 여러 언론사 기사를 하나의 묶음으로 합침
    4. 섹션별 최소 보장 + 섹션당 상한 + 전체 중요도순으로 max_items개만 남김

    Args:
        articles: 분류 완료된 기사 리스트
        active_sections: 활성화할 섹션 번호 (None이면 전체)
        min_importance: 이 점수 이상만 섹션에 포함
        max_items: 회당 최대 발송 묶음 수 (None이면 제한 없음)
        min_per_section: 섹션당 최소 보장 건수
        max_per_section: 섹션당 최대 건수

    Returns:
        기사가 있는 섹션만 반환 (빈 섹션은 생략)
    """
    active = active_sections if active_sections is not None else set(range(1, 10))

    # 1. 발송 기준 미달 기사 제외
    articles = [a for a in articles if a.importance >= min_importance]

    # 2~3. 섹션별 배치 + 같은 사건 묶기
    per_section: dict[int, list[ArticleGroup]] = {}

    for number, _name, _emoji, category, scope_filter in SECTION_DEFS:
        if number not in active:
            continue

        matched = [a for a in articles if _matches_section(a, category, scope_filter)]
        if not matched:
            continue

        matched.sort(key=lambda a: a.importance, reverse=True)
        per_section[number] = _group_similar(matched)

    # 4. 분량 제한
    if max_items is not None:
        kept = _cap_groups(per_section, max_items, min_per_section, max_per_section)
    else:
        kept = per_section

    # 섹션 객체 조립 (빈 섹션 생략)
    sections = []
    for number, name, emoji, _category, _scope_filter in SECTION_DEFS:
        groups = kept.get(number)
        if not groups:
            continue
        sections.append(Section(
            number=number,
            name=name,
            emoji=emoji,
            articles=[a for g in groups for a in g.all_articles],
            groups=groups,
        ))

    return sections


def _cap_groups(
    per_section: dict[int, list[ArticleGroup]],
    max_items: int,
    min_per_section: int = DEFAULT_MIN_PER_SECTION,
    max_per_section: int = DEFAULT_MAX_PER_SECTION,
) -> dict[int, list[ArticleGroup]]:
    """섹션별 최소 보장 + 섹션당 상한 + 나머지는 전체 중요도순

    1단계: 각 섹션에서 중요도 높은 순으로 min_per_section개를 가져간다.
           단, 전체 합이 max_items를 넘으면 거기서 멈춘다.
    2단계: 남은 자리를 전체 잔여에서 중요도순으로 채우되,
           한 섹션이 max_per_section을 넘지 않게 한다.

    어떤 설정 조합이든 총량은 max_items를 절대 넘지 않는다.
    전체가 max_items 이하여도 섹션당 상한(max_per_section)은 항상 적용된다.
    min_per_section > max_per_section이면 max_per_section으로 내린다.
    """
    total = sum(len(gs) for gs in per_section.values())

    # 모순 방지: 최소 보장이 섹션당 상한보다 크면 상한으로 내림
    effective_min = min(min_per_section, max_per_section)

    _sort_key = lambda g: (g.primary.importance, len(g.related))

    # 각 섹션을 중요도 내림차순 큐로 준비
    queues: dict[int, list[ArticleGroup]] = {
        n: sorted(gs, key=_sort_key, reverse=True)
        for n, gs in per_section.items()
    }

    # 1. 최소 보장 — 돌아가며 1건씩 (순서 편향 방지)
    # 모든 섹션이 1건씩 받은 뒤 2건, 3건... effective_min까지 반복.
    # 예산이 떨어지면 거기서 멈춘다.
    kept: dict[int, list[ArticleGroup]] = {n: [] for n in queues}
    budget = max_items

    for round_i in range(effective_min):
        if budget <= 0:
            break
        for n in queues:
            if budget <= 0:
                break
            if len(kept[n]) > round_i:
                continue  # 이미 이 라운드까지 받음
            if not queues[n]:
                continue  # 이 섹션에 더 줄 게 없음
            kept[n].append(queues[n].pop(0))
            budget -= 1

    # 남은 기사를 2단계 풀로 — 중요도별 묶음
    leftover: list[tuple[int, ArticleGroup]] = [
        (n, g) for n, q in queues.items() for g in q
    ]
    leftover.sort(key=lambda t: _sort_key(t[1]), reverse=True)

    # 2. 같은 중요도 안에서는 섹션을 돌아가며 하나씩 (순서 편향 방지)
    i = 0
    while i < len(leftover) and budget > 0:
        # 현재 중요도 레벨의 항목들을 섹션별로 분류
        level_key = _sort_key(leftover[i][1])
        by_sec: dict[int, list[ArticleGroup]] = {}
        start = i
        while i < len(leftover) and _sort_key(leftover[i][1]) == level_key:
            n, g = leftover[i]
            by_sec.setdefault(n, []).append(g)
            i += 1

        # 이 레벨 안에서 돌아가며 채움
        while budget > 0:
            took = False
            for n in list(by_sec):
                if budget <= 0:
                    break
                if not by_sec[n]:
                    continue
                if len(kept.get(n, [])) >= max_per_section:
                    by_sec[n] = []  # 이 섹션은 더 이상 받지 않음
                    continue
                kept.setdefault(n, []).append(by_sec[n].pop(0))
                budget -= 1
                took = True
            if not took:
                break

    sent = sum(len(v) for v in kept.values())
    dropped = total - sent
    logger.info(
        f"  분량 제한: {sent}건 발송 "
        f"({dropped}건 제외, 섹션당 최소 {effective_min}/최대 {max_per_section})"
    )
    return kept

def _is_same_issue(a: Article, b: Article) -> bool:
    """두 기사가 같은 사건을 다루는지 판단 (제목 유사도만 사용)

    여러 언론사가 같은 사건을 보도하면 제목이 비슷해진다.
    주제가 비슷하다는 이유로 묶으면 다른 사건이 섞이므로 제목만 본다.
    """
    return SequenceMatcher(None, a.title, b.title).ratio() >= TITLE_SIMILARITY_THRESHOLD


def _group_similar(articles: list[Article]) -> list[ArticleGroup]:
    """같은 이슈를 다룬 기사를 그룹으로 묶기

    중요도 높은 순으로 이미 정렬된 상태에서, 제목이 닮은 기사를 같은 묶음으로 합친다.
    먼저 온 기사(중요도 높은 쪽)가 대표가 된다.
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
