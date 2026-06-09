from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

_SENSITIVE_QUERY_PARAM_RE = re.compile(
    r"([?&](?:api[_-]?key|access[_-]?token|token|client[_-]?secret|secret|password)=)[^&\s\"']+",
    re.IGNORECASE,
)


def _redact_log_message(message: str) -> str:
    return _SENSITIVE_QUERY_PARAM_RE.sub(r"\1[REDACTED]", message)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": _redact_log_message(record.getMessage()),
        }
        if hasattr(record, "request_id"):
            payload["request_id"] = record.request_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
