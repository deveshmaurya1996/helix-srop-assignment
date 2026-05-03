"""List persisted support tickets (E2)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Ticket
from app.db.session import get_db

router = APIRouter(tags=["tickets"])


class TicketOut(BaseModel):
    ticket_id: str
    user_id: str
    session_id: str | None
    summary: str
    priority: str


class TicketListResponse(BaseModel):
    tickets: list[TicketOut]


@router.get("/tickets", response_model=TicketListResponse)
async def list_tickets(
    user_id: str = Query(..., min_length=1, description="Filter by ticket submitter"),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(Ticket).where(Ticket.user_id == user_id).order_by(Ticket.created_at.desc())
    )
    rows = res.scalars().all()
    return TicketListResponse(
        tickets=[
            TicketOut(
                ticket_id=r.ticket_id,
                user_id=r.user_id,
                session_id=r.session_id,
                summary=r.summary,
                priority=r.priority,
            )
            for r in rows
        ]
    )
