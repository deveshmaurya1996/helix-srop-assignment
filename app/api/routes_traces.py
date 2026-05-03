
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import TraceNotFoundError
from app.db.models import AgentTrace
from app.db.session import get_db

router = APIRouter(tags=["traces"])


class ToolCallRecord(BaseModel):
    tool_name: str
    args: dict[str, Any]
    result: Any | None


class TraceResponse(BaseModel):
    trace_id: str
    session_id: str
    routed_to: str
    tool_calls: list[ToolCallRecord]
    retrieved_chunk_ids: list[str]
    latency_ms: int


@router.get("/traces/{trace_id}", response_model=TraceResponse)
async def get_trace(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
) -> TraceResponse:
    """Return trace for one turn. 404 if not found."""
    res = await db.execute(select(AgentTrace).where(AgentTrace.trace_id == trace_id))
    row = res.scalar_one_or_none()
    if row is None:
        raise TraceNotFoundError(f"No trace with id {trace_id}")

    tools = [
        ToolCallRecord(
            tool_name=str(t.get("tool_name", "")),
            args=dict(t.get("args") or {}),
            result=t.get("result"),
        )
        for t in (row.tool_calls or [])
    ]

    return TraceResponse(
        trace_id=row.trace_id,
        session_id=row.session_id,
        routed_to=row.routed_to,
        tool_calls=tools,
        retrieved_chunk_ids=list(row.retrieved_chunk_ids or []),
        latency_ms=row.latency_ms,
    )
