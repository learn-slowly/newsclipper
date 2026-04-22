"""
웹 스크래핑 수집 모듈

RSS가 없는 경남 지역 매체(경남신문, MBC경남, KBS경남, KNN)에서
최신 기사 제목과 URL을 스크래핑으로 수집한다.
"""

import html
import json
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import httpx
import yaml
from loguru import logger

from src.collect import Article


# ── 설정 ─────────────────────────────────────
SCRAPE_CONFIG_PATH = Path(__file__).parent.parent / "config" / "scrape.yaml"

# 브라우저처럼 보이는 User-Agent (봇 차단 우회)
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# HTML 태그 제거용
TAG_RE = re.compile(r"<[^>]+>")

# MBC경남 NewsViewFunc(ID) 패턴
MBC_ID_RE = re.compile(r"NewsViewFunc\((\d+)\)")


def _clean_title(text: str) -> str:
    """기사 제목 정제: HTML 태그·엔티티 제거, 공백 정리"""
    text = TAG_RE.sub("", text)           # HTML 태그 제거
    text = html.unescape(text)            # &apos; &quot; &nbsp; &amp; 등 디코딩
    text = re.sub(r"\s+", " ", text)      # 연속 공백·줄바꿈 → 공백 1개
    return text.strip()


def load_scrape_config(config_path: Optional[Path] = None) -> list[dict]:
    """scrape.yaml에서 스크래핑 대상 로드"""
    path = config_path or SCRAPE_CONFIG_PATH

    if not path.exists():
        logger.debug("scrape.yaml 없음 — 스크래핑 건너뜀")
        return []

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    sources = config.get("sources", [])
    logger.info(f"스크래핑 대상 {len(sources)}개 로드")
    return sources


def _extract_links_from_html(html_text: str, source_config: dict) -> list[dict]:
    """HTML에서 기사 링크와 제목을 추출한다.

    BeautifulSoup 없이 정규식으로 처리 (의존성 최소화)
    """
    name = source_config["name"]
    selector_hint = source_config.get("selector", "")
    base_url = source_config.get("base_url", "")

    articles = []
    seen_urls = set()

    if name == "MBC경남":
        # href="javascript:NewsViewFunc(ID)" + title 속성 또는 <h2> 제목
        template = source_config.get(
            "article_url_template",
            "https://www.mbcgn.kr/01_new/new01_view.asp?mn_lnk=B&idx={id}",
        )
        # 방법 1: title 속성이 있는 링크에서 추출
        pattern = r'<a\s+[^>]*href="javascript:NewsViewFunc\((\d+)\)"[^>]*title="([^"]+)"'
        for article_id, title in re.findall(pattern, html_text):
            title = _clean_title(title)
            url = template.format(id=article_id)
            if title and len(title) >= 5 and url not in seen_urls:
                seen_urls.add(url)
                articles.append({"title": title, "url": url})

        # 방법 2: title 속성이 없으면 <h2> 태그에서 추출
        if not articles:
            blocks = re.findall(
                r'NewsViewFunc\((\d+)\).*?<h[23][^>]*>(.*?)</h[23]>',
                html_text,
                re.DOTALL,
            )
            for article_id, title in blocks:
                title = _clean_title(title)
                url = template.format(id=article_id)
                if title and len(title) >= 5 and url not in seen_urls:
                    seen_urls.add(url)
                    articles.append({"title": title, "url": url})

    elif name == "KNN":
        # 절대 URL: href="https://news.knn.co.kr/news/article/186658"
        # 또는 상대 URL: href="/news/article/186658"
        pattern = r'<a\s+[^>]*href="((?:https?://news\.knn\.co\.kr)?/news/article/\d+)"[^>]*>(.*?)</a>'
        for path, inner in re.findall(pattern, html_text, re.DOTALL):
            # <h3> 또는 텍스트에서 제목 추출
            title_match = re.search(r'<h[23][^>]*>(.*?)</h[23]>', inner, re.DOTALL)
            if title_match:
                title = _clean_title(title_match.group(1))
            else:
                title = _clean_title(inner)
                # 카테고리 태그 등 짧은 텍스트 제거
                title = re.sub(r'^(경제|정치|사회|스포츠|문화|날씨)\s*', '', title).strip()
            url = path if path.startswith("http") else urljoin(base_url, path)
            if title and len(title) >= 5 and url not in seen_urls:
                seen_urls.add(url)
                articles.append({"title": title, "url": url})

    elif name == "경남신문":
        # 상대경로: href="../news/articleView.php?idxno=1539710&gubun="
        pattern = r'<a\s+[^>]*href="(?:\.\.)?(/news/articleView\.php\?idxno=\d+[^"]*)"[^>]*>(.*?)</a>'
        for path, title in re.findall(pattern, html_text, re.DOTALL):
            title = _clean_title(title)
            if not title or len(title) < 5:
                continue
            url = urljoin(base_url, path)
            if url not in seen_urls:
                seen_urls.add(url)
                articles.append({"title": title, "url": url})

    elif name == "KBS경남":
        # 유튜브 채널 페이지에서 ytInitialData JSON으로 영상 제목·URL 추출
        match = re.search(r'var ytInitialData = ({.+?});</script>', html_text)
        if match:
            try:
                data = json.loads(match.group(1))
                tabs = data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
                for tab in tabs:
                    items = tab.get("tabRenderer", {}).get("content", {}).get("richGridRenderer", {}).get("contents", [])
                    for item in items:
                        video = item.get("richItemRenderer", {}).get("content", {}).get("videoRenderer", {})
                        if not video:
                            continue
                        title = video.get("title", {}).get("runs", [{}])[0].get("text", "")
                        video_id = video.get("videoId", "")
                        if title and video_id:
                            # 제목에서 " / KBS  2026.04.21." 같은 꼬리 제거
                            title = re.sub(r"\s*/\s*KBS\s*\d{4}\.\d{2}\.\d{2}\.\s*$", "", title).strip()
                            url = f"https://www.youtube.com/watch?v={video_id}"
                            if title and len(title) >= 5 and url not in seen_urls:
                                seen_urls.add(url)
                                articles.append({"title": title, "url": url})
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"[KBS경남] 유튜브 JSON 파싱 실패: {e}")

    else:
        # 기본: href에서 링크 추출
        pattern = r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
        for path, title in re.findall(pattern, html_text, re.DOTALL):
            title = _clean_title(title)
            if not title or len(title) < 5:
                continue
            url = urljoin(base_url, path) if not path.startswith("http") else path
            if url not in seen_urls:
                seen_urls.add(url)
                articles.append({"title": title, "url": url})

    return articles


