"""중앙당 논평 구글시트 읽기 모듈

jpnews 프로젝트가 수집한 정의당 중앙당 논평을 구글시트에서 읽어온다.
대응 추천 기능에서 뉴스 기사와 매칭할 때 사용한다.

시트 구조 (6열): 날짜 | 유형 | 제목 | 주제 | 본문 | 원문링크
"""

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

import gspread
from google.oauth2.service_account import Credentials
from loguru import logger


SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


@dataclass
class Statement:
    """중앙당 논평 하나"""
    date: str         # YYYY-MM-DD
    type: str         # 논평, 성명, 보도자료, 기타
    title: str
    topic: str        # labor, climate, ... (newsclipper 분류와 동일)
    link: str


def _get_client(credentials_b64: str) -> gspread.Client:
    """읽기 전용 인증으로 gspread 클라이언트를 생성한다."""
    creds_json = json.loads(base64.b64decode(credentials_b64))
    creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
    return gspread.authorize(creds)


def read_statements(
    credentials_b64: str,
    sheet_id: str,
    months: int = 6,
) -> list[Statement]:
    """구글시트에서 최근 N개월 논평을 읽어온다.

    제목이나 주제가 빈 행은 건너뛴다 (아직 백필 안 된 행).
    """
    client = _get_client(credentials_b64)
    spreadsheet = client.open_by_key(sheet_id)
    sheet = spreadsheet.sheet1

    # 헤더 확인
    header = sheet.row_values(1)
    if len(header) < 6 or header[0] != "날짜":
        logger.warning("jpnews 시트 형식을 인식할 수 없습니다.")
        return []

    # 날짜 기준선
    cutoff = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")

    all_rows = sheet.get_all_values()
    statements = []

    for row in all_rows[1:]:
        if len(row) < 6:
            continue

        date_str, typ, title, topic, _body, link = row[0], row[1], row[2], row[3], row[4], row[5]

        # 빈 제목이나 주제는 건너뜀 (백필 안 된 행)
        if not title.strip() or not topic.strip():
            continue

        # 날짜 필터
        if date_str < cutoff:
            continue

        statements.append(Statement(
            date=date_str,
            type=typ,
            title=title,
            topic=topic,
            link=link,
        ))

    logger.info(f"중앙당 논평 {len(statements)}건 로드 (최근 {months}개월)")
    return statements


# 제목 키워드 겹침 최소 기준 (이 이상 겹쳐야 매칭으로 인정)
MIN_KEYWORD_OVERLAP = 2


def _extract_keywords(text: str) -> set[str]:
    """제목에서 2글자 이상 단어를 추출한다 (간단한 토큰화)."""
    import re
    # 한글·영문 단어만 추출, 조사·접속사 등 1글자 제거
    words = re.findall(r'[가-힣a-zA-Z]{2,}', text)
    # 흔한 불용어 제거
    stopwords = {"대한", "에서", "하는", "한다", "이다", "으로", "에게", "위한", "관련", "대해"}
    return {w for w in words if w not in stopwords}


def find_matching_statement(
    statements: list[Statement],
    category: str,
    article_title: str,
) -> Statement | None:
    """카테고리가 같고 제목 키워드가 겹치는 가장 최근 논평을 찾는다.

    키워드 겹침이 MIN_KEYWORD_OVERLAP 미만이면 None (관련 없는 논평 방지).
    """
    article_kw = _extract_keywords(article_title)
    if not article_kw:
        return None

    candidates = [s for s in statements if s.topic == category]
    if not candidates:
        return None

    # 키워드 겹침 수로 점수 매기기
    scored = []
    for stmt in candidates:
        stmt_kw = _extract_keywords(stmt.title)
        overlap = len(article_kw & stmt_kw)
        if overlap >= MIN_KEYWORD_OVERLAP:
            scored.append((overlap, stmt.date, stmt))

    if not scored:
        return None

    # 겹침 많은 순 → 같으면 최근 순
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return scored[0][2]
