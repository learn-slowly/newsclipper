"""clipboard055 — 정의당 경남도당 일일 뉴스 브리핑 자동화 시스템"""

# ── 본문 미확인 처리 상수 ─────────────────────────
# AI에 넘기는 본문(title + summary 또는 summary or title)이 이 길이 미만이면
# 환각 방지를 위해 분류 단계에서는 가드 프롬프트를 추가하고,
# 요약 단계에서는 Sonnet 호출을 스킵한다.
MIN_CONTENT_LENGTH = 80

# 텔레그램 발송 시 본문 미확인 기사 앞에 붙는 마커
LOW_CONTENT_MARKER = "[본문 미확인]"
