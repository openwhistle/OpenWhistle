"""Logging configuration — JSON or plain-text based on LOG_FORMAT env var."""

from __future__ import annotations

import logging
import logging.config
from typing import Any


def configure_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """Set up root logger and uvicorn loggers with the chosen format."""
    fmt_class = (
        "pythonjsonlogger.json.JsonFormatter"
        if log_format.lower() == "json"
        else "logging.Formatter"
    )
    fmt_string = (
        "%(asctime)s %(levelname)s %(name)s %(message)s"
        if log_format.lower() == "json"
        else "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": fmt_class,
                "fmt": fmt_string,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "handlers": ["console"],
            "level": log_level.upper(),
        },
        "loggers": {
            "uvicorn": {"handlers": ["console"], "level": log_level.upper(), "propagate": False},
            "uvicorn.error": {
                "handlers": ["console"],
                "level": log_level.upper(),
                "propagate": False,
            },
            # No handler and no propagation: uvicorn writes a request line only
            # when this logger ``hasHandlers()``. It used to get the console
            # handler here, which re-enabled the access log that the image's
            # ``--no-access-log`` had switched off, and put every path and
            # query string (setup token, OIDC code, case pages) into stdout.
            "uvicorn.access": {"handlers": [], "propagate": False},
        },
    }
    logging.config.dictConfig(config)
