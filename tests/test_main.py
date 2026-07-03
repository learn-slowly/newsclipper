"""main 모듈 단위 테스트

분류 전멸(성공 0건) 감지 로직을 검증한다.
크레딧 소진·API 장애로 분류가 전부 실패하면 브리핑이 조용히 누락되므로,
관리자 경고 메시지가 만들어지는지가 핵심이다 (2026-07-02 크레딧 소진 사고 재발 방지).
"""

from src.main import build_classify_failure_alert


def test_분류_전멸시_경고_메시지_생성():
    """기사가 있는데 분류 성공이 0건이면 경고 메시지를 만든다"""
    alert = build_classify_failure_alert(total=332, ok=0)

    assert alert is not None
    assert "332" in alert  # 몇 건이 실패했는지 알려준다
    assert "크레딧" in alert  # 가장 흔한 원인을 안내한다


def test_분류_일부_성공시_경고_없음():
    """한 건이라도 분류에 성공했으면 정상 동작 — 경고하지 않는다"""
    assert build_classify_failure_alert(total=300, ok=150) is None
    assert build_classify_failure_alert(total=300, ok=1) is None


def test_기사_0건이면_경고_없음():
    """수집된 기사 자체가 없으면 API 장애가 아니므로 경고하지 않는다"""
    assert build_classify_failure_alert(total=0, ok=0) is None
