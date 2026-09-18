"""UTC structured JSON logging setup shared by all Telemetria processes.

Call ``configure_logging(settings)`` once at process startup, before any
other log output. All timestamps are UTC; ``asctime`` uses ISO-8601 with a
trailing ``Z``. Output is newline-delimited JSON via ``python-json-logger``.
"""

from __future__ import annotations

import logging
import logging.config
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telemetria.config import CommonSettings


def configure_logging(settings: CommonSettings, process_name: str) -> None:
    """Configure root logger for *process_name* using *settings*."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {
                    "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                    "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%SZ",
                },
            },
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "json",
                },
            },
            "root": {
                "level": settings.log_level,
                "handlers": ["stdout"],
            },
        }
    )
    logging.Formatter.converter = time.gmtime  # ensure UTC for asctime

    logging.getLogger(__name__).debug(
        "Logging configured",
        extra={"process": process_name, "level": settings.log_level},
    )
