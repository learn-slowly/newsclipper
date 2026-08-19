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


def test_양산시청_보도자료_파싱_및_부서필터():
    """양산시청 보도자료 목록에서 시청 부서 글은 수집하고, 읍면동 단순 미담은 제외한다."""
    html = """
    <table>
        <tr>
            <td>24185</td>
            <td><a href="#" data-action="/portal/saeol/news/view.do" data-keyset="{'newsEpctNo': '28169'}">하북면, 착한나눔가게 53호점 협약식</a></td>
            <td>하북면</td>
            <td>2026-08-19</td>
        </tr>
        <tr>
            <td>24184</td>
            <td><a href="#" data-action="/portal/saeol/news/view.do" data-keyset="{'newsEpctNo': '28168'}">양산시, 2026년 첨단 스마트도시 사업 추진 계획 발표</a></td>
            <td>미래산업과</td>
            <td>2026-08-19</td>
        </tr>
        <tr>
            <td>24183</td>
            <td><a href="#" data-action="/portal/saeol/news/view.do" data-keyset="{'newsEpctNo': '28167'}">물금읍, 주민참여예산 조례 관련 주민설명회 개최</a></td>
            <td>물금읍</td>
            <td>2026-08-19</td>
        </tr>
    </table>
    """
    config = {"name": "양산시청", "base_url": "https://www.yangsan.go.kr"}
    articles = _extract_links_from_html(html, config)

    titles = [a["title"] for a in articles]
    # 읍면동 단순 나눔은 제외
    assert "하북면, 착한나눔가게 53호점 협약식" not in titles
    # 시청 부서의 정책 발표는 포함
    assert "양산시, 2026년 첨단 스마트도시 사업 추진 계획 발표" in titles
    # 읍면동이라도 조례/설명회 등 중요 정책 키워드가 있으면 포함
    assert "물금읍, 주민참여예산 조례 관련 주민설명회 개최" in titles

    assert len(articles) == 2
    assert articles[0]["url"] == "https://www.yangsan.go.kr/portal/saeol/news/view.do?newsEpctNo=28168&mid=0105010000"
    assert articles[0]["published_at"] == datetime(2026, 8, 19)
    assert "[미래산업과]" in articles[0]["summary"]


def test_창원시청_보도자료_파싱():
    """창원시청 보도자료 목록에서 제목, 요약문, 부서, 날짜와 언이스케이프된 URL을 정확히 추출한다."""
    html = """
    <ul>
        <li class="li1">
            <div class="wrap1">
                <a href="?gcode=1011&amp;idx=882795&amp;amode=view&amp;" class="a1">
                    <span class="wrap1texts">
                        <strong class="t1">창원특례시, 시내버스 ‘준공영제 2.0’ 시대 연다<i class="ic1 new"><span class="t1">새 글</span></i></strong>
                        <span class="t2">창원특례시는 시내버스 준공영제 갱신 협약을 체결했다.</span>
                        <i class="wrap1t3">
                            <span class="t3">2026-08-19</span>
                            <span class="t3">버스운영과</span>
                            <span class="t3">조회수 : 37</span>
                        </i>
                    </span>
                </a>
            </div>
        </li>
    </ul>
    """
    config = {
        "name": "창원시청",
        "url": "https://www.changwon.go.kr/cwportal/10310/10429/10432.web",
        "base_url": "https://www.changwon.go.kr",
    }
    articles = _extract_links_from_html(html, config)

    assert len(articles) == 1
    assert articles[0]["title"] == "창원특례시, 시내버스 ‘준공영제 2.0’ 시대 연다"
    # &amp;가 &로 언이스케이프되고 목록 URL 경로가 유지되어야 함
    assert articles[0]["url"] == "https://www.changwon.go.kr/cwportal/10310/10429/10432.web?gcode=1011&idx=882795&amode=view&"
    assert articles[0]["published_at"] == datetime(2026, 8, 19)
    assert "[버스운영과]" in articles[0]["summary"]
    assert "창원특례시는 시내버스" in articles[0]["summary"]


def test_경남교육청_보도자료_파싱():
    """경남교육청 보도자료 목록에서 제목, 요약문, 날짜, URL을 정확히 추출한다."""
    html = """
    <ul>
        <li>
            <a href="BD_selectBbs.do?q_bbsSn=1350&amp;q_bbsDocNo=20260819111426335">
                <div class="cont">
                    <p class="tit">가짜 뉴스, 사이버 폭력 스스로 거른다</p>
                    <div class="comn">경상남도교육청은 디지털 미디어 문해교육을 운영한다고 밝혔다.</div>
                    <div class="info">
                        <p class="date">2026-08-19</p>
                    </div>
                </div>
            </a>
        </li>
    </ul>
    """
    config = {
        "name": "경남교육청",
        "url": "https://www.gne.go.kr/pr/user/bbs/BD_selectBbsList.do?q_bbsSn=1350",
        "base_url": "https://www.gne.go.kr",
    }
    articles = _extract_links_from_html(html, config)

    assert len(articles) == 1
    assert articles[0]["title"] == "가짜 뉴스, 사이버 폭력 스스로 거른다"
    assert articles[0]["url"] == "https://www.gne.go.kr/pr/user/bbs/BD_selectBbs.do?q_bbsSn=1350&q_bbsDocNo=20260819111426335"
    assert articles[0]["published_at"] == datetime(2026, 8, 19)
    assert "디지털 미디어 문해교육" in articles[0]["summary"]
