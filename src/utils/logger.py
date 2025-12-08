"""로깅 설정 모듈"""

import sys
from pathlib import Path
from loguru import logger


def setup_logger(log_level: str = "INFO", log_file: Path = None) -> None:
    """로거 설정
    
    Args:
        log_level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR)
        log_file: 로그 파일 경로 (선택)
    """
    # 기본 핸들러 제거
    logger.remove()
    
    # 콘솔 출력 설정
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True
    )
    
    # 파일 출력 설정 (선택)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_file,
            level=log_level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            rotation="1 day",
            retention="7 days",
            encoding="utf-8"
        )


def get_logger():
    """로거 인스턴스 반환"""
    return logger

