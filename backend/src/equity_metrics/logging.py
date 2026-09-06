"""Structured logging.

Logs are emitted as one JSON object per line so a log collector can read them
without parsing prose. Everything goes to stderr, which keeps stdout free for
the MCP stdio transport.
"""

import datetime as dt
import json
import logging
import sys
from typing import Any

# Attributes LogRecord always carries; anything else was added by the caller and
# is worth forwarding as structured context.
_STANDARD_FIELDS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": dt.datetime.fromtimestamp(record.created, dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_FIELDS:
                payload[key] = _safe(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger, replacing any handlers."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Uvicorn installs its own handlers; let them fall through to ours so the
    # whole process emits one format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True


def _safe(value: Any) -> Any:
    """Keep JSON-native values as they are; render anything else as text."""
    if isinstance(value, str | int | float | bool | type(None) | list | dict):
        return value
    return str(value)
