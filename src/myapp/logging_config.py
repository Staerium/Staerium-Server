"""Logging setup helpers for Staerium Server."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)s: %(message)s"
_DEBUG_LOG_FORMAT = "%(asctime)s %(levelname)s %(funcName)s %(filename)s:%(lineno)d: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _resolve_level(debug: bool) -> int:
    level_name = os.getenv("LOG_LEVEL")
    if level_name:
        level = logging.getLevelName(level_name.upper())
        if isinstance(level, int):
            return level
    return logging.DEBUG if debug else logging.INFO


def setup_logging(*, debug: bool = False) -> None:
    """Configure root logging with stdout and rotating file handlers."""

    level = _resolve_level(debug)
    format_string = _DEBUG_LOG_FORMAT if debug else _LOG_FORMAT
    formatter = logging.Formatter(fmt=format_string, datefmt=_DATE_FORMAT)

    stream_handler = logging.StreamHandler(stream=sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)

    log_dir = Path(os.getenv("LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "staerium-server.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)
