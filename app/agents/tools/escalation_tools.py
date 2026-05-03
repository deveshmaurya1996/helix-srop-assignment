"""Create support tickets from the escalation specialist (E2)."""
from __future__ import annotations

import uuid

from app.db.models import Ticket
from app.db.tool_context import get_bound_db, get_bound_session_id, get_bound_user_id


async def create_ticket(summary: str, priority: str = "normal") -> dict[str, str]:
    """
    Persist a human-support ticket. Called only when the user explicitly wants
    escalation (billing disputes, account lockouts, legal, abuse).
    """
    db = get_bound_db()
    user_id = get_bound_user_id()
    session_id = get_bound_session_id()
    if db is None or user_id is None:
        return {
            "ok": "false",
            "error": "ticket_context_missing",
            "message": "Unable to create ticket (missing session context).",
        }

    sid = (summary or "").strip()
    if not sid:
        return {"ok": "false", "error": "empty_summary"}

    pr = (priority or "normal").strip().lower()
    if pr not in ("low", "normal", "high", "urgent"):
        pr = "normal"

    tid = f"tk_{uuid.uuid4().hex[:16]}"
    row = Ticket(
        ticket_id=tid,
        user_id=user_id,
        session_id=session_id,
        summary=sid[:4000],
        priority=pr,
    )
    db.add(row)
    await db.flush()

    return {
        "ok": "true",
        "ticket_id": tid,
        "priority": pr,
        "message": f"Ticket {tid} opened for the support team.",
    }
