"""
웹 스크래핑 수집 모듈

RSS가 없는 경남 지역 매체(경남신문, MBC경남, KBS경남, KNN)에서
최신 기사 제목과 URL을 스크래핑으로 수집한다.
"""

import html
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import httpx
import yaml
from loguru import logger

from src import MIN_CONTENT_LENGTH
from src.collect import Article, _legacy_ssl_context


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

# 스크래핑 기본 타임아웃(초). 느린 매체는 scrape.yaml의 timeout 값으로 개별 조정한다.
DEFAULT_SCRAPE_TIMEOUT = 15
# 타임아웃 시 재시도 횟수 (느린 서버가 한 번에 응답 못 하는 경우 대비)
SCRAPE_MAX_ATTEMPTS = 2

# 목록에 날짜가 있는 스크래핑 매체(웅상신문)에서 몇 시간 이내 기사만 남길지.
# 24시간으로 두면 하루 2회 실행 시 아침 수집분이 저녁에 다시 실릴 수 있어 48시간으로 넉넉히 잡는다.
SCRAPE_RECENCY_HOURS = 48

# ── Jina Reader 본문 추출 설정 ─────────────────────
# 스크래핑 매체(MBC경남·KNN·경남신문 등)는 RSS와 달리 본문이 비어 있으므로
# Jina Reader(https://r.jina.ai)를 통해 본문을 마크다운으로 가져온다.
JINA_BASE_URL = "https://r.jina.ai/"
JINA_TIMEOUT = 15
JINA_RATE_LIMIT_SLEEP = 0.5      # 호출 사이 sleep (초)
BODY_TRUNCATE_LENGTH = 500       # Article.summary에 저장할 최대 길이


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

    elif name == "양산웅상신문":
        # 웅상신문(2026-08-15 제호 변경: 양산웅상신문) 모바일 목록
        # <a href="view.php?idx=43566"> 블록 안에
        #   <span class="news_tit">제목</span>
        #   <span class="news_modify">2025/06/08 12:37</span>
        # 목록이 오래된 순(2022~2023년 기사가 위)이라 날짜로 걸러낸다.
        # 블록 단위로 자른 뒤 각 블록 안에서만 파싱 — news_modify가 없는
        # 기사가 다음 기사의 날짜를 끌어오지 않게 한다.
        blocks = re.split(r'(?=<a\s[^>]*href="view\.php\?idx=)', html_text)
        for block in blocks:
            link = re.search(r'href="(view\.php\?idx=\d+)"', block)
            if not link:
                continue
            path = link.group(1)
            tit = re.search(
                r'<span class="news_tit">(.*?)</span>', block, re.DOTALL
            )
            if not tit:
                continue
            title = _clean_title(tit.group(1))
            if not title or len(title) < 5:
                continue
            pub_date = None
            mod = re.search(
                r'<span class="news_modify">'
                r'(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})</span>',
                block,
            )
            if mod:
                try:
                    pub_date = datetime(
                        int(mod.group(1)), int(mod.group(2)), int(mod.group(3)),
                        int(mod.group(4)), int(mod.group(5)),
                    )
                except ValueError:
                    pub_date = None
            url = urljoin(base_url, path)
            if url not in seen_urls:
                seen_urls.add(url)
                articles.append({"title": title, "url": url, "published_at": pub_date})

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

    elif name == "민중의소리":
        # 기사 URL: href="/A00001695553.html", 링크 안 텍스트가 제목
        pattern = r'<a\s+[^>]*href="(/A\d{6,}\.html)"[^>]*>(.*?)</a>'
        for path, inner in re.findall(pattern, html_text, re.DOTALL):
            title = _clean_title(inner)
            if not title or len(title) < 5:
                continue
            url = urljoin(base_url, path)
            if url not in seen_urls:
                seen_urls.add(url)
                articles.append({"title": title, "url": url})


    elif name == "프레시안":
        # 기사 URL: href="/pages/articles/2026081214152226144", 링크 안 텍스트가 제목
        pattern = r'<a\s+[^>]*href="(/pages/articles/\d+)"[^>]*>(.*?)</a>'
        for path, inner in re.findall(pattern, html_text, re.DOTALL):
            title = _clean_title(inner)
            if not title or len(title) < 5:
                continue
            url = urljoin(base_url, path)
            if url not in seen_urls:
                seen_urls.add(url)
                articles.append({"title": title, "url": url})

    elif name == "양산시청":
        # 양산시청 보도자료/해명자료 목록: <a ... data-action="..." data-keyset="{'newsEpctNo': '...'}">
        # 읍·면·동 주민센터 단순 미담/간식 나눔 건은 필터링하여 AI 비용 방어
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html_text, re.DOTALL)
        for row in rows:
            keyset_match = re.search(r"data-keyset=\"\{'newsEpctNo':\s*'(\d+)'\}\"", row)
            if not keyset_match:
                continue
            news_no = keyset_match.group(1)

            link_match = re.search(r'<a\s+[^>]*data-action="([^"]+)"[^>]*>(.*?)</a>', row, re.DOTALL)
            if not link_match:
                continue
            action_path = link_match.group(1)
            raw_title = link_match.group(2)
            title = _clean_title(raw_title)
            if not title or len(title) < 5:
                continue

            tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            dept = ""
            date_str = ""
            if len(tds) >= 4:
                dept = _clean_title(tds[2])
                date_str = _clean_title(tds[3])

            # 부서 필터: 읍·면·동 단위 단순 미담/간식/생일/성금/나눔 등 제외
            if re.search(r'(동|읍|면|주민센터|행정복지센터)$', dept):
                if re.search(r'(나눔|기탁|간식|생일|후원|어르신|경로당|이웃돕기|봉사|전달)', title):
                    continue
                if not re.search(r'(조례|예산|대책|설명회|공청회|청사|주민자치회|투표|선거)', title):
                    continue
            pub_date = None
            date_match = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', date_str)
            if date_match:
                try:
                    pub_date = datetime(
                        int(date_match.group(1)),
                        int(date_match.group(2)),
                        int(date_match.group(3)),
                    )
                except ValueError:
                    pub_date = None

            url = f"https://www.yangsan.go.kr{action_path}?newsEpctNo={news_no}&mid=0105010000"
            if url not in seen_urls:
                seen_urls.add(url)
                articles.append({
                    "title": title,
                    "url": url,
                    "published_at": pub_date,
                    "summary": f"[{dept}] {title}" if dept else title,
                })

    elif name == "창원시청":
        # 창원시청 보도자료 목록: <li class="li1">...<strong class="t1">제목</strong><span class="t2">요약</span>
        items = re.findall(r'<li\s+class="li1"[^>]*>(.*?)</li>', html_text, re.DOTALL)
        for item in items:
            link_match = re.search(r'<a\s+[^>]*href="([^"]+)"[^>]*>', item)
            if not link_match:
                continue
            href = link_match.group(1)

            title_match = re.search(r'<strong\s+class="t1"[^>]*>(.*?)</strong>', item, re.DOTALL)
            if not title_match:
                continue
            raw_title = title_match.group(1)
            title = _clean_title(raw_title)
            title = re.sub(r'새\s*글\s*$', '', title).strip()
            if not title or len(title) < 5:
                continue

            summary = ""
            sum_match = re.search(r'<span\s+class="t2"[^>]*>(.*?)</span>', item, re.DOTALL)
            if sum_match:
                summary = _clean_title(sum_match.group(1))

            pub_date = None
            t3_list = re.findall(r'<span\s+class="t3"[^>]*>(.*?)</span>', item, re.DOTALL)
            dept = ""
            for t3_text in t3_list:
                cleaned = _clean_title(t3_text)
                date_match = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', cleaned)
                if date_match and not pub_date:
                    try:
                        pub_date = datetime(
                            int(date_match.group(1)),
                            int(date_match.group(2)),
                            int(date_match.group(3)),
                        )
                    except ValueError:
                        pub_date = None
                elif not date_match and not cleaned.startswith("조회수") and cleaned:
                    dept = cleaned

            clean_href = html.unescape(href)
            # 상대경로가 ?gcode=... 형태이므로 목록 페이지 URL을 기준으로 합친다
            page_url = source_config.get("url") or base_url
            url = urljoin(page_url, clean_href)
            if url not in seen_urls:
                seen_urls.add(url)
                full_summary = f"[{dept}] {summary}" if dept and summary else (summary or title)
                articles.append({
                    "title": title,
                    "url": url,
                    "published_at": pub_date,
                    "summary": full_summary,
                })

    elif name == "경남교육청":
        # 경남교육홍보관 보도자료 목록: <p class="tit">제목</p><div class="comn">요약</div><p class="date">날짜</p>
        items = re.findall(r'<li[^>]*>\s*<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*</li>', html_text, re.DOTALL)
        for href, inner in items:
            tit_match = re.search(r'<p\s+class="tit"[^>]*>(.*?)</p>', inner, re.DOTALL)
            if not tit_match:
                continue
            title = _clean_title(tit_match.group(1))
            if not title or len(title) < 5:
                continue

            summary = ""
            comn_match = re.search(r'<div\s+class="comn"[^>]*>(.*?)</div>', inner, re.DOTALL)
            if comn_match:
                summary = _clean_title(comn_match.group(1))

            pub_date = None
            date_match = re.search(r'<p\s+class="date"[^>]*>(\d{4})-(\d{1,2})-(\d{1,2})</p>', inner)
            if date_match:
                try:
                    pub_date = datetime(
                        int(date_match.group(1)),
                        int(date_match.group(2)),
                        int(date_match.group(3)),
                    )
                except ValueError:
                    pub_date = None

            clean_href = html.unescape(href)
            page_url = source_config.get("url") or base_url
            url = urljoin(page_url, clean_href)
            if url not in seen_urls:
                seen_urls.add(url)
                articles.append({
                    "title": title,
                    "url": url,
                    "published_at": pub_date,
                    "summary": summary or title,
                })
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
    # 매체별 타임아웃 (scrape.yaml에 timeout 지정 시 우선, 없으면 기본값)
    timeout = source_config.get("timeout", DEFAULT_SCRAPE_TIMEOUT)
    # 낡은 SSL을 쓰는 서버(예: 민중의소리)는 보안 레벨 낮춘 전용 컨텍스트로 요청
    legacy_ssl = source_config.get("legacy_ssl", False)

    # 타임아웃은 일시적일 수 있으므로 SCRAPE_MAX_ATTEMPTS회까지 재시도한다.
    # HTTP 오류·파싱 오류 등은 재시도해도 같으므로 즉시 중단한다.
    for attempt in range(1, SCRAPE_MAX_ATTEMPTS + 1):
        try:
            if legacy_ssl:
                # 공용 client는 기본 SSL이라 거부당하므로 전용 컨텍스트로 직접 요청
                response = httpx.get(
                    url,
                    timeout=timeout,
                    follow_redirects=True,
                    headers={"User-Agent": BROWSER_UA},
                    verify=_legacy_ssl_context(),
                )
            elif client:
                response = client.get(url, timeout=timeout)
            else:
                response = httpx.get(
                    url,
                    timeout=timeout,
                    follow_redirects=True,
                    headers={"User-Agent": BROWSER_UA},
                )

            response.raise_for_status()
            html = response.text

            raw_articles = _extract_links_from_html(html, source_config)

            # 목록에 날짜가 있는 매체(웅상신문)의 오래된 기사 걸러내기
            cutoff = datetime.now() - timedelta(hours=SCRAPE_RECENCY_HOURS)

            articles = []
            for raw in raw_articles:
                article = Article(
                    title=raw["title"],
                    url=raw["url"],
                    source=name,
                    summary=raw.get("summary", ""),
                    published_at=raw.get("published_at"),
                )
                if article.published_at and article.published_at < cutoff:
                    continue
                articles.append(article)

            logger.info(f"[{name}] 스크래핑 {len(articles)}건 수집")
            return articles

        except httpx.TimeoutException:
            if attempt < SCRAPE_MAX_ATTEMPTS:
                logger.warning(
                    f"[{name}] 타임아웃 (시도 {attempt}/{SCRAPE_MAX_ATTEMPTS}, "
                    f"{timeout}초) — 재시도"
                )
                continue
            logger.warning(
                f"[{name}] 스크래핑 실패: 타임아웃 {SCRAPE_MAX_ATTEMPTS}회 ({timeout}초)"
            )
            return []
        except httpx.HTTPStatusError as e:
            logger.warning(f"[{name}] HTTP 오류 {e.response.status_code}: {url}")
            return []
        except Exception as e:
            # 하나 실패해도 전체 파이프라인은 계속 (graceful degradation)
            logger.warning(f"[{name}] 스크래핑 실패: {e}")
            return []

    return []


