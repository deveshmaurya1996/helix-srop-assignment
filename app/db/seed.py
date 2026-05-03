"""Load demo rows into SQLite for manual API checks (idempotent)."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentTrace, Message, Ticket, User
from app.db.models import Session as DbSession
from app.db.session import AsyncSessionLocal, init_db
from app.srop.state import SessionState

SEED_USER_ID = "demo_user"
SEED_SESSION_ID = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
SEED_TRACE_ID = "b1eebc99-9c0b-4ef8-bb6d-6bb9bd380a22"


async def _seed(db: AsyncSession) -> bool:
    existing = await db.execute(select(DbSession).where(DbSession.session_id == SEED_SESSION_ID))
    if existing.scalar_one_or_none() is not None:
        return False

    res = await db.execute(select(User).where(User.user_id == SEED_USER_ID))
    user = res.scalar_one_or_none()
    if user is None:
        db.add(User(user_id=SEED_USER_ID, plan_tier="pro"))
    else:
        user.plan_tier = "pro"

    state = SessionState(
        user_id=SEED_USER_ID,
        plan_tier="pro",
        last_agent="knowledge",
        turn_count=2,
    )
    db.add(
        DbSession(
            session_id=SEED_SESSION_ID,
            user_id=SEED_USER_ID,
            state=state.to_db_dict(),
        )
    )

    db.add(
        Message(
            message_id=str(uuid.uuid4()),
            session_id=SEED_SESSION_ID,
            role="user",
            content="How do I rotate a deploy key?",
            trace_id=None,
        )
    )
    db.add(
        Message(
            message_id=str(uuid.uuid4()),
            session_id=SEED_SESSION_ID,
            role="assistant",
            content="You can rotate deploy keys in Settings → SSH and GPG keys.",
            trace_id=SEED_TRACE_ID,
        )
    )

    db.add(
        AgentTrace(
            trace_id=SEED_TRACE_ID,
            session_id=SEED_SESSION_ID,
            routed_to="knowledge",
            tool_calls=[
                {
                    "tool_name": "search_docs",
                    "args": {"query": "deploy key"},
                    "result": None,
                }
            ],
            retrieved_chunk_ids=["chunk_demo_01", "chunk_demo_02"],
            latency_ms=120,
        )
    )

    db.add(
        Ticket(
            ticket_id=str(uuid.uuid4()),
            user_id=SEED_USER_ID,
            session_id=SEED_SESSION_ID,
            summary="Billing shows duplicate charge for March",
            priority="high",
        )
    )
    db.add(
        Ticket(
            ticket_id=str(uuid.uuid4()),
            user_id=SEED_USER_ID,
            session_id=SEED_SESSION_ID,
            summary="Cannot connect CI pipeline to registry",
            priority="normal",
        )
    )

    await db.commit()
    return True


async def run_seed() -> None:
    await init_db()
    async with AsyncSessionLocal() as db:
        inserted = await _seed(db)
    if not inserted:
        print("Seed session already exists; nothing to do.")
    else:
        print("Seed complete.")
    print(f"  user_id:      {SEED_USER_ID}")
    print(f"  session_id: {SEED_SESSION_ID}")
    print(f"  trace_id:    {SEED_TRACE_ID}")
    print("Examples:")
    print(f"  curl http://127.0.0.1:8000/v1/tickets?user_id={SEED_USER_ID}")
    print(f"  curl http://127.0.0.1:8000/v1/traces/{SEED_TRACE_ID}")
    print(
        "  curl -s -X POST http://127.0.0.1:8000/v1/chat/"
        f"{SEED_SESSION_ID} -H 'Content-Type: application/json' "
        "-d '{\"content\":\"What is my plan tier?\"}'"
    )


def main() -> None:
    asyncio.run(run_seed())


if __name__ == "__main__":
    main()
