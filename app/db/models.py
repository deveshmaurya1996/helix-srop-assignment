from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_tier: Mapped[str] = mapped_column(String(16), default="free")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sessions: Mapped[list["Session"]] = relationship(back_populates="user")


class Session(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user: Mapped["User"] = relationship(back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["Session"] = relationship(back_populates="messages")


class AgentTrace(Base):
    __tablename__ = "agent_traces"

    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    routed_to: Mapped[str] = mapped_column(String(32))
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    retrieved_chunk_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    latency_ms: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IdempotencyEntry(Base):
    """
    Caches prior successful chat responses for safe retries (E1).
    Keyed by hash(Idempotency-Key header) + body fingerprint + stream mode.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("key_hash", "body_fingerprint", "is_sse", name="uq_idem_key_body_stream"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(String(64), index=True)
    body_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    is_sse: Mapped[bool] = mapped_column(default=False)
    json_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    sse_payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Ticket(Base):
    """Support tickets created by the escalation specialist (E2)."""

    __tablename__ = "tickets"

    ticket_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(32), default="normal")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
