from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.adk_runner import AdkTurnResult, execute_turn, execute_turn_stream
from app.api.errors import SessionNotFoundError, UpstreamTimeoutError
from app.db import tool_context
from app.db.models import AgentTrace, Message
from app.db.models import Session as DbSession
from app.guardrails.policies import evaluate_user_message
from app.settings import settings
from app.srop.state import SessionState


@dataclass
class PipelineResult:
    content: str
    routed_to: str
    trace_id: str


def _json_safe_tool_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = json.dumps(calls, default=str)
    return json.loads(raw)


async def run(session_id: str, user_message: str, db: AsyncSession) -> PipelineResult:
    trace_id = str(uuid.uuid4())

    res = await db.execute(select(DbSession).where(DbSession.session_id == session_id))
    row = res.scalar_one_or_none()
    if row is None:
        raise SessionNotFoundError(f"No session with id {session_id}")

    state = SessionState.from_db_dict(row.state)

    user_mid = str(uuid.uuid4())
    db.add(
        Message(
            message_id=user_mid,
            session_id=session_id,
            role="user",
            content=user_message,
            trace_id=trace_id,
        )
    )

    await db.flush()

    gr = evaluate_user_message(user_message)
    if not gr.allowed:
        refusal = gr.refusal_message or "I cannot help with that request."
        latency_ms = 0
        state.turn_count += 1
        state.last_agent = "guardrails"
        row.state = state.to_db_dict()
        db.add(
            AgentTrace(
                trace_id=trace_id,
                session_id=session_id,
                routed_to="guardrails",
                tool_calls=[],
                retrieved_chunk_ids=[],
                latency_ms=latency_ms,
            )
        )
        assist_mid = str(uuid.uuid4())
        db.add(
            Message(
                message_id=assist_mid,
                session_id=session_id,
                role="assistant",
                content=refusal,
                trace_id=trace_id,
            )
        )
        await db.commit()
        return PipelineResult(content=refusal, routed_to="guardrails", trace_id=trace_id)

    t0 = time.perf_counter()
    t_db, t_sid, t_uid = tool_context.bind(db, session_id, state.user_id)
    try:
        adk: AdkTurnResult = await execute_turn(session_id, user_message, state)
    finally:
        tool_context.unbind(t_db, t_sid, t_uid)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    state.turn_count += 1
    state.last_agent = adk.routed_to
    row.state = state.to_db_dict()

    db.add(
        AgentTrace(
            trace_id=trace_id,
            session_id=session_id,
            routed_to=adk.routed_to,
            tool_calls=_json_safe_tool_calls(adk.tool_calls),
            retrieved_chunk_ids=adk.retrieved_chunk_ids,
            latency_ms=latency_ms,
        )
    )

    assist_mid = str(uuid.uuid4())
    db.add(
        Message(
            message_id=assist_mid,
            session_id=session_id,
            role="assistant",
            content=adk.reply,
            trace_id=trace_id,
        )
    )

    await db.commit()

    return PipelineResult(content=adk.reply, routed_to=adk.routed_to, trace_id=trace_id)


def _sse_data_line(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, default=str)}\n\n".encode()


async def run_stream(
    session_id: str, user_message: str, db: AsyncSession
) -> AsyncIterator[bytes]:
    """
    Same persistence contract as run(), but streams assistant text as SSE.

    Each event is one SSE `data:` line (JSON). Types:
    - `delta`: partial assistant text
    - `done`: final reply + routing + trace_id (after DB commit)
    """
    trace_id = str(uuid.uuid4())

    res = await db.execute(select(DbSession).where(DbSession.session_id == session_id))
    row = res.scalar_one_or_none()
    if row is None:
        raise SessionNotFoundError(f"No session with id {session_id}")

    state = SessionState.from_db_dict(row.state)

    user_mid = str(uuid.uuid4())
    db.add(
        Message(
            message_id=user_mid,
            session_id=session_id,
            role="user",
            content=user_message,
            trace_id=trace_id,
        )
    )

    await db.flush()

    gr = evaluate_user_message(user_message)
    if not gr.allowed:
        refusal = gr.refusal_message or "I cannot help with that request."
        step = 48
        for i in range(0, len(refusal), step):
            yield _sse_data_line({"type": "delta", "text": refusal[i : i + step]})
        latency_ms = 0
        state.turn_count += 1
        state.last_agent = "guardrails"
        row.state = state.to_db_dict()
        db.add(
            AgentTrace(
                trace_id=trace_id,
                session_id=session_id,
                routed_to="guardrails",
                tool_calls=[],
                retrieved_chunk_ids=[],
                latency_ms=latency_ms,
            )
        )
        assist_mid = str(uuid.uuid4())
        db.add(
            Message(
                message_id=assist_mid,
                session_id=session_id,
                role="assistant",
                content=refusal,
                trace_id=trace_id,
            )
        )
        await db.commit()
        yield _sse_data_line(
            {
                "type": "done",
                "reply": refusal,
                "routed_to": "guardrails",
                "trace_id": trace_id,
            }
        )
        return

    t0 = time.perf_counter()
    adk: AdkTurnResult | None = None

    t_db, t_sid, t_uid = tool_context.bind(db, session_id, state.user_id)
    try:
        try:
            async with asyncio.timeout(float(settings.llm_timeout_seconds)):
                async for kind, payload in execute_turn_stream(session_id, user_message, state):
                    if kind == "delta":
                        yield _sse_data_line({"type": "delta", "text": payload})
                    elif kind == "complete":
                        adk = payload
        except TimeoutError as exc:
            raise UpstreamTimeoutError(
                f"LLM did not respond within {settings.llm_timeout_seconds}s"
            ) from exc
    finally:
        tool_context.unbind(t_db, t_sid, t_uid)

    if adk is None:
        raise RuntimeError("ADK stream finished without a complete result")

    latency_ms = int((time.perf_counter() - t0) * 1000)

    state.turn_count += 1
    state.last_agent = adk.routed_to
    row.state = state.to_db_dict()

    db.add(
        AgentTrace(
            trace_id=trace_id,
            session_id=session_id,
            routed_to=adk.routed_to,
            tool_calls=_json_safe_tool_calls(adk.tool_calls),
            retrieved_chunk_ids=adk.retrieved_chunk_ids,
            latency_ms=latency_ms,
        )
    )

    assist_mid = str(uuid.uuid4())
    db.add(
        Message(
            message_id=assist_mid,
            session_id=session_id,
            role="assistant",
            content=adk.reply,
            trace_id=trace_id,
        )
    )

    await db.commit()

    yield _sse_data_line(
        {
            "type": "done",
            "reply": adk.reply,
            "routed_to": adk.routed_to,
            "trace_id": trace_id,
        }
    )