def scrape_source(
    source_config: dict,
    client: Optional[httpx.Client] = None,
) -> list[Article]:
    """단일 매체에서 기사 스크래핑

    Args:
        source_config: scrape.yaml의 개별 소스 설정
        client: httpx 클라이언트 (재사용)

    Returns:
        수집된 Article 리스트
    """
    name = source_config["name"]
    url = source_config["url"]
    scope = source_config.get("scope", "gyeongnam")

    try:
        if client:
            response = client.get(url, timeout=15)
        else:
            response = httpx.get(
                url,
                timeout=15,
                follow_redirects=True,
                headers={"User-Agent": BROWSER_UA},
            )

        response.raise_for_status()
        html = response.text

        raw_articles = _extract_links_from_html(html, source_config)

        articles = []
        for raw in raw_articles:
            article = Article(
                title=raw["title"],
                url=raw["url"],
                source=name,
            )
            articles.append(article)

        logger.info(f"[{name}] 스크래핑 {len(articles)}건 수집")
        return articles

    except httpx.HTTPStatusError as e:
        logger.warning(f"[{name}] HTTP 오류 {e.response.status_code}: {url}")
        return []
    except Exception as e:
        # 하나 실패해도 전체 파이프라인은 계속 (graceful degradation)
        logger.warning(f"[{name}] 스크래핑 실패: {e}")
        return []


def scrape_all(config_path: Optional[Path] = None) -> list[Article]:
    """모든 스크래핑 대상에서 기사 수집

    Args:
        config_path: scrape.yaml 경로 (테스트용)

    Returns:
        수집된 전체 Article 리스트
    """
    sources = load_scrape_config(config_path)

    if not sources:
        return []

    all_articles = []
    with httpx.Client(
        headers={"User-Agent": BROWSER_UA},
        follow_redirects=True,
    ) as client:
        for source_config in sources:
            articles = scrape_source(source_config, client)
            all_articles.extend(articles)

    # URL 기준 중복 제거
    seen_urls = set()
    unique = []
    for article in all_articles:
        if article.url not in seen_urls:
            seen_urls.add(article.url)
            unique.append(article)

    logger.info(f"스크래핑 전체: {len(all_articles)}건 → 중복 제거 후 {len(unique)}건")
    return unique
