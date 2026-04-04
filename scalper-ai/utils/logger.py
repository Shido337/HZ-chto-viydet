from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


def setup_logger() -> None:
    """Configure Loguru with console + file rotation."""
    Path("logs").mkdir(exist_ok=True)
    logger.remove()
    logger.add(
        sys.stderr,
        level=LOG_LEVEL,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}",
    )
    logger.add(
        "logs/scalper_{time:YYYY-MM-DD}.log",
        rotation="50 MB",
        retention="7 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {name}:{line} | {message}",
    )
