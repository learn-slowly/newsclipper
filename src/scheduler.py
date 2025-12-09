"""
스케줄러 모듈

뉴스 클리핑을 정해진 시간에 자동 실행
"""

import signal
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from main import run_news_clipper
from utils.config import get_settings
from utils.logger import setup_logger


def signal_handler(signum, frame):
    """종료 시그널 핸들러"""
    logger.info("종료 시그널 수신, 스케줄러 종료 중...")
    sys.exit(0)


def run_scheduler():
    """스케줄러 실행"""
    
    # 설정 로드
    settings = get_settings()
    config = settings.load_config()
    schedule_config = config.get("schedule", {})
    
    # 로거 설정
    setup_logger(log_level=settings.log_level)
    
    logger.info("=" * 60)
    logger.info("🕐 뉴스 클리핑 스케줄러 시작")
    logger.info("=" * 60)
    
    # 스케줄 시간 파싱
    morning_time = schedule_config.get("morning_run", "10:00")
    morning_hours = schedule_config.get("morning_hours", 16)
    evening_time = schedule_config.get("evening_run", "18:00")
    evening_hours = schedule_config.get("evening_hours", 8)
    timezone = schedule_config.get("timezone", "Asia/Seoul")
    
    morning_hour, morning_minute = map(int, morning_time.split(":"))
    evening_hour, evening_minute = map(int, evening_time.split(":"))
    
    logger.info(f"⏰ 오전 실행: {morning_time} (최근 {morning_hours}시간 뉴스)")
    logger.info(f"⏰ 오후 실행: {evening_time} (최근 {evening_hours}시간 뉴스)")
    logger.info(f"🌍 시간대: {timezone}")
    
    # 스케줄러 생성
    scheduler = BlockingScheduler(timezone=timezone)
    
    # 오전 스케줄 등록
    scheduler.add_job(
        run_news_clipper,
        CronTrigger(hour=morning_hour, minute=morning_minute),
        id="morning_clipper",
        name="오전 뉴스 클리핑",
        misfire_grace_time=3600
    )
    
    # 오후 스케줄 등록
    scheduler.add_job(
        run_news_clipper,
        CronTrigger(hour=evening_hour, minute=evening_minute),
        id="evening_clipper",
        name="오후 뉴스 클리핑",
        misfire_grace_time=3600
    )
    
    # 종료 시그널 핸들러 등록
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("✅ 스케줄러 등록 완료")
    logger.info("💡 Ctrl+C로 종료")
    
    # 다음 실행 시간 출력
    jobs = scheduler.get_jobs()
    for job in jobs:
        next_run = job.next_run_time
        if next_run:
            logger.info(f"📅 다음 실행: {job.name} - {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("스케줄러 종료됨")


if __name__ == "__main__":
    run_scheduler()

