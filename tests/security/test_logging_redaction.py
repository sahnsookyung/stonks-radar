from __future__ import annotations

import json
import logging

from frw_api.core.logging import JsonFormatter, configure_logging


def test_json_formatter_redacts_sensitive_query_params() -> None:
    record = logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        'HTTP Request: GET "https://api.example.test/time_series?symbol=AAPL&apikey=secret123&client_secret=shh"',
        (),
        None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert "secret123" not in payload["message"]
    assert "shh" not in payload["message"]
    assert "symbol=AAPL" in payload["message"]
    assert "apikey=[REDACTED]" in payload["message"]
    assert "client_secret=[REDACTED]" in payload["message"]


def test_configure_logging_suppresses_http_client_info_logs() -> None:
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_root_level = root.level
    httpx_logger = logging.getLogger("httpx")
    httpcore_logger = logging.getLogger("httpcore")
    old_httpx_level = httpx_logger.level
    old_httpcore_level = httpcore_logger.level

    try:
        configure_logging()

        assert root.level == logging.INFO
        assert httpx_logger.level == logging.WARNING
        assert httpcore_logger.level == logging.WARNING
    finally:
        root.handlers.clear()
        root.handlers.extend(old_handlers)
        root.setLevel(old_root_level)
        httpx_logger.setLevel(old_httpx_level)
        httpcore_logger.setLevel(old_httpcore_level)
