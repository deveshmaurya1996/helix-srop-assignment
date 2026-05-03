"""
POST /v1/chat/{session_id} — send a user message, get assistant reply.

JSON by default. With header ``Accept: text/event-stream``, streams SSE (extension E3).

``Idempotency-Key`` (E1): retry-safe replays return the same payload without duplicating
messages when the request body matches.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.db.session import get_db
from app.services import idempotency as idem_svc
from app.settings import settings
from app.srop import pipeline

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    content: str


class ChatResponse(BaseModel):
    reply: str
    routed_to: str  # which sub-agent handled this turn
    trace_id: str


def _wants_sse(accept: str | None) -> bool:
    if not accept:
        return False
    return "text/event-stream" in accept.lower()


@router.post("/chat/{session_id}", response_model=None)
async def chat(
    session_id: str,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    accept: str | None = Header(default=None, alias="Accept"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """
    Run one turn of the SROP pipeline.

    Error cases:
    - Session not found → 404
    - LLM timeout → 504

    **SSE:** send ``Accept: text/event-stream`` to receive ``data:`` JSON lines
    (``delta`` chunks, then ``done`` with trace metadata).

    **Idempotency:** optional ``Idempotency-Key`` header replays a prior successful response
    when the session id and message body are unchanged.
    """
    wants_sse = _wants_sse(accept)

    if idempotency_key and settings.idempotency_enabled:
        cached = await idem_svc.get_cached_response(
            db, idempotency_key, session_id, body.content, wants_sse
        )
        if isinstance(cached, dict):
            return ChatResponse(
                reply=cached["reply"],
                routed_to=cached["routed_to"],
                trace_id=cached["trace_id"],
            )
        if isinstance(cached, (bytes, bytearray)):

            async def _replay() -> AsyncIterator[bytes]:
                yield bytes(cached)

            return StreamingResponse(
                _replay(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

    if wants_sse:

        async def sse_body() -> AsyncIterator[bytes]:
            buf: list[bytes] = []
            async for part in pipeline.run_stream(session_id, body.content, db):
                buf.append(part)
                yield part
            if idempotency_key and settings.idempotency_enabled and buf:
                try:
                    await idem_svc.save_sse_payload(
                        db,
                        idempotency_key,
                        session_id,
                        body.content,
                        b"".join(buf),
                    )
                    await db.commit()
                except IntegrityError:
                    await db.rollback()

        return StreamingResponse(
            sse_body(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    result = await pipeline.run(session_id, body.content, db)
    payload = {
        "reply": result.content,
        "routed_to": result.routed_to,
        "trace_id": result.trace_id,
    }
    if idempotency_key and settings.idempotency_enabled:
        try:
            await idem_svc.save_json_response(
                db, idempotency_key, session_id, body.content, payload
            )
            await db.commit()
        except IntegrityError:
            await db.rollback()
    return ChatResponse(**payload)
