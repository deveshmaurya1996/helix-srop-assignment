"""
Google ADK wiring: root `LlmAgent` + `AgentTool` sub-agents, `Runner`, turn execution.

Routing is native tool selection (not string-parsing LLM output). Durable session fields
live in SQLite (`SessionState`); ADK's session/memory services here are in-memory only.
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.events import Event
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.tools.agent_tool import AgentTool
from google.genai import types
from google.genai.errors import ClientError

from app.agents.tools import account_tools, escalation_tools
from app.agents.tools import search_docs as search_docs_tool
from app.agents.trace_context import get_recorded_chunk_ids, reset_trace_buffers
from app.api.errors import RateLimitedError, UpstreamTimeoutError
from app.settings import settings
from app.srop.state import SessionState

# Ensure Gemini can pick up the key from the environment.
if settings.google_api_key:
    os.environ.setdefault("GOOGLE_API_KEY", settings.google_api_key)


def _raise_if_gemini_rate_limit(exc: ClientError) -> None:
    """Map GenAI quota / RPM errors to HTTP 429 instead of an opaque 500."""
    if isinstance(exc, ClientError) and getattr(exc, "code", None) == 429:
        detail = getattr(exc, "message", None) or str(exc)
        raise RateLimitedError(detail) from exc

ROOT_BASE = """
You are the Helix Support Concierge — a routing agent.
You have specialist tools (sub-agents):
- **knowledge**: product documentation, how-to, "what is", security, CI, billing policy questions.
- **account**: the user's builds, usage, plan limits, "last failed builds", account status.
- **escalation**: open a human-support ticket for billing disputes, suspected account compromise,
  legal/compliance, abuse reports, or when the user explicitly asks for a human.

Rules:
- If the user asks how something works or about Helix features → call **knowledge**.
- If the user asks about *their* data (builds, account, usage)
  → call **account** with the user_id from context.
- If the user needs a human (escalation, dispute, lockout, ticket) → call **escalation**
  (it will create a ticket via create_ticket).
- Simple greetings, thanks, or chit-chat → answer directly (no tool call).

Never invent detailed procedures without calling **knowledge**.
"""


def _root_instruction(state: SessionState) -> str:
    return (
        f"{ROOT_BASE.strip()}\n\n"
        "=== Session context (do not ask the user to repeat these) ===\n"
        f"- user_id: {state.user_id}\n"
        f"- plan_tier: {state.plan_tier}\n"
        f"- previous_specialist: {state.last_agent or 'none'}\n"
        f"- turns_so_far: {state.turn_count}\n"
    )


def _knowledge_instruction() -> str:
    return """
You answer Helix product questions using the search_docs tool only.

Steps:
1. Call search_docs with a concise query and k between 3 and 8.
2. Answer using ONLY retrieved content. Quote chunk IDs inline like [chunk_xxxxxxxx] for each claim.

If search_docs returns nothing relevant, say you could not find it in the docs.
"""


def _escalation_instruction() -> str:
    return """
You handle escalation to human support for Helix.

When to act:
- User asks for a human, manager, or ticket.
- Billing disputes, refunds outside self-serve policy.
- Suspected account takeover or security incidents.
- Legal, privacy, or compliance requests.

Steps:
1. Summarize the issue in one short sentence for the ticket summary.
2. Choose priority: low | normal | high | urgent (urgent only for lockout/security).
3. Call create_ticket(summary=..., priority=...).

Confirm the ticket_id to the user and set expectations (business hours, email follow-up).
"""


def _account_instruction(state: SessionState) -> str:
    return f"""
You help with Helix account data for user_id={state.user_id}.

Always pass user_id="{state.user_id}" to get_recent_builds and get_account_status.
The user's plan tier is {state.plan_tier} — mention it when summarizing limits.

