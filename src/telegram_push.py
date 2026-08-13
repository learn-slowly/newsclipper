"""
텔레그램 발송 모듈

섹션별로 정리된 브리핑 메시지를 텔레그램 비공개 채널에 발송한다.
4096자 제한을 고려해 섹션 경계에서 자동 분할한다.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from loguru import logger

from src import LOW_CONTENT_MARKER
from src.collect import Article
from src.section_builder import ArticleGroup, Section


# 텔레그램 메시지 최대 길이
MAX_MESSAGE_LENGTH = 4096


def _format_scope(scope: str) -> str:
    """스코프를 한국어로 변환"""
    return {"gyeongnam": "경남", "national": "전국", "both": "전국+경남"}.get(
        scope, scope
    )


def _format_article(article: Article, statement=None) -> str:
    """단일 기사를 텔레그램 메시지 포맷으로 변환"""
    if article.low_content:
        prefix = "⚠️ "
    elif getattr(article, "response_needed", "") == "high":
        prefix = "📢 "
    elif article.importance == 5:
        prefix = "🔥 "
    else:
        prefix = ""

    scope_label = _format_scope(article.scope)
    title_suffix = f" {LOW_CONTENT_MARKER}" if article.low_content else ""
    line = f"{prefix}[{article.importance}|{scope_label}] {article.title}{title_suffix}"

    # 이슈 경과 맥락 표시
    if article.ongoing_context:
        line += f"\n   {article.ongoing_context}"

    # AI 코멘트가 있으면 추가
    if article.ai_comment:
        line += f"\n   → {article.ai_comment}"

    line += f"\n   {article.url}"
    # 대응 필요(high) 기사에 중앙당 논평 표시
    if getattr(article, "response_needed", "") == "high":
        if statement:
            line += f"\n   📌 참고 논평: {statement.title} ({statement.date})"
            line += f"\n      {statement.link}"
        else:
            line += f"\n   📌 중앙당 참고 논평 없음 — 도당 자체 대응 검토"

    return line


def _format_group(group: ArticleGroup, statement=None) -> str:
    """기사 그룹을 텔레그램 메시지 포맷으로 변환

    대표 기사: 제목 + 코멘트 + 링크
    관련 기사: 출처명 + 링크만 간략히
    statement: 매칭된 중앙당 논평 (있으면 표시)
    """
    primary = group.primary
    if primary.low_content:
        prefix = "⚠️ "
    elif getattr(primary, "response_needed", "") == "high":
        prefix = "📢 "
    elif primary.importance == 5:
        prefix = "🔥 "
    else:
        prefix = ""
    scope_label = _format_scope(primary.scope)
    title_suffix = f" {LOW_CONTENT_MARKER}" if primary.low_content else ""

    line = f"{prefix}[{primary.importance}|{scope_label}] {primary.title}{title_suffix}"

    # 이슈 경과 맥락 표시
    if primary.ongoing_context:
        line += f"\n   {primary.ongoing_context}"

    if primary.ai_comment:
        line += f"\n   → {primary.ai_comment}"

    line += f"\n   {primary.url}"
    # 관련 기사가 있으면 출처 + 링크 추가
    if group.related:
        line += f"\n   📎 관련 {len(group.related)}건:"
        for related in group.related:
            line += f"\n   · [{related.source}] {related.url}"

    # 대응 필요(high) 기사에 중앙당 논평 표시
    if getattr(primary, "response_needed", "") == "high":
        if statement:
            line += f"\n   📌 참고 논평: {statement.title} ({statement.date})"
            line += f"\n      {statement.link}"
        else:
            line += f"\n   📌 중앙당 참고 논평 없음 — 도당 자체 대응 검토"

    return line


def _format_section(section: Section, statement_map: dict | None = None) -> str:
    """단일 섹션을 텔레그램 메시지 포맷으로 변환"""
    total = len(section.articles)
    group_count = len(section.groups)
    smap = statement_map or {}

    # 그룹이 있으면 이슈 수로 표시
    if group_count < total:
        header = f"{section.emoji} {section.name} ({group_count}건의 이슈, {total}건 기사)"
    else:
        header = f"{section.emoji} {section.name} ({total}건)"

    # 그룹 기반으로 포맷
    if section.groups:
        items_text = "\n\n".join(
            _format_group(g, smap.get(g.primary.url))
            for g in section.groups
        )
    else:
        items_text = "\n\n".join(
            _format_article(a, smap.get(a.url)) for a in section.articles
        )

    return f"{header}\n{items_text}"


def format_briefing(
    sections: list[Section],
    total_collected: int,
    statement_map: dict | None = None,
) -> str:
    """전체 브리핑 메시지 생성

    statement_map: 기사 URL → Statement 매칭 (없으면 빈 dict)
    """
    tz = ZoneInfo(os.getenv("TIMEZONE", "Asia/Seoul"))
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d (%a)")
    total_selected = sum(len(s.articles) for s in sections)

    # 오전/저녁 구분 (정오 기준, KST)
    time_label = "아침" if now.hour < 12 else "저녁"

    header = (
        f"📰 경남도당 {time_label} 브리핑 | {today}\n"
        f"오늘 총 {total_collected}건 중 {total_selected}건 선별"
    )

    section_texts = [_format_section(s, statement_map) for s in sections]

    return header + "\n\n" + "\n\n".join(section_texts)


def format_alert_message(articles: list[Article]) -> str:
    """속보 전용 텔레그램 메시지 생성"""
    tz = ZoneInfo(os.getenv("TIMEZONE", "Asia/Seoul"))
    now = datetime.now(tz)
    time_str = now.strftime("%Y-%m-%d %H:%M")

    header = f"🚨 [속보] 중요 뉴스 긴급 알림 | {time_str}"

    items = []
    for a in articles:
        scope_label = _format_scope(a.scope)
        item = f"🔥 [{a.importance}|{scope_label}] [{a.source}] {a.title}"
        if a.summary:
            # summary의 첫 100자만 간략히
            short_sum = a.summary.strip().replace("\n", " ")
            if len(short_sum) > 100:
                short_sum = short_sum[:100] + "..."
            item += f"\n   → {short_sum}"
        if a.ongoing_context:
            item += f"\n   {a.ongoing_context}"
        item += f"\n   {a.url}"
        items.append(item)

    return header + "\n\n" + "\n\n".join(items)


def format_weekly_summary_message(
    summary_text: str, start_date: str, end_date: str, total_articles: int
) -> str:
    """주간 요약 보고서 메시지 생성"""
    header = (
        f"📊 [주간 브리핑] 경남도당 이슈 주간 리포트\n"
        f"📅 {start_date} ~ {end_date} (수집 총 {total_articles}건)"
    )
    return header + "\n\n" + summary_text

def split_message(text: str) -> list[str]:
    """텔레그램 4096자 제한에 맞게 메시지 분할

    \n\n(섹션) -> \n(줄) -> 글자 수 하드 컷 순으로 4096자 제한 준수
    """
    if len(text) <= MAX_MESSAGE_LENGTH:
        return [text]

    def _split_chunk(chunk: str, sep: str, next_sep: str | None) -> list[str]:
        if len(chunk) <= MAX_MESSAGE_LENGTH:
            return [chunk]
        res = []
        subparts = chunk.split(sep)
        curr = ""
        for p in subparts:
            if len(p) > MAX_MESSAGE_LENGTH:
                if curr:
                    res.append(curr)
                    curr = ""
                if next_sep is not None:
                    res.extend(_split_chunk(p, next_sep, None))
                else:
                    for i in range(0, len(p), MAX_MESSAGE_LENGTH):
                        res.append(p[i:i+MAX_MESSAGE_LENGTH])
                continue

            delim = sep if (curr and sep) else ""
            if len(curr) + len(delim) + len(p) > MAX_MESSAGE_LENGTH:
                if curr:
                    res.append(curr)
                curr = p
            else:
                curr = curr + delim + p if curr else p
        if curr:
            res.append(curr)
        return res

    return _split_chunk(text, "\n\n", "\n")


async def send_telegram(
    text: str,
    bot_token: str,
    channel_id: str,
) -> bool:
    """텔레그램 메시지 발송

    Args:
        text: 발���할 메시지
        bot_token: 텔레그램 봇 토큰
        channel_id: 채널 ID

    Returns:
        발송 성공 여부
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    messages = split_message(text)
    failed = 0

    async with httpx.AsyncClient() as client:
        for i, msg in enumerate(messages):
            payload = {
                "chat_id": channel_id,
                "text": msg,
                "disable_web_page_preview": True,
            }

            try:
                response = await client.post(url, json=payload, timeout=30)

                if response.status_code != 200:
                    body = response.text
                    logger.error(
                        f"텔레그램 발송 실패 ({i+1}/{len(messages)}): "
                        f"HTTP {response.status_code} - {body}\n"
                        f"메시지 길이: {len(msg)}자"
                    )
                    failed += 1
                    continue

                data = response.json()
                if not data.get("ok"):
                    logger.error(f"텔레그램 API 오류 ({i+1}/{len(messages)}): {data}")
                    failed += 1
                    continue

            except Exception as e:
                logger.error(f"텔레그램 발송 오류 ({i+1}/{len(messages)}): {e}")
                failed += 1
                continue

    if failed:
        logger.warning(f"텔레그램 발송: {len(messages)}개 중 {failed}개 실패")
        return failed < len(messages)  # 전부 실패한 경우만 False

    logger.info(f"텔레그램 발송 완료 ({len(messages)}개 메시지)")
    return True


async def send_error_alert(
    error_msg: str,
    bot_token: str,
    admin_user_id: str,
):
    """오류 알림을 관리자에게 DM으로 발송"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    text = f"⚠️ clipboard055 오류 알림\n\n{error_msg}"

    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                url,
                json={
                    "chat_id": admin_user_id,
                    "text": text[:MAX_MESSAGE_LENGTH],
                },
                timeout=30,
            )
        except Exception as e:
            logger.error(f"오류 알림 발송 실패: {e}")
