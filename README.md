# Helix SROP — Devesh Maurya

Stateful RAG orchestration pipeline for Helix: documentation Q&A (vector RAG) and account lookups (tool-backed agents), with **persistent session state**, **Google ADK** routing via **`AgentTool`**, and **structured traces** per turn.

**Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x (async SQLite), Chroma, Google ADK (`google-adk`), Gemini.

**Public GitHub repository (submission):**  
`https://github.com/deveshmaurya1996/helix-srop-assignment` — same URL as in the `git clone` commands below. Ensure the repo is **public** (or shared with reviewers) before you submit.

**Hosted live API (optional):**  
This project is a self-hosted FastAPI service (no bundled static UI). If you deploy it, add your base URL here and in your cover email (e.g. `https://your-api.onrender.com`). Otherwise reviewers can run it locally with the steps in this README.

**Demo video (Loom or screen recording, ~2–3 minutes):**  
Record your screen with audio and walk through the script in [Demo walkthrough](#demo-walkthrough-loom--screen-recording) so every capability is visible in one take.

---

## Demo walkthrough (Loom / screen recording)

Use this order so graders see **routing, RAG, tools, persistence, extensions**, and **restart survival**:

1. **Setup visible** — Show repo root, `.env` with `GOOGLE_API_KEY` set (mask the key), `python -m app.rag.ingest --path docs/` already run (or run it once), and `uvicorn` starting cleanly.
2. **Session** — `POST /v1/sessions` with `user_id` + `plan_tier` → copy `session_id` (or run `python -m app.db.seed` and use the printed `session_id` for a repeatable demo).
3. **Knowledge / RAG** — Ask a doc question (e.g. deploy key rotation). Show JSON `reply`, `routed_to` (e.g. knowledge path), and `trace_id`.
4. **Trace** — `GET /v1/traces/{trace_id}` and point out `tool_calls`, `retrieved_chunk_ids`, `latency_ms`.
5. **Account tools** — Ask for last failed builds or account status; show `routed_to` reflecting account handling.
6. **Escalation + tickets** — Ask for a human / open a ticket; then `GET /v1/tickets?user_id=...` and show the new row.
7. **State without re-asking** — Second message that assumes **plan tier** is already known (e.g. “What limits apply to my plan?”) and show coherent use of prior context.
8. **Restart survival** — Stop `uvicorn`, start again, send another message on the **same** `session_id`; show it still works with stored `sessions.state` / messages.
9. **Optional extras** — SSE: same chat with header `Accept: text/event-stream`. Idempotency: same `POST` with an `Idempotency-Key` twice and show identical JSON.

Paste your **Loom (or YouTube unlisted) link** next to the repository link in your submission form.

---

## Prerequisites

- **Python 3.11+** (3.11 or 3.12 recommended; 3.13 works with dependency deprecation warnings)
- **Google AI API key** ([Google AI Studio](https://aistudio.google.com/apikey)) for Gemini models used by ADK

---

## Setup (fresh clone)

Typical time: **under 5 minutes** after Python is installed (excluding first-time dependency downloads).

### 1. Clone and virtual environment

**Option A — `uv`**

```bash
git clone https://github.com/deveshmaurya1996/helix-srop-assignment.git
cd helix-srop-assignment
uv sync --extra dev
cp .env.example .env
```

**Option B — `venv` + pip**

```bash
git clone https://github.com/deveshmaurya1996/helix-srop-assignment.git
cd helix-srop-assignment
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

### 2. Configure environment

Edit `.env` and set at minimum:

| Variable             | Purpose                                        |
| -------------------- | ---------------------------------------------- |
| `GOOGLE_API_KEY`     | Required for live LLM calls (Gemini)           |
| `DATABASE_URL`       | Default: `sqlite+aiosqlite:///./helix_srop.db` |
| `CHROMA_PERSIST_DIR` | Default: `./chroma_db`                         |
| `ADK_MODEL`          | Default: `gemini-2.0-flash`                    |

**Security:** Never commit `.env` or API keys. This repository includes `.gitignore` rules for `.env`, `*.db`, and `chroma_db/`.

### 3. Ingest documentation into Chroma

```bash
python -m app.rag.ingest --path docs/
```

**Optional — seed SQLite** with a demo user, session, two tickets, a trace, and sample messages (safe to re-run; skips if the demo session already exists):

```bash
python -m app.db.seed
```

The command prints `user_id`, `session_id`, and `trace_id` plus example `curl` lines.

### 4. Run the API

From the repository root, with the same Python you used for `pip install` (venv activated on Windows, or use `.\.venv\Scripts\python.exe` instead of `python`):

```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/healthz` and `http://127.0.0.1:8000/docs` (OpenAPI / “Try it out” for every route).

### 5. Verify (recommended before submission)

```bash
pytest -q
```

All tests should pass (integration tests mock the LLM; one unit test ingests into a temporary Chroma directory).

---

## API overview

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/sessions` | Create session (`user_id`, `plan_tier`) → `session_id` |
| `POST` | `/v1/chat/{session_id}` | Message in, `reply` + `routed_to` + `trace_id` out. SSE: `Accept: text/event-stream`. Optional `Idempotency-Key` for safe retries. |
| `GET` | `/v1/traces/{trace_id}` | Trace: routing, tool calls, chunk IDs, latency |
| `GET` | `/v1/tickets?user_id=` | List tickets for a user |
| `GET` | `/healthz` | Liveness |

**Errors (RFC 7807-style JSON `application/json`):** `SESSION_NOT_FOUND` (404), `TRACE_NOT_FOUND` (404), `RATE_LIMITED` (429 — Gemini quota / rate limit; retry later or adjust billing), `UPSTREAM_TIMEOUT` (504).

---

## Features

What the implementation delivers (core assignment + extensions):

| Area | Behavior |
|------|----------|
| **Sessions** | `POST /v1/sessions` creates a row in `sessions` with JSON `state` (`SessionState`: `user_id`, `plan_tier`, `last_agent`, `turn_count`). Same `user_id` updates `plan_tier` on the `users` row. |
| **Stateful chat** | Each `POST /v1/chat/{session_id}` persists user + assistant messages, updates `sessions.state`, and injects tier / user into the ADK root prompt so the model does not re-ask. State survives **process restart** (SQLite is the source of truth; ADK session/memory services stay in-process only). |
| **Knowledge (RAG)** | Root agent calls a **knowledge** sub-agent via `AgentTool`; it uses `search_docs` → Chroma. Optional **rerank** (E4) refines an oversampled hit list before truncation to `k`. |
| **Account** | **account** sub-agent (`AgentTool`) calls `get_recent_builds` / `get_account_status` — **mock data**; real `plan_tier` for UX comes from `SessionState` in instructions. |
| **Escalation (E2)** | **escalation** sub-agent can `create_ticket` (writes `tickets` via request-scoped DB context). `GET /v1/tickets?user_id=` lists tickets. |
| **Traces** | `trace_id` on each reply; `GET /v1/traces/{trace_id}` returns `routed_to`, `tool_calls`, `retrieved_chunk_ids`, `latency_ms`. |
| **SSE (E3)** | Header `Accept: text/event-stream` → newline-delimited `data: {JSON}` events (`delta` then `done`). |
| **Idempotency (E1)** | Header `Idempotency-Key` + same session, body, and JSON vs SSE mode → replay cached response **without** writing duplicate messages. |
| **Guardrails (E5)** | Pre-LLM policy on user text; refusal path skips Gemini, stores `routed_to=guardrails`. `redact_pii_for_logs` masks emails/phones in logs. |
| **Docker (E6)** | `docker compose up --build` — API on `:8000`, SQLite/Chroma on a named volume under `./data` in the container. |
| **Eval (E7)** | `python eval/run_eval.py` against a running server (see [Evaluation harness](#evaluation-harness-e7)). |

---

## Quick manual test

**Option A — new session (bash + `jq`):**

```bash
SESSION=$(curl -s -X POST localhost:8000/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"user_id": "u_demo", "plan_tier": "pro"}' | jq -r .session_id)

curl -s -X POST "localhost:8000/v1/chat/$SESSION" \
  -H "Content-Type: application/json" \
  -d '{"content": "How do I rotate a deploy key?"}' | jq .
```

**Option B — after `python -m app.db.seed`:** use the printed `session_id` (fixed UUID `a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11`) so demos match the seeded user `demo_user` / `pro` tier.

**PowerShell:**

```powershell
$r = Invoke-RestMethod -Method Post -Uri http://localhost:8000/v1/sessions `
  -ContentType "application/json" -Body '{"user_id":"u_demo","plan_tier":"pro"}'
$sid = $r.session_id
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/v1/chat/$sid" `
  -ContentType "application/json" -Body '{"content":"How do I rotate a deploy key?"}'
```

---

## Architecture

```
Client
  |
  |  POST /v1/sessions
  v
 SQLite (users, sessions.state JSON, messages, agent_traces, tickets)
  |
  |  POST /v1/chat/{session_id}
  v
 pipeline.run / pipeline.run_stream
  |-- Load SessionState + validate session exists
  |-- Guardrails (optional) -> short-circuit refusal if policy blocks
  |-- execute_turn / execute_turn_stream (Google ADK)
  |       Runner (in-memory ADK services, auto_create_session=True)
  |         LlmAgent "srop_root" (model from settings ADK_MODEL)
  |           tools: AgentTool(knowledge), AgentTool(account), AgentTool(escalation)
  |             knowledge  -> search_docs -> Chroma (+ optional rerank)
  |             account    -> get_recent_builds, get_account_status (mock data)
  |             escalation -> create_ticket (SQLite tickets)
  |-- Persist user + assistant messages, AgentTrace, updated SessionState
  v
 JSON reply + trace_id (or SSE stream)
```

### Repository layout (main packages)

| Path | Role |
|------|------|
| `app/main.py` | FastAPI app, routers, `HelixError` handler |
| `app/api/` | REST routes: sessions, chat, traces, tickets |
| `app/api/errors.py` | Typed errors → RFC 7807 JSON |
| `app/agents/adk_runner.py` | ADK `Runner`, `AgentTool` wiring, `execute_turn` / streaming |
| `app/agents/orchestrator.py` | Short docstring pointer to where root/sub-agent instructions live |
| `app/agents/tools/` | `search_docs`, account mocks, `create_ticket` |
| `app/srop/pipeline.py` | Chat pipeline: DB, guardrails, ADK, persistence |
| `app/srop/state.py` | `SessionState` ↔ `sessions.state` JSON |
| `app/rag/` | Ingest CLI, chunking, Chroma, rerank helper |
| `app/db/` | SQLAlchemy models, async session, optional `seed.py` |
| `app/guardrails/` | Message policy + PII-style redaction hooks |
| `app/services/idempotency.py` | E1 replay cache |
| `eval/run_eval.py` | E7 scripted checks against a running API |
| `tests/` | pytest integration (mocked LLM) + retriever unit tests |

Core modules use short **module docstrings** and **inline notes** where behavior is easy to misunderstand (ADK in-memory vs SQLite, E1/E2/E4/E5 boundaries, mock account data). There is no JWT/auth layer in this take-home.

---

## Design decisions

### State persistence (ADK guide pattern)

**Pattern 3 — session state in the application database + injected context**

- Canonical state lives in SQLite: `sessions.state` holds `SessionState` (`user_id`, `plan_tier`, `last_agent`, `turn_count`).
- Each chat turn rebuilds ADK agents with an instruction prefix that includes this context so the model does not re-ask for plan tier or user id.
- **Messages** are stored in `messages` for auditability and optional future replay; restart survival is guaranteed by **persisted `SessionState` and rows in `sessions` / `messages`**, not by ADK’s in-memory session service alone.

This balances durability (assignment requirement) with implementation complexity versus a full custom `BaseSessionService` implementation.

### Chunking strategy

**Heading-aware splitting** on `##` / `###`, then **character windows** with overlap for long sections. Frontmatter YAML is parsed for `title`, `product_area`, and attached to Chroma metadata. Chunk IDs are **deterministic** (`sha256(relative_path:index)`) so re-ingest does not duplicate logical chunks when IDs are stable.

### Vector store

**Chroma** persistent client under `CHROMA_PERSIST_DIR`, **cosine** space, default embedding function bundled with Chroma for local development without a separate embedding service.

---

## Tests

```bash
pytest -q
```

- **Integration:** session creation, chat with mocked ADK boundary (`execute_turn` via `app.srop.pipeline`), trace with chunk IDs, plan-tier follow-up using persisted state, 404 for missing session.
- **Unit:** chunker plus `search_docs` (scores in `[0, 1]`, chunk IDs) after ingest into an isolated temporary Chroma directory.

---

## Known limitations

- **Idempotent retries** are best-effort: concurrent duplicate requests with the same key may both execute once before either cache row commits (acceptable for this SQLite demo; production would use a distributed lock or transactional outbox).
- **Account tools** return **mock** build and usage data; wiring and ADK integration are what reviewers exercise.
- **`get_account_status`** mock does not dynamically read `plan_tier` from the DB; the **root/account instructions** carry the real tier from `SessionState` for coherent answers.
- **Routing metadata** (`routed_to`) is derived from ADK event authors and fallbacks when authors are ambiguous.
- **SQLAlchemy** uses `datetime.utcnow` defaults (deprecation warnings under Python 3.13+); acceptable for this SQLite dev setup.

---

## What I would add with more time

- **Alembic migrations** instead of `create_all` on startup for production.
- **Stronger routing attribution** by parsing ADK events only (no heuristics on reply text).
- **Dynamic `get_account_status`** backed by real usage tables when schema exists.
- **Distributed idempotency** (Redis / advisory locks) for concurrent retries with the same key.

---

## Docker (E6)

```bash
docker compose up --build
```

The API listens on port **8000**. SQLite and Chroma paths default under `./data` inside the container via `DATABASE_URL` / `CHROMA_PERSIST_DIR` in `docker-compose.yml`. Provide `GOOGLE_API_KEY` via `.env`.

---

## Evaluation harness (E7)

With the API running on port 8000:

```bash
python eval/run_eval.py
```

Use `python eval/run_eval.py --help` for options (`--base-url`, `--skip-extended`, `-v`).

---

## Extensions status (`ASSIGNMENT.md` Section 4)

| ID | Feature | Status |
|----|---------|--------|
| E1 | Idempotency (`Idempotency-Key`) | Implemented |
| E2 | Escalation agent + `tickets` table | Implemented |
| E3 | SSE (`Accept: text/event-stream`) | Implemented |
| E4 | Reranking | Implemented |
| E5 | Guardrails + PII redaction | Implemented |
| E6 | Docker / Compose | Implemented |
| E7 | Eval harness (`eval/run_eval.py`) | Implemented |

---

## Submission checklist (assignment + repository hygiene)

**Verify locally before you push:**

```bash
ruff check app tests eval
pytest -q
```

| Deliverable | Notes |
|-------------|--------|
| **GitHub repository link** | Public repo: `https://github.com/deveshmaurya1996/helix-srop-assignment` — push latest `main`, confirm `.env` is never committed. |
| **README.md** | This file: setup, architecture, API, tests, Docker, eval, extensions, limitations. |
| **`.env.example`** | Committed template only; no real secrets. Copy to `.env` locally. |
| **Demo video (2–3 min)** | Follow [Demo walkthrough](#demo-walkthrough-loom--screen-recording); upload Loom or unlisted YouTube and add the URL to your submission. |
| **Hosted link (if applicable)** | Optional; document the base URL if you deploy. |
| **`pytest -q`** | Passes after `pip install -e ".[dev]"` or `uv sync --extra dev` and `cp .env.example .env`. |
| **`.gitignore`** | Covers `.env`, `*.db`, `chroma_db/`, venvs, caches. |

---

## Time spent

| Phase                                                                           | Hours (approx.) |
| ------------------------------------------------------------------------------- | --------------- |
| Environment, dependencies, DB models, FastAPI shell                             | 0.75            |
| RAG ingest (`chunk_markdown`, metadata, Chroma upsert) + `search_docs`          | 1.00            |
| ADK root + Knowledge/Account sub-agents (`AgentTool`), `execute_turn`, timeouts | 1.25            |
| `pipeline.run`, traces, session routes, error handlers                          | 1.00            |
| Tests (`conftest`, integration + unit), README, `.gitignore`, polish            | 0.75            |
| **Total**                                                                       | **~4.75**       |

---

## Author

**Devesh Maurya**