Respond with concise bullet points when listing builds.
"""


def build_agents(state: SessionState) -> LlmAgent:
    """Build a fresh agent graph each turn so prompts match latest ``SessionState``."""

    knowledge_agent = LlmAgent(
        name="knowledge",
        model=settings.adk_model,
        instruction=_knowledge_instruction(),
        tools=[search_docs_tool.search_docs],
    )

    account_agent = LlmAgent(
        name="account",
        model=settings.adk_model,
        instruction=_account_instruction(state),
        tools=[account_tools.get_recent_builds, account_tools.get_account_status],
    )

    escalation_agent = LlmAgent(
        name="escalation",
        model=settings.adk_model,
        instruction=_escalation_instruction(),
        tools=[escalation_tools.create_ticket],
    )

    root_agent = LlmAgent(
        name="srop_root",
        model=settings.adk_model,
        instruction=_root_instruction(state),
        tools=[
            AgentTool(agent=knowledge_agent),  # assignment: sub-agent as tool, not string routing
            AgentTool(agent=account_agent),
            AgentTool(agent=escalation_agent),
        ],
    )
    return root_agent


def _serialize_tool_result(result: Any) -> Any:
    if hasattr(result, "__dict__"):
        try:
            return result.__dict__
        except Exception:
            return str(result)
    return result


def _merge_tool_calls(events: list[Event]) -> list[dict[str, Any]]:
    """Flatten ADK events into ordered tool_call rows for `agent_traces.tool_calls` JSON."""
    rows: list[dict[str, Any]] = []
    for event in events:
        for fc in event.get_function_calls():
            rows.append(
                {
                    "tool_name": fc.name or "",
                    "args": dict(fc.args) if fc.args else {},
                    "result": None,
                    "_id": fc.id,
                }
            )
        for fr in event.get_function_responses():
            assigned = False
            name = fr.name or ""
            resp_val = fr.response if fr.response is not None else getattr(fr, "parts", None)
            for row in reversed(rows):
                if row["result"] is None and row["tool_name"] == name:
                    row["result"] = resp_val
                    assigned = True
                    break
            if not assigned:
                rows.append({"tool_name": name, "args": {}, "result": resp_val})
    out = []
    for row in rows:
        row.pop("_id", None)
        out.append({"tool_name": row["tool_name"], "args": row["args"], "result": row["result"]})
    return out


def _normalize_author(author: str | None, reply: str) -> str:
    """Map ADK `event.author` (+ light reply heuristics) to API `routed_to` string."""
    a = (author or "").lower()
    if "knowledge" in a:
        return "knowledge"
    if "account" in a:
        return "account"
    if "escalation" in a:
        return "escalation"
    if "srop_root" in a or "root" in a:
        return "smalltalk"
    rl = reply.lower()
    if "tk_" in rl or ("ticket" in rl and "created" in rl):
        return "escalation"
    if any(x in rl for x in ("chunk_", "[chunk_")):
        return "knowledge"
    return "smalltalk"


@dataclass
class AdkTurnResult:
    reply: str
    routed_to: str
    tool_calls: list[dict[str, Any]]
    retrieved_chunk_ids: list[str]


async def execute_turn(session_id: str, user_message: str, state: SessionState) -> AdkTurnResult:
    reset_trace_buffers()
    root = build_agents(state)
    runner = Runner(
        app_name="helix_srop",
        agent=root,
        artifact_service=InMemoryArtifactService(),
        session_service=InMemorySessionService(),  # not durable; app DB holds conversation truth
        memory_service=InMemoryMemoryService(),
        auto_create_session=True,
    )

    new_message = types.Content(
        role="user",
        parts=[types.Part(text=user_message)],
    )

    async def _collect() -> tuple[str, str, list[Event]]:
        events: list[Event] = []
        final_text = ""
        final_author: str | None = None
        gen = runner.run_async(
            user_id=state.user_id,
            session_id=session_id,
            new_message=new_message,
        )
        async for event in gen:
            events.append(event)
            if event.is_final_response() and event.content and event.content.parts:
                text_parts = [p.text for p in event.content.parts if getattr(p, "text", None)]
                if text_parts:
                    final_text = "\n".join(text_parts).strip()
                    final_author = event.author
        if not final_text:
            final_text = "(No response generated.)"
        routed = _normalize_author(final_author, final_text)
        return final_text, routed, events

    try:
        final_text, routed, events = await asyncio.wait_for(
            _collect(),
            timeout=float(settings.llm_timeout_seconds),
        )
    except TimeoutError as exc:
        raise UpstreamTimeoutError(
            f"LLM did not respond within {settings.llm_timeout_seconds}s"
        ) from exc
    except ClientError as exc:
        _raise_if_gemini_rate_limit(exc)
        raise

    tool_calls = _merge_tool_calls(events)
    chunk_ids = get_recorded_chunk_ids()

    return AdkTurnResult(
        reply=final_text,
        routed_to=routed,
        tool_calls=tool_calls,
        retrieved_chunk_ids=chunk_ids,
    )


def _final_reply_from_events(events: list[Event]) -> tuple[str, str | None]:
    """Extract assistant reply text and author from collected ADK events."""
    final_text = ""
    final_author: str | None = None
    for event in events:
        if event.is_final_response() and event.content and event.content.parts:
            text_parts = [p.text for p in event.content.parts if getattr(p, "text", None)]
            if text_parts:
                final_text = "\n".join(text_parts).strip()
                final_author = event.author
    if not final_text:
        final_text = "(No response generated.)"
    return final_text, final_author


async def execute_turn_stream(
    session_id: str, user_message: str, state: SessionState
) -> AsyncIterator[tuple[str, Any]]:
    """
    Stream one ADK turn using Gemini SSE-style partial events.

    Yields:
        ("delta", str) — incremental assistant text for the client (SSE).
        ("complete", AdkTurnResult) — final structured result for persistence.

    Non-streaming callers should use execute_turn() instead.
    """
    reset_trace_buffers()
    root = build_agents(state)
    runner = Runner(
        app_name="helix_srop",
        agent=root,
        artifact_service=InMemoryArtifactService(),
        session_service=InMemorySessionService(),  # in-memory; SQLite is canonical
        memory_service=InMemoryMemoryService(),
        auto_create_session=True,
    )

    new_message = types.Content(
        role="user",
        parts=[types.Part(text=user_message)],
    )

    run_config = RunConfig(streaming_mode=StreamingMode.SSE)  # token-delta events from Gemini
    gen = runner.run_async(
        user_id=state.user_id,
        session_id=session_id,
        new_message=new_message,
        run_config=run_config,
    )

    events: list[Event] = []
    cumul_displayed = ""
    emitted_delta = False

    try:
        async for event in gen:
            events.append(event)

            if getattr(event, "partial", None) and event.content and event.content.parts:
                has_fc = any(p.function_call for p in event.content.parts)
                has_text = any(getattr(p, "text", None) for p in event.content.parts)
                if has_text and not has_fc:
                    chunk_full = "".join(p.text or "" for p in event.content.parts)
                    if chunk_full.startswith(cumul_displayed):
                        delta = chunk_full[len(cumul_displayed) :]
                        cumul_displayed = chunk_full
                        if delta:
                            emitted_delta = True
                            yield ("delta", delta)
    except ClientError as exc:
        _raise_if_gemini_rate_limit(exc)
        raise

    final_text, final_author = _final_reply_from_events(events)
    routed = _normalize_author(final_author, final_text)

    if not emitted_delta and final_text and final_text != "(No response generated.)":
        # No partial tokens observed — chunk final reply so SSE still demonstrates streaming.
        step = 48
        for i in range(0, len(final_text), step):
            yield ("delta", final_text[i : i + step])

    tool_calls = _merge_tool_calls(events)
    chunk_ids = get_recorded_chunk_ids()

    yield (
        "complete",
        AdkTurnResult(
            reply=final_text,
            routed_to=routed,
            tool_calls=tool_calls,
            retrieved_chunk_ids=chunk_ids,
        ),
    )
