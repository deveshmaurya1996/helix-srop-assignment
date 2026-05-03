"""Lightweight input guardrails for support-bot abuse cases (E5)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.settings import settings

REFUSAL_COPY = (
    "I can only help with Helix product support and account questions on this channel. "
    "Please rephrase your question, or contact security@helix.example if you believe "
    "this was blocked in error."
)

_BLOCKED_SUBSTRINGS = (
    "ignore all previous",
    "ignore previous instructions",
    "you are now",
    "developer mode",
    "show system prompt",
    "reveal your instructions",
    "jailbreak",
    "dan mode",
    "execute shell",
    "rm -rf",
    "curl ",
    "wget ",
)

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_PHONE_RE = re.compile(r"\b\+?\d[\d\s\-().]{8,}\d\b")


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool
    refusal_message: str | None = None


def evaluate_user_message(text: str) -> GuardrailResult:
    if not settings.guardrails_enabled:
        return GuardrailResult(allowed=True)
    t = (text or "").strip().lower()
    if len(t) > 8000:
        return GuardrailResult(allowed=False, refusal_message=REFUSAL_COPY)
    for sub in _BLOCKED_SUBSTRINGS:
        if sub in t:
            return GuardrailResult(allowed=False, refusal_message=REFUSAL_COPY)
    return GuardrailResult(allowed=True)


def redact_pii_for_logs(text: str) -> str:
    """Best-effort masking for log sinks (E5)."""
    if not text:
        return text
    s = _EMAIL_RE.sub("[email-redacted]", text)
    s = _PHONE_RE.sub("[phone-redacted]", s)
    return s
