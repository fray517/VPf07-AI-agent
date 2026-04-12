"""Настройка логирования: файл + stderr, уровень из LOG_LEVEL."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from agent.paths import agent_data_dir


def configure_logging() -> None:
    """Читает LOG_LEVEL и LOG_FILE из окружения (после load_dotenv)."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    log_file = os.environ.get("LOG_FILE", "").strip()
    if log_file:
        path = Path(log_file)
    else:
        path = agent_data_dir() / "agent.log"

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt=datefmt)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    fh = RotatingFileHandler(
        path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(formatter)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(level)
    sh.setFormatter(formatter)
    root.addHandler(sh)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.INFO)
    logging.getLogger("langchain").setLevel(logging.INFO)
    logging.getLogger("langgraph").setLevel(logging.INFO)
