"""Idempotency for chat completion (E1) — safe retries without duplicate side effects."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IdempotencyEntry
from app.settings import settings


def _hash_key(header_value: str) -> str:
    return hashlib.sha256(header_value.strip().encode("utf-8")).hexdigest()


def body_fingerprint(session_id: str, content: str, wants_sse: bool) -> str:
    raw = f"{session_id}\n{content}\n{'sse' if wants_sse else 'json'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def get_cached_response(
    db: AsyncSession,
    idempotency_key: str,
    session_id: str,
    content: str,
    wants_sse: bool,
) -> dict[str, Any] | bytes | None:
    if not settings.idempotency_enabled:
        return None
    kh = _hash_key(idempotency_key)
    fp = body_fingerprint(session_id, content, wants_sse)
    res = await db.execute(
        select(IdempotencyEntry).where(
            IdempotencyEntry.key_hash == kh,
            IdempotencyEntry.body_fingerprint == fp,
            IdempotencyEntry.is_sse == wants_sse,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        return None
    if wants_sse and row.sse_payload:
        return row.sse_payload
    if not wants_sse and row.json_payload:
        return json.loads(row.json_payload)
    return None


async def save_json_response(
    db: AsyncSession,
    idempotency_key: str,
    session_id: str,
    content: str,
    payload: dict[str, Any],
) -> None:
    if not settings.idempotency_enabled:
        return
    kh = _hash_key(idempotency_key)
    fp = body_fingerprint(session_id, content, False)
    row = IdempotencyEntry(
        key_hash=kh,
        body_fingerprint=fp,
        is_sse=False,
        json_payload=json.dumps(payload, default=str),
        sse_payload=None,
    )
    db.add(row)
    await db.flush()


async def save_sse_payload(
    db: AsyncSession,
    idempotency_key: str,
    session_id: str,
    content: str,
    sse_bytes: bytes,
) -> None:
    if not settings.idempotency_enabled:
        return
    kh = _hash_key(idempotency_key)
    fp = body_fingerprint(session_id, content, True)
    row = IdempotencyEntry(
        key_hash=kh,
        body_fingerprint=fp,
        is_sse=True,
        json_payload=None,
        sse_payload=sse_bytes,
    )
    db.add(row)
    await db.flush()
