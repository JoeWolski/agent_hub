from __future__ import annotations

import logging
import re
import sys
from collections.abc import Callable, Mapping
from typing import Any


_REDACT_PATTERN = re.compile(r"(?i)(authorization|token|api_key|password)=([^\s,;]+)")


class StructuredLogDefaultsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        defaults: dict[str, Any] = {
            "request_id": "",
            "project_id": "",
            "chat_id": "",
            "component": "",
            "operation": "",
            "result": "",
            "duration_ms": 0,
            "error_class": "",
        }
        for key, value in defaults.items():
            if not hasattr(record, key):
                setattr(record, key, value)
        try:
            message = record.getMessage()
        except Exception:
            return True
        lowered = message.lower()
        if any(secret_key in lowered for secret_key in ("authorization", "token", "api_key", "password")):
            record.msg = _REDACT_PATTERN.sub(r"\1=[redacted]", message)
            record.args = ()
        return True


def configure_structured_logger(logger: logging.Logger, *, level: str) -> None:
    handler = logging.StreamHandler(sys.__stderr__)
    handler.addFilter(StructuredLogDefaultsFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: "
            "request_id=%(request_id)s project_id=%(project_id)s chat_id=%(chat_id)s "
            "component=%(component)s operation=%(operation)s result=%(result)s "
            "duration_ms=%(duration_ms)s error_class=%(error_class)s %(message)s"
        )
    )
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, str(level or "info").upper(), logging.INFO))
    logger.propagate = False


def configure_domain_log_levels(
    *,
    domains: Mapping[str, Any] | None,
    logger_prefix: str,
    normalize_level: Callable[[Any], str],
) -> None:
    if not isinstance(domains, Mapping):
        return
    for domain, level_value in domains.items():
        normalized_domain = str(domain or "").strip().lower()
        if not normalized_domain:
            continue
        level = normalize_level(level_value)
        logging.getLogger(f"{logger_prefix}.{normalized_domain}").setLevel(
            getattr(logging, level.upper(), logging.INFO)
        )

