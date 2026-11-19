"""Structured standard-library logging with credential-safe exception context."""

from datetime import datetime, timezone
import json
import logging
from logging import LogRecord
from pathlib import PurePath
import traceback
from typing import Any


_CONTEXT_FIELDS = (
    "method",
    "path",
    "status_code",
    "user_id",
    "conversation_id",
    "category",
    "close_code",
    "exception_type",
    "traceback",
)


class JsonLogFormatter(logging.Formatter):
    """Serialize only approved event fields; omit exception messages and headers."""

    def format(self, record: LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            # Messages from libraries can contain request data; use only an
            # explicit application event or the logger name as the event key.
            "event": getattr(record, "event", "library.log"),
        }
        for field in _CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO)
    root.setLevel(min(root.level or logging.INFO, logging.INFO))
    for handler in root.handlers:
        if not isinstance(handler, logging.NullHandler):
            handler.setFormatter(JsonLogFormatter())


def _safe_traceback(exc: BaseException) -> list[dict[str, Any]]:
    return [
        {
            "file": PurePath(frame.filename).name,
            "line": frame.lineno,
            "function": frame.name,
        }
        for frame in traceback.extract_tb(exc.__traceback__)
    ]


def log_exception(
    logger: logging.Logger,
    event: str,
    exc: BaseException,
    **context: Any,
) -> None:
    """Log traceback locations and exception type without the exception text."""
    logger.error(
        event,
        extra={
            "event": event,
            "exception_type": type(exc).__name__,
            "traceback": _safe_traceback(exc),
            **context,
        },
    )
