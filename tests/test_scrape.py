"""scrape 모듈 단위 테스트

웅상신문(양산웅상신문) 블록 단위 파싱과 오래된 기사 필터,
경남신문 기사 링크 파싱을 검증한다.
2026-08-19: 양산시 집중 프로토타입에서 신규 추가.
"""

from datetime import datetime, timedelta

import httpx

from src.scrape import _extract_links_from_html, scrape_source


def _woongsang_html(now: datetime) -> str:
    """웅상신문 모바일 목록 실제 HTML 구조 (2026-08-19 실측)

    - 최근 기사: news_tit + news_modify
    - 오래된 기사: news_tit + news_modify (48시간 필터로 걸러야 함)
    - 날짜 없는 기사: news_tit만 (문화·카페 섹션, 다음 기사 날짜를 끌어오면 안 됨)
    """
    recent = (now - timedelta(hours=12)).strftime("%Y/%m/%d %H:%M")
    old = (now - timedelta(days=30)).strftime("%Y/%m/%d %H:%M")
    return f"""<ul>
<li><a href="view.php?idx=999">
<div class="txt_news">
<span class="news_tit">최근 양산 기사</span>
<em class="news_ctg">[웅상]</em>
<span class="news_modify">{recent}</span>
</div></a></li>
<li><a href="view.php?idx=1000">
<div class="txt_news">
<span class="news_tit">오래된 양산 기사</span>
<span class="news_modify">{old}</span>
</div></a></li>
<li><a href="view.php?idx=1001">
<div class="txt_news">
<span class="news_tit">날짜 없는 기사</span>
</div></a></li>
</ul>"""


def test_양산웅상신문_블록_파싱():
    """각 기사 블록 안에서 제목·URL·날짜를 추출한다.

    날짜 없는 기사는 None이어야 한다 (다음 기사의 날짜를 끌어오지 않음).
    """
    now = datetime.now()
    config = {"name": "양산웅상신문", "base_url": "http://m.ungsangnews.com"}
    articles = _extract_links_from_html(_woongsang_html(now), config)

    assert len(articles) == 3
    assert articles[0]["title"] == "최근 양산 기사"
    assert articles[0]["url"] == "http://m.ungsangnews.com/view.php?idx=999"
    assert articles[0]["published_at"] is not None
    assert articles[1]["title"] == "오래된 양산 기사"
    assert articles[1]["published_at"] is not None
    # 날짜가 없는 기사는 None (경계 침범 금지)
    assert articles[2]["title"] == "날짜 없는 기사"
    assert articles[2]["published_at"] is None


def test_양산웅상신문_오래된_기사_필터():
    """48시간보다 오래된 기사는 수집에서 제외된다.

    웅상신문 목록은 오래된 순(2022~2023년 기사가 위)이라
    날짜 필터 없이는 과거 기사가 '오늘 뉴스'로 브리핑에 실린다.
    """
    now = datetime.now()

    def handler(request):
        return httpx.Response(200, text=_woongsang_html(now))

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    config = {
        "name": "양산웅상신문",
        "url": "http://m.ungsangnews.com/list.php?part_idx=291",
        "base_url": "http://m.ungsangnews.com",
    }

    articles = scrape_source(config, client=client)

    titles = [a.title for a in articles]
    assert "오래된 양산 기사" not in titles, "30일 전 기사는 필터링되어야 함"
    assert "최근 양산 기사" in titles
    assert "날짜 없는 기사" in titles


def test_경남신문_기사_링크_파싱():
    """경남신문 홈페이지의 articleView 링크에서 제목·URL을 추출한다."""
    html = (
        '<a href="../news/articleView.php?idxno=1548870">'
        "수마가 할퀸 터전… 쓸고 닦아도 막막"
        "</a>"
    )
    config = {"name": "경남신문", "base_url": "https://www.knnews.co.kr"}
    articles = _extract_links_from_html(html, config)

    assert len(articles) == 1
    assert articles[0]["title"] == "수마가 할퀸 터전… 쓸고 닦아도 막막"
    assert articles[0]["url"] == (
        "https://www.knnews.co.kr/news/articleView.php?idxno=1548870"
    )
