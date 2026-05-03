"""Pydantic model for `sessions.state` JSON — persisted durable session for ADK instructions."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SessionState(BaseModel):
    user_id: str
    plan_tier: str = Field(default="free")
    # Last routing bucket we attribute after a turn (includes escalation, guardrails, smalltalk)
    last_agent: str | None = None
    turn_count: int = 0

    def to_db_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_db_dict(cls, data: dict) -> SessionState:
        return cls.model_validate({**{"plan_tier": "free", "turn_count": 0}, **data})
