"""
Request-scoped context for tools that need DB / session metadata (E2 escalation).

Contextvars follow the running asyncio Task — set in `pipeline.run` / `run_stream`
around ADK execution so sync tool functions can `flush()` without passing db through ADK.
"""
from __future__ import annotations

import contextvars

from sqlalchemy.ext.asyncio import AsyncSession

db_session_var: contextvars.ContextVar[AsyncSession | None] = contextvars.ContextVar(
    "db_session", default=None
)
session_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "chat_session_id", default=None
)
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "chat_user_id", default=None
)


def bind(
    db: AsyncSession, session_id: str, user_id: str
) -> tuple[contextvars.Token, contextvars.Token, contextvars.Token]:
    return (
        db_session_var.set(db),
        session_id_var.set(session_id),
        user_id_var.set(user_id),
    )


def unbind(
    t_db: contextvars.Token,
    t_sid: contextvars.Token,
    t_uid: contextvars.Token,
) -> None:
    user_id_var.reset(t_uid)
    session_id_var.reset(t_sid)
    db_session_var.reset(t_db)


def get_bound_db() -> AsyncSession | None:
    return db_session_var.get()


def get_bound_session_id() -> str | None:
    return session_id_var.get()


def get_bound_user_id() -> str | None:
    return user_id_var.get()
