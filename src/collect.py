"""
RSS 뉴스 수집 모듈

config/feeds.yaml에 정의된 RSS 피드에서 최근 24시간 내 뉴스를 수집한다.
"""

import hashlib
import re
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

import feedparser
import httpx
import yaml
from loguru import logger


@lru_cache(maxsize=1)
def _legacy_ssl_context() -> ssl.SSLContext:
    """구형 서버용 SSL 컨텍스트 (보안 레벨 1)

    민중의소리(vop.co.kr)처럼 낡은 1024비트 DH 키를 쓰는 서버는
    최신 OpenSSL이 'DH_KEY_TOO_SMALL' 오류로 연결을 거부한다.
    보안 레벨을 1로 낮춰 이 서버에 한해 연결을 허용한다.
    (feeds.yaml에서 legacy_ssl: true 로 지정한 피드에만 사용)
    """
    ctx = ssl.create_default_context()
    ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    return ctx


@dataclass
class Article:
    """뉴스 기사 데이터 모델"""

    # 필수
    title: str
    url: str
    source: str  # 언론사 이름

    # RSS에서 가져오는 정보
    summary: str = ""  # RSS 요약문
    published_at: Optional[datetime] = None
    collected_at: datetime = field(default_factory=datetime.now)

    # URL 해시 (중복 체크용)
    url_hash: str = ""

    # 분류 결과 (classify.py에서 채움)
    category: str = ""
    importance: int = 0
    scope: str = ""
    response_needed: str = "none"  # high, medium, none (classify.py에서 채움)

    # 요약 결과 (summarize.py에서 채움)
    ai_summary: str = ""
    ai_comment: str = ""

    # 본문 미확인 플래그 (classify/summarize에서 세팅)
    low_content: bool = False

    # 분류 성공 여부 (classify.py에서 세팅)
    # AI 분류가 실제로 성공하면 True, API/파싱 오류로 기본값 처리되면 False.
    # 수집 단계 seen 기록 시 성공한 기사만 기록해 장애 기사 복구를 가능하게 한다.
    classified_ok: bool = False

    # 이슈 경과 추적 (issue_tracker.py에서 채움)
    # 예: "📋 3일째 진행 중 (이번 주 12건)"
    ongoing_context: str = ""

    def __post_init__(self):
        """URL 해시 자동 생성"""
        if not self.url_hash and self.url:
            self.url_hash = hashlib.sha256(self.url.encode()).hexdigest()


# ── 피드 설정 파일 경로 ─────────────────────────
FEEDS_PATH = Path(__file__).parent.parent / "config" / "feeds.yaml"


def load_feeds(feeds_path: Optional[Path] = None) -> list[dict]:
    """feeds.yaml에서 피드 목록 로드

    Returns:
        [{"name": "경남도민일보", "url": "https://...", "scope": "gyeongnam"}, ...]
    """
    path = feeds_path or FEEDS_PATH

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    feeds = []
    for group_name, feed_list in config.items():
        if not isinstance(feed_list, list):
            continue
        for feed in feed_list:
            if "url" in feed:
                feeds.append(feed)

    logger.info(f"피드 {len(feeds)}개 로드 완료")
    return feeds


def _parse_date(entry) -> Optional[datetime]:
    """feedparser 엔트리에서 날짜 추출"""
    # feedparser가 파싱한 구조화된 날짜 사용
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6])
        except (TypeError, ValueError):
            pass

    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        try:
            return datetime(*entry.updated_parsed[:6])
        except (TypeError, ValueError):
            pass

    return None


def _clean_html(text: str) -> str:
    """HTML 태그·엔티티 제거, 공백 정리"""
    import html
    text = re.sub(r"<[^>]+>", "", text)   # 태그 제거
    text = html.unescape(text)            # &apos; &quot; &nbsp; 등 디코딩
    text = re.sub(r"\s+", " ", text)      # 연속 공백 정리
    return text.strip()


def collect_from_feed(
    feed_config: dict,
    hours: int = 24,
    client: Optional[httpx.Client] = None,
) -> list[Article]:
    """단일 RSS 피드에서 기사 수집

    Args:
        feed_config: {"name": "...", "url": "...", "scope": "..."}
        hours: 최근 N시간 이내 기사만 수집
        client: httpx 클라이언트 (재사용)

    Returns:
        수집된 Article 리스트
    """
    name = feed_config["name"]
    url = feed_config["url"]
    cutoff = datetime.now() - timedelta(hours=hours)

    articles = []

    try:
        if feed_config.get("legacy_ssl"):
            # 낡은 SSL을 쓰는 구형 서버(예: 민중의소리)는 보안 레벨을 낮춘
            # 전용 컨텍스트로 직접 요청한다. 공용 client는 기본 SSL이라 거부당한다.
            response = httpx.get(
                url,
                timeout=15,
                follow_redirects=True,
                headers={"User-Agent": "clipboard055/1.0"},
                verify=_legacy_ssl_context(),
            )
            content = response.content
        elif client:
            response = client.get(url, timeout=15)
            content = response.content
        else:
            response = httpx.get(url, timeout=15, follow_redirects=True)
            content = response.content

        feed = feedparser.parse(content)

        for entry in feed.entries:
            title = _clean_html(entry.get("title", ""))
            link = entry.get("link", "")
            summary = _clean_html(
                entry.get("summary", entry.get("description", ""))
            )
            pub_date = _parse_date(entry)

            # 빈 제목이나 링크는 스킵
            if not title or not link:
                continue

            # 시간 필터링
            if pub_date and pub_date < cutoff:
                continue

            article = Article(
                title=title,
                url=link,
                source=name,
                summary=summary[:500] if summary else "",
                published_at=pub_date,
            )
            articles.append(article)

        logger.info(f"[{name}] {len(articles)}건 수집")

    except Exception as e:
        # 피드 하나 실패해도 전체 파이프라인은 계속 (graceful degradation)
        logger.warning(f"[{name}] 수집 실패: {e}")

    return articles


def collect_all(hours: int = 24, feeds_path: Optional[Path] = None) -> list[Article]:
    """모든 피드에서 기사 수집

    Args:
        hours: 최근 N시간 이내 기사만
        feeds_path: feeds.yaml 경로 (테스트용)

    Returns:
        중복 URL 제거된 전체 Article 리스트
    """
    feeds = load_feeds(feeds_path)

    all_articles = []
    with httpx.Client(
        headers={"User-Agent": "clipboard055/1.0"},
        follow_redirects=True,
    ) as client:
        for feed_config in feeds:
            articles = collect_from_feed(feed_config, hours=hours, client=client)
            all_articles.extend(articles)

    # URL 기준 중복 제거 (같은 기사가 여러 피드에 나올 수 있음)
    seen_urls = set()
    unique = []
    for article in all_articles:
        if article.url not in seen_urls:
            seen_urls.add(article.url)
            unique.append(article)

    logger.info(f"전체 수집: {len(all_articles)}건 → 중복 제거 후 {len(unique)}건")
    return unique
