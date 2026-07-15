"""Structlog setup — JSON logs to file, per SPEC.md section 3."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog


def configure_logging(log_path: Path = Path("./data/gateway.log")) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    logging.getLogger().addHandler(file_handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
