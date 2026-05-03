"""POST /v1/sessions: create user row, new session, initial ``SessionState`` JSON."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Session as DbSession
from app.db.models import User
from app.db.session import get_db
from app.srop.state import SessionState

router = APIRouter(tags=["sessions"])


class CreateSessionRequest(BaseModel):
    user_id: str
    plan_tier: str = Field(default="free")


class CreateSessionResponse(BaseModel):
    session_id: str
    user_id: str


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(
    body: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
) -> CreateSessionResponse:
    session_id = str(uuid.uuid4())

    res = await db.execute(select(User).where(User.user_id == body.user_id))
    user = res.scalar_one_or_none()
    if user:
        user.plan_tier = body.plan_tier
    else:
        db.add(User(user_id=body.user_id, plan_tier=body.plan_tier))

    state = SessionState(user_id=body.user_id, plan_tier=body.plan_tier, turn_count=0)
    db.add(
        DbSession(
            session_id=session_id,
            user_id=body.user_id,
            state=state.to_db_dict(),
        )
    )
    await db.commit()

    return CreateSessionResponse(session_id=session_id, user_id=body.user_id)
