"""
Structured logging setup.

All log lines must include session_id, trace_id, user_id when available.
Use structlog's context vars for request-scoped fields.
"""
import logging
import sys

import structlog

from app.guardrails.policies import redact_pii_for_logs

_SENSITIVE_KEYS = frozenset(
    {"content", "message", "user_message", "reply", "text", "body", "prompt"}
)


def _scrub_pii_processor(_logger: object, _method: str, event_dict: dict) -> dict:
    for key in list(event_dict.keys()):
        if key in _SENSITIVE_KEYS and isinstance(event_dict[key], str):
            event_dict[key] = redact_pii_for_logs(event_dict[key])
    return event_dict


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _scrub_pii_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
    )


# Usage in request handlers:
#   import structlog
#   log = structlog.get_logger()
#   structlog.contextvars.bind_contextvars(session_id=session_id, trace_id=trace_id)
#   log.info("pipeline_started", user_message_len=len(message))
