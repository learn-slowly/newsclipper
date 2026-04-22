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

from src.collect import Article
from src.section_builder import ArticleGroup, Section


# 텔레그램 메시지 최대 길이
MAX_MESSAGE_LENGTH = 4096


def _format_scope(scope: str) -> str:
    """스코프를 한국어로 변환"""
    return {"gyeongnam": "경남", "national": "전국", "both": "전국+경남"}.get(
        scope, scope
    )


def _format_article(article: Article) -> str:
    """단일 기사를 텔레그램 메시지 포맷으로 변환"""
    # 중요도 5점에만 🔥 이모지
    fire = "🔥 " if article.importance == 5 else ""

    scope_label = _format_scope(article.scope)
    line = f"{fire}[{article.importance}|{scope_label}] {article.title}"

    # AI 코멘트가 있으면 추가
    if article.ai_comment:
        line += f"\n   → {article.ai_comment}"

    line += f"\n   {article.url}"

    return line


def _format_group(group: ArticleGroup) -> str:
    """기사 그룹을 텔레그램 메시지 포맷으로 변환

    대표 기사: 제목 + 코멘트 + 링크
    관련 기사: 출처명 + 링크만 간략히
    """
    primary = group.primary
    fire = "🔥 " if primary.importance == 5 else ""
    scope_label = _format_scope(primary.scope)

    line = f"{fire}[{primary.importance}|{scope_label}] {primary.title}"

    if primary.ai_comment:
        line += f"\n   → {primary.ai_comment}"

    line += f"\n   {primary.url}"

    # 관련 기사가 있으면 출처 + 링크 추가
    if group.related:
        line += f"\n   📎 관련 {len(group.related)}건:"
        for related in group.related:
            line += f"\n   · [{related.source}] {related.url}"

    return line


def _format_section(section: Section) -> str:
    """단일 섹션을 텔레그램 메시지 포맷으로 변환"""
    total = len(section.articles)
    group_count = len(section.groups)

    # 그룹이 있으면 이슈 수로 표시
    if group_count < total:
        header = f"{section.emoji} {section.name} ({group_count}건의 이슈, {total}건 기사)"
    else:
        header = f"{section.emoji} {section.name} ({total}건)"

    # 그룹 기반으로 포맷
    if section.groups:
        items_text = "\n\n".join(
            _format_group(g) for g in section.groups
        )
    else:
        items_text = "\n\n".join(
            _format_article(a) for a in section.articles
        )

    return f"{header}\n{items_text}"


def format_briefing(sections: list[Section], total_collected: int) -> str:
    """전체 브리핑 메시지 생성"""
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

    section_texts = [_format_section(s) for s in sections]

    return header + "\n\n" + "\n\n".join(section_texts)


def split_message(text: str) -> list[str]:
    """텔레그램 4096자 제한에 맞게 메시지 분할

    섹션 경계(\n\n 두 번)에서 나눈다.
    """
    if len(text) <= MAX_MESSAGE_LENGTH:
        return [text]

    messages = []
    current = ""

    # 섹션 단위로 분할 (빈 줄 두 개 = 섹션 구분)
    parts = text.split("\n\n")

    for part in parts:
        candidate = current + ("\n\n" if current else "") + part

        if len(candidate) > MAX_MESSAGE_LENGTH:
            if current:
                messages.append(current)
            current = part
        else:
            current = candidate

    if current:
        messages.append(current)

    return messages


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

    async with httpx.AsyncClient() as client:
        for i, msg in enumerate(messages):
            payload = {
                "chat_id": channel_id,
                "text": msg,
                "disable_web_page_preview": True,
            }

            try:
                response = await client.post(url, json=payload, timeout=30)
                response.raise_for_status()
                data = response.json()

                if not data.get("ok"):
                    logger.error(f"텔레그램 발송 실패 ({i+1}/{len(messages)}): {data}")
                    return False

            except Exception as e:
                logger.error(f"텔레그램 발송 오류 ({i+1}/{len(messages)}): {e}")
                return False

    logger.info(f"텔레그램 발송 완료 ({len(messages)}개 ��시지)")
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
