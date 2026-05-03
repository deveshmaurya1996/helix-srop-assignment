from __future__ import annotations

from pydantic import BaseModel, Field


class SessionState(BaseModel):
    user_id: str
    plan_tier: str = Field(default="free")
    last_agent: str | None = None  # knowledge | account | smalltalk
    turn_count: int = 0

    def to_db_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_db_dict(cls, data: dict) -> SessionState:
        return cls.model_validate({**{"plan_tier": "free", "turn_count": 0}, **data})
