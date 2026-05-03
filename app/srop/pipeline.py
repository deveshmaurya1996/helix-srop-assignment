from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.adk_runner import AdkTurnResult, execute_turn
from app.api.errors import SessionNotFoundError
from app.db.models import AgentTrace, Message
from app.db.models import Session as DbSession
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

    t0 = time.perf_counter()
    adk: AdkTurnResult = await execute_turn(session_id, user_message, state)
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
