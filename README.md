# Helix SROP — Devesh Maurya

Stateful RAG orchestration pipeline for Helix: documentation Q&A (vector RAG) and account lookups (tool-backed agents), with **persistent session state**, **Google ADK** routing via **`AgentTool`**, and **structured traces** per turn.

**Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x (async SQLite), Chroma, Google ADK (`google-adk`), Gemini.

**Repository:** `https://github.com/deveshmaurya1996/helix-srop-assignment` (same URL as in the `git clone` commands below).

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

| Variable | Purpose |
|----------|---------|
| `GOOGLE_API_KEY` | Required for live LLM calls (Gemini) |
| `DATABASE_URL` | Default: `sqlite+aiosqlite:///./helix_srop.db` |
| `CHROMA_PERSIST_DIR` | Default: `./chroma_db` |
| `ADK_MODEL` | Default: `gemini-2.0-flash` |

**Security:** Never commit `.env` or API keys. This repository includes `.gitignore` rules for `.env`, `*.db`, and `chroma_db/`.

### 3. Ingest documentation into Chroma

```bash
python -m app.rag.ingest --path docs/
```

### 4. Run the API

```bash
uvicorn app.main:app --reload
```

Service defaults to `http://127.0.0.1:8000`.

### 5. Verify (recommended before submission)

```bash
pytest -q
```

All tests should pass (integration tests mock the LLM; one unit test ingests into a temporary Chroma directory).

---

## API overview

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/sessions` | Create session: body `{"user_id", "plan_tier"}`, returns `session_id` |
| `POST` | `/v1/chat/{session_id}` | Send message: JSON body `{"content": "..."}`. Returns `reply`, `routed_to`, `trace_id`. **SSE:** header `Accept: text/event-stream`. **Idempotency:** optional `Idempotency-Key` — identical session + body replays the cached response (JSON or full SSE bytes) without duplicating DB writes. |
| `GET` | `/v1/traces/{trace_id}` | Structured trace (routing, tool calls, chunk IDs, latency) |
| `GET` | `/v1/tickets` | Query `?user_id=` — list support tickets created via the escalation agent (`GET` is read-only listing). |
| `GET` | `/healthz` | Liveness |

**Errors (RFC 7807-style JSON):** `SESSION_NOT_FOUND` (404), `TRACE_NOT_FOUND` (404), `UPSTREAM_TIMEOUT` (504).

---

## Quick manual test

**bash (with `jq`):**

```bash
SESSION=$(curl -s -X POST localhost:8000/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"user_id": "u_demo", "plan_tier": "pro"}' | jq -r .session_id)

curl -s -X POST "localhost:8000/v1/chat/$SESSION" \
  -H "Content-Type: application/json" \
  -d '{"content": "How do I rotate a deploy key?"}' | jq .
```

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
 SQLite (users, sessions.state JSON, messages, agent_traces)
  |
  |  POST /v1/chat/{session_id}
  v
 pipeline.run
  |-- Load SessionState + validate session exists
  |-- execute_turn (Google ADK)
  |       Runner (in-memory services, auto_create_session=True)
  |         LlmAgent "srop_root"
  |           tools: AgentTool(knowledge), AgentTool(account)
  |             knowledge  -> search_docs  -> Chroma
  |             account    -> get_recent_builds, get_account_status (mock data)
  |-- Persist messages, AgentTrace, updated SessionState
  v
 JSON reply + trace_id
```

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

With the API running locally:

```bash
python eval/run_eval.py
python eval/run_eval.py --help
```

- **Default:** health, session, chat, tickets, then **idempotency** (two identical `POST`s with `Idempotency-Key`) and **guardrails** (blocked prompt → `routed_to: guardrails`). Prints one JSON line to stdout on success.
- **`--skip-extended`:** only the first four checks (useful if you want a quicker smoke without E1/E5 probes).
- **Base URL:** `--base-url http://127.0.0.1:9000` or `EVAL_BASE_URL=...`.
- **Verbose:** `-v` logs each step to stderr.

---

## Extensions status (`ASSIGNMENT.md` Section 4)

| ID | Feature | Status |
|----|---------|--------|
| E1 | Idempotency (`Idempotency-Key`) | **Implemented** — `idempotency_keys` table; JSON + SSE payloads keyed by header hash + body fingerprint (`app/services/idempotency.py`, `routes_chat`) |
| E2 | Escalation agent + `tickets` table | **Implemented** — `escalation` sub-agent + `create_ticket` tool (`escalation_tools`), context-bound DB session (`tool_context`), `GET /v1/tickets` |
| E3 | SSE on `POST /v1/chat/{id}` with `Accept: text/event-stream` | **Implemented** — ADK `StreamingMode.SSE`; falls back to chunking final text if the model emits no partials |
| E4 | Reranking | **Implemented** — oversampled Chroma retrieval + Gemini reordering with lexical fallback (`app/rag/rerank.py`); toggle `RERANK_ENABLED` |
| E5 | Guardrails + PII redaction | **Implemented** — prompt-injection / abuse heuristics short-circuit before LLM (`guardrails/policies`); structlog scrubs sensitive keys; optional email/phone masking in logs |
| E6 | Docker / Compose | **Implemented** — `Dockerfile`, `docker-compose.yml` |
| E7 | Eval harness | **Implemented** — `eval/run_eval.py` (CLI: `--base-url`, `-v`, `--skip-extended`; JSON result; idempotency + guardrail probes by default) |

---

## Submission checklist (`ASSIGNMENT.md`)

**Verify locally before you push:**

```bash
ruff check app tests eval
pytest -q
```

| Item | Status |
|------|--------|
| README: setup, architecture, state + chunking decisions, limitations, time spent | Done |
| `pytest -q` passes from a clean clone (after `pip install -e ".[dev]"` or `uv sync`, `cp .env.example .env`; ingest not required for mocked integration tests) | Done |
| `.env` / local DB / `chroma_db` excluded from git (`.gitignore`) | Done |
| GitHub repository public or reviewer invited | **Your step:** push `main`, confirm repo URL in README |
| Loom (≤4 min): multi-turn across **knowledge** and **account**, restart `uvicorn`, show state still works | **Your step:** record & link — see `LOOM_DEMO.md` for a timed script + files |

---

## Time spent

| Phase | Hours (approx.) |
|-------|-----------------|
| Environment, dependencies, DB models, FastAPI shell | 0.75 |
| RAG ingest (`chunk_markdown`, metadata, Chroma upsert) + `search_docs` | 1.00 |
| ADK root + Knowledge/Account sub-agents (`AgentTool`), `execute_turn`, timeouts | 1.25 |
| `pipeline.run`, traces, session routes, error handlers | 1.00 |
| Tests (`conftest`, integration + unit), README, `.gitignore`, polish | 0.75 |
| **Total** | **~4.75** |

---

## Author

**Devesh Maurya**