def fetch_body_via_jina(url: str, client: httpx.Client) -> tuple[str, str]:
    """Jina Reader로 기사 본문 추출

    Args:
        url: 원본 기사 URL
        client: httpx 클라이언트 (재사용)

    Returns:
        (본문 텍스트, 상태 코드 라벨)
        - 성공: (본문, "ok")
        - 429 rate limit: ("", "rate_limit")
        - 기타 실패: ("", "error")
    """
    headers = {"User-Agent": BROWSER_UA, "Accept": "text/plain"}

    # 환경변수에 키가 있으면 추가 (없어도 무료 티어로 동작)
    api_key = os.getenv("JINA_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    jina_url = f"{JINA_BASE_URL}{url}"

    try:
        response = client.get(jina_url, headers=headers, timeout=JINA_TIMEOUT)

        if response.status_code == 429:
            return "", "rate_limit"

        response.raise_for_status()
        text = response.text

        # "Markdown Content:" 마커 이후만 사용 (앞쪽 메타데이터 제거)
        # 마커가 없으면 전체 텍스트 사용 (방어적 fallback)
        marker = "Markdown Content:"
        idx = text.find(marker)
        if idx >= 0:
            body = text[idx + len(marker):].strip()
        else:
            body = text.strip()

        return body, "ok"

    except httpx.HTTPStatusError:
        return "", "error"
    except httpx.TimeoutException:
        return "", "error"
    except Exception:
        return "", "error"


def enrich_articles_with_body(
    articles: list[Article],
    client: httpx.Client,
) -> None:
    """스크래핑된 Article 리스트의 summary를 Jina Reader 본문으로 채운다.

    in-place로 article.summary를 수정한다.
    YouTube URL은 영상 본문 추출이 불가능하므로 스킵.
    본문이 MIN_CONTENT_LENGTH 미만이면 빈 문자열 유지 → 다음 단계 가드가 처리.
    """
    for i, article in enumerate(articles):
        title_short = article.title[:30]

        # 이미 목록에서 충분한 요약문이 추출된 경우 Jina 조회 생략 (창원시청, 경남교육청 등)
        if article.summary and len(article.summary) >= MIN_CONTENT_LENGTH:
            logger.debug(f"[Jina] 이미 요약문 있음 (Jina 생략): {title_short}")
            continue

        # YouTube URL 스킵 (KBS경남 채널)
        if "youtube.com/watch" in article.url or "youtu.be/" in article.url:
            logger.debug(f"[Jina] YouTube URL 스킵: {title_short}")
            continue

        body, status = fetch_body_via_jina(article.url, client)

        if status == "rate_limit":
            logger.warning(
                f"[Jina] ⏱ rate limit (429) | {article.source} | {title_short}"
            )
        elif status == "error":
            logger.warning(
                f"[Jina] ✗ fetch 실패 | {article.source} | {title_short}"
            )
        elif len(body) >= MIN_CONTENT_LENGTH:
            article.summary = body[:BODY_TRUNCATE_LENGTH]
            logger.info(
                f"[Jina] ✓ {article.source} | {len(body)}자 → "
                f"{len(article.summary)}자 저장 | {title_short}"
            )
        else:
            logger.warning(
                f"[Jina] ✗ {article.source} | {len(body)}자 "
                f"(임계값 {MIN_CONTENT_LENGTH} 미만) | {title_short}"
            )

        # 마지막 항목 뒤엔 sleep 안 함
        if i < len(articles) - 1:
            time.sleep(JINA_RATE_LIMIT_SLEEP)


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

        logger.info(
            f"스크래핑 전체: {len(all_articles)}건 → 중복 제거 후 {len(unique)}건"
        )

        # Jina Reader로 본문 enrich (스크래핑 매체 4곳, RSS 매체는 영향 없음)
        if unique:
            logger.info(f"📥 Jina Reader로 본문 fetch 시작 ({len(unique)}건)")
            enrich_articles_with_body(unique, client)

    return unique
