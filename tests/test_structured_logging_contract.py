from __future__ import annotations

import io
import logging

import agent_hub.server as hub_server


REQUIRED_KEYS = (
    "request_id",
    "project_id",
    "chat_id",
    "component",
    "operation",
    "result",
    "duration_ms",
    "error_class",
)


def test_structured_log_filter_injects_required_defaults() -> None:
    record = logging.LogRecord(
        name="agent_hub",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )

    filter_obj = hub_server._StructuredLogDefaultsFilter()
    assert filter_obj.filter(record) is True
    for key in REQUIRED_KEYS:
        assert hasattr(record, key)


def test_configured_hub_logging_formatter_emits_required_fields() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(hub_server._StructuredLogDefaultsFilter())
    handler.setFormatter(
        logging.Formatter(
            "request_id=%(request_id)s project_id=%(project_id)s chat_id=%(chat_id)s "
            "component=%(component)s operation=%(operation)s result=%(result)s "
            "duration_ms=%(duration_ms)s error_class=%(error_class)s %(message)s"
        )
    )

    logger = logging.getLogger("agent_hub.structured_contract_test")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.info("event", extra={"component": "runtime", "operation": "start", "result": "ok", "duration_ms": 12})
    text = stream.getvalue()
    for key in REQUIRED_KEYS:
        assert f"{key}=" in text
    assert "component=runtime" in text
    assert "operation=start" in text
    assert "result=ok" in text
    assert "duration_ms=12" in text
