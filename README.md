# DentalAI — AI-Powered Dental Practice Management

A portfolio project demonstrating production-grade AI engineering with Python, FastAPI, LangChain, and React. DentalAI mirrors the structure of the [NexHealth Synchronizer API](https://docs.nexhealth.com) — a real dental practice management platform — without requiring a live account. All data runs locally on SQLite with Faker-generated mock patients, providers, and appointments.

> **Portfolio goal:** Show end-to-end AI product engineering — typed REST API, event-driven background jobs, an LLM agent that books and modifies appointments, and a polished React dashboard with a Dentrix-style interactive calendar (drag-to-move, drag-to-resize, overlap detection).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        React Frontend                           │
│   ScheduleView  │  RecallQueue  │  BookingChat  │  AgentLog     │
└────────────────────────┬────────────────────────────────────────┘
                         │  HTTP (REST + /agent/chat)
┌────────────────────────▼────────────────────────────────────────┐
│                      FastAPI  (port 8000)                       │
│                                                                 │
│  /api/v1/patients          /api/v1/appointments                 │
│  /api/v1/available_slots   /api/v1/patient_recalls              │
│  /api/v1/providers         /api/v1/events                       │
│  /api/v1/webhooks/simulate                                      │
│  /api/v1/agent/chat        /api/v1/agent/status/{session_id}    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────┐   ┌────────────────────────┐
│        SQLAlchemy + SQLite          │   │   LangChain Agent      │
│                                     │   │   (Groq-hosted model)  │
│  Patient  Provider  Location        │   │                        │
│  Appointment  AvailableSlot         │   │  14 tools — booking,   │
│  PatientRecall  Event               │   │  scheduling, recalls,  │
│                                     │   │  patient management    │
└──────────────────────────┬──────────┘   └────────────────────────┘
                           │
┌──────────────────────────▼──────────┐
│        APScheduler (background)     │
│                                     │
│  appointment.reminder  every 2 min  │
│  recall.due            every 5 min  │
│  appointment.booked    on POST      │
└─────────────────────────────────────┘
```

---

## Tech Stack

| Technology | Version | Why |
|---|---|---|
| **Python** | 3.11 | Async-ready, strong typing, ecosystem breadth |
| **FastAPI** | 0.115 | Auto-generated OpenAPI docs, Pydantic validation, async-first |
| **SQLAlchemy** | 2.0 | Typed ORM with `Mapped[]`, clean migration path to Postgres |
| **SQLite** | — | Zero-config local persistence; swap for Postgres in prod |
| **Pydantic v2** | 2.10 | Schema validation + serialisation, NexHealth envelope shaping |
| **APScheduler** | 3.10 | In-process cron jobs for background event firing |
| **Groq SDK** | 0.11+ | LLM inference via OpenAI-compatible API |
| **LangChain Core** | 0.2 | `@tool` decorator + schema introspection |
| **python-jose** | 3.3 | HS256 JWT auth |
| **Faker** | 33 | Deterministic mock patient/appointment data |
| **React** | 18.3 | Component model, hooks, concurrent features |
| **TypeScript** | 5.5 | Catches API contract mismatches at compile time |
| **Vite** | 5.4 | Sub-second HMR, native ESM |
| **Tailwind CSS** | 3.4 | Utility-first dark theme without CSS bloat |
| **TanStack Query** | 5 | Caching, refetch intervals, loading/error states |
| **React Router** | 6 | SPA routing for four views |
| **Radix UI** | — | Accessible dialog/scroll primitives |
| **Docker** | — | Reproducible one-command startup |
| **Redis** | 7 | Wired in for future agent session persistence |

---

## Quick Start

### Option 1 — Docker (recommended, zero setup)

```bash
# 1. Clone
git clone <repo-url>
cd dentalai

# 2. Set your Groq key (optional — all non-agent endpoints work without it)
cp backend/.env.example backend/.env
# Edit backend/.env and set GROQ_API_KEY=gsk-...

# 3. Start everything
docker-compose up --build

# The first boot automatically seeds the database.
# Frontend: http://localhost:5173
# API docs: http://localhost:8000/docs
# The Bearer token is printed in the backend container logs.
```

### Option 2 — Manual (Python 3.11+)

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # add GROQ_API_KEY if you want agent chat
alembic upgrade head               # run migrations
python -m app.db.seed              # populate the database
uvicorn app.main:app --reload      # starts on port 8000

# Frontend (separate terminal)
cd ../frontend
npm install
cp .env.example .env               # VITE_API_URL=http://localhost:8000
npm run dev                        # starts on port 5173
```

---

## Authentication

Auth is scaffolded (`auth.py` generates an HS256 JWT printed at startup) but not enforced yet — the Bearer header is currently ignored by all API routes. Enforcement is planned for a later milestone.

**Dev token (for future use):** printed to the backend console on startup:
```
INFO | app.main | Test Bearer token (valid 24 h):
INFO | app.main |   eyJhbGci...
```

---

## API Reference

All list responses follow the NexHealth envelope shape:
```json
{
  "code": 200,
  "description": "OK",
  "data": {
    "items": [...],
    "total": 42
  }
}
```

### Patients

```bash
# List patients (optional: ?name=jane&email=@example.com)
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patients

# Get single patient
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patients/3

# Create patient
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"first_name":"Jane","last_name":"Doe","email":"jane@example.com","phone":"(555) 123-4567"}' \
  http://localhost:8000/api/v1/patients
```

### Appointments

```bash
# Today's appointments
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/appointments?date=$(date +%Y-%m-%d)"

# Appointments by provider
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/appointments?provider_id=1"

# Create appointment
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": 3,
    "provider_id": 1,
    "location_id": 1,
    "appointment_type_id": 1,
    "start_time": "2025-06-10T10:00:00",
    "end_time": "2025-06-10T10:45:00",
    "status": "confirmed"
  }' \
  http://localhost:8000/api/v1/appointments

# Update appointment status
curl -X PATCH -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "completed"}' \
  http://localhost:8000/api/v1/appointments/42
```

### Available Slots

```bash
# Open slots this week
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/available_slots?booked=false"

# Slots for a specific provider and date
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/available_slots?provider_id=2&date=2025-06-10"
```

### Patient Recalls

```bash
# All overdue recalls
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/patient_recalls?status=pending&due_before=$(date +%Y-%m-%d)"

# Recalls filtered by status
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/patient_recalls?status=contacted"
```

### Providers & Appointment Types

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/providers
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/appointment_types
```

### Events (Agent Log)

```bash
# Recent events (newest first)
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/events?limit=20"

# Filter by type
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/events?event_type=recall.due"
```

### Webhook Simulator

```bash
# Manually fire any event type
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "recall.due",
    "payload": {"patient_id": 5, "recall_type": "6-month cleaning", "due": "2024-01-10"}
  }' \
  http://localhost:8000/api/v1/webhooks/simulate
```

### Agent Chat

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Book a cleaning for patient 3 with any available provider this week",
    "session_id": "my-session"
  }' \
  http://localhost:8000/api/v1/agent/chat
```

Response:
```json
{
  "response": "I've booked a cleaning for Catherine Chen with Dr. Smith on Monday, June 9 at 10:00 AM. Appointment ID: 187.",
  "tool_calls": [
    {
      "tool": "check_available_slots",
      "input": {"date_from": "2025-06-09", "date_to": "2025-06-13", "provider_id": 0},
      "output": "[{\"slot_id\": 42, \"provider_name\": \"Dr. Alice Smith\", ...}]"
    },
    {
      "tool": "book_appointment",
      "input": {"patient_id": 3, "slot_id": 42, "appointment_type_id": 1},
      "output": "Appointment booked successfully!\n  Appointment ID: 187 ..."
    }
  ],
  "session_id": "my-session"
}
```

---

## LangChain Agent

The agent is built on **Groq function calling** with 14 tools defined using LangChain's `@tool` decorator. Each tool opens its own database session and returns a string — either JSON data or a human-readable confirmation. Rate-limit retries are surfaced in real time to the frontend via a polling status endpoint.

### Agent Loop

```
User message
    │
    ▼
POST /chat/completions  (Groq, with OPENAI_TOOL_SCHEMAS)
    │
    ├─ finish_reason == "tool_calls"
    │   ├─ Execute each called tool against the SQLite DB
    │   ├─ Append results to conversation context
    │   └─ Loop (max 6 iterations)
    │
    └─ finish_reason == "stop"
        └─ Return final answer + tool_call log
```

### Tools

| Tool | Description |
|---|---|
| `search_patients` | Search patients by name |
| `add_patient` | Create a new patient record |
| `list_all_patients` | List all patients in the practice |
| `list_patients_by_provider` | List patients seen by a specific provider |
| `get_patient_appointments` | Get a patient's upcoming/recent appointments |
| `get_appointments_for_date` | Get all booked appointments for a specific date |
| `check_available_slots` | Find open slots in a date range, enforcing 5 PM closing |
| `book_appointment` | Book a slot; validates 5 PM cutoff and provider overlaps |
| `delete_appointment` | Hard-delete an appointment and free its slot |
| `cancel_appointment` | Set status to cancelled (keeps the record) |
| `modify_appointment` | Change any combination of provider, time, type, patient, status, or notes — with overlap and office-hours validation |
| `get_patient_context` | Demographics + last appointment + recall status |
| `get_recall_queue` | Overdue recalls sorted by days overdue |
| `draft_recall_message` | Personalised outreach with tone escalation (gentle → moderate → urgent) |

### Rate Limit Handling

When Groq returns a 429, the backend parses the retry-after time from the error message. Short waits (< 5 min, typically TPM limits) are retried automatically. Long waits (daily token limits) surface immediately as a user-friendly error. The frontend polls `GET /api/v1/agent/status/{session_id}` every second and shows a live countdown under the thinking bubble.

### Memory

Conversation history is held in a module-level dict keyed by `session_id`. To add persistence across restarts, swap `_session_histories` for a `RedisChatMessageHistory` backed by the Redis container that's already in `docker-compose.yml`.

---

## Background Events

APScheduler runs two jobs inside the FastAPI process:

| Job | Interval | Trigger condition | Event fired |
|---|---|---|---|
| `appointment_reminder_job` | Every 2 min | Appointment starts within 24 h and is pending/confirmed | `appointment.reminder` |
| `recall_due_job` | Every 5 min | `PatientRecall.due_date` is in the past and `status == pending` | `recall.due` |

Plus: `POST /appointments` fires `appointment.booked` synchronously after commit.

All events are persisted to the `events` table (audit trail) and printed to stdout in the format:
```
[EVENT] recall.due → patient_id=12 | recall_type=6-month cleaning | due=2024-01-15
```

---

## Connecting to a Real NexHealth Account

The mock layer mirrors NexHealth's API contract. Swapping it in requires three changes:

### 1. Replace SQLAlchemy reads with NexHealth API calls

```python
# Current (mock)
patients = db.query(Patient).all()

# Real NexHealth
import httpx
resp = httpx.get(
    "https://nexhealth.info/patients",
    headers={"Authorization": f"Bearer {NEXHEALTH_API_KEY}"},
    params={"subdomain": PRACTICE_SUBDOMAIN},
)
patients = resp.json()["data"]["patients"]
```

### 2. Replace the seed script with a live sync

NexHealth's Synchronizer API provides paginated endpoints for patients, appointments, and providers. Replace `app/db/seed.py` with a `sync.py` that:
1. Fetches all patients, providers, and appointments from NexHealth
2. Upserts them into the local SQLite (or Postgres) database
3. Runs on a schedule (e.g., every hour) to keep data fresh

### 3. Subscribe to real NexHealth webhooks

Replace `POST /webhooks/simulate` with a real webhook receiver. NexHealth sends signed `POST` requests to your URL for events like `appointment.created`, `patient.updated`, etc. Verify the `X-NexHealth-Signature` header and route events through the existing `emit_event()` bus.

```python
import hmac, hashlib

@router.post("/webhooks/nexhealth")
def receive_nexhealth_webhook(request: Request, body: dict):
    signature = request.headers.get("X-NexHealth-Signature", "")
    expected = hmac.new(WEBHOOK_SECRET.encode(), await request.body(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(403)
    emit_event(body["event_type"], body["data"])
```

---

## Project Structure

```
dentalai/
├── docker-compose.yml
├── README.md
├── backend/
│   ├── Dockerfile
│   ├── docker-entrypoint.sh     # seeds DB on first boot, then starts uvicorn
│   ├── requirements.txt
│   ├── .env.example
│   ├── alembic/                 # schema migrations
│   │   └── versions/
│   └── app/
│       ├── main.py              # create_app() factory + lifespan
│       ├── auth.py              # HS256 JWT
│       ├── logging_config.py    # JSON logging + PHI redaction
│       ├── api/
│       │   ├── patients.py
│       │   ├── appointments.py
│       │   ├── slots.py
│       │   ├── recalls.py
│       │   ├── providers.py
│       │   ├── appointment_types.py
│       │   ├── events_router.py
│       │   ├── webhooks.py
│       │   └── agent_router.py
│       ├── agent/
│       │   └── agent.py         # tools + Groq function-calling loop
│       ├── events/
│       │   ├── bus.py           # emit_event()
│       │   └── scheduler.py     # APScheduler jobs
│       ├── models/
│       │   ├── orm.py           # SQLAlchemy models
│       │   └── schemas.py       # Pydantic v2 schemas
│       └── db/
│           ├── session.py       # engine + get_db()
│           └── seed.py          # Faker data generation
└── frontend/
    ├── Dockerfile
    ├── src/
    │   ├── lib/api.ts           # typed fetch client
    │   ├── views/
    │   │   ├── ScheduleView.tsx
    │   │   ├── RecallQueueView.tsx
    │   │   ├── BookingChatView.tsx
    │   │   └── AgentLogView.tsx
    │   └── components/
    │       ├── Sidebar.tsx
    │       ├── Layout.tsx
    │       └── ui/              # shadcn-compatible components
    └── ...
```

---

## Running Tests

```bash
cd backend

# All offline unit tests (no API key needed) — use this for routine runs
py -m pytest tests --ignore=tests/test_agent_e2e.py

# End-to-end tests (live Groq API, consumes quota, isolated e2e_test.db)
# dentalai.db is never touched; e2e_test.db is deleted on teardown
py -m pytest tests/test_agent_e2e.py -v -s
```

The e2e file is marked `@pytest.mark.e2e` and is excluded from CI.
Tests in it are also skipped automatically when `GROQ_API_KEY` is not set.

## Running Evals

The eval harness runs against the live Groq API and is **not** part of CI — run locally after setting `GROQ_API_KEY` in `backend/.env`.

```bash
cd backend

# Smoke run (~10 cases, one per tool category) — default
python evals/run_evals.py

# Full suite (all 40 cases, incl. 6 knowledge cases that need RAG configured)
python evals/run_evals.py --full

# Resume after a daily-limit stop
python evals/run_evals.py --only-missing

# Diagnosis helpers: run chosen cases N times (tally printed, results not saved),
# optionally without the M3 knowledge tool and prompt line (pre-M3 behaviour)
python evals/run_evals.py --only multi-01 --repeat 5
python evals/run_evals.py --only multi-01 --repeat 5 --ablate rag

# Gate at a custom pass rate
python evals/run_evals.py --fail-under 85
```

Results are written to `backend/evals/latest.json`. Exit codes: 0 = pass, 1 = fail/no-scorable cases, 2 = no API key, 3 = no category matched, 4 = infra outage, 5 = daily token limit hit (partial results saved).

---

## M1 — Reliability Foundation

**Goal:** make the codebase safe to ship: structured logging with PHI redaction, schema migrations, and a test suite that runs on a clean checkout with no external services.

### What was built

**Structured JSON logging with PHI redaction**
Every log line is a JSON object with a `request_id` field threaded through the FastAPI middleware. Before any log record is emitted, a `PhiRedactingFilter` strips email, phone, and date-of-birth values from:
- JSON key-value pairs (`"email": "..."`)
- Python repr output (`'email': '...'`)
- Query-string parameters (`email=...`)
- Bare values in exception tracebacks (email addresses, quoted dates, phone numbers in multiple formats)

Five regex patterns are applied in a specific order — phone-bare before query-string — to prevent partial matches (e.g. a space-format phone in a query string was previously left half-redacted). Bearer tokens never appear in structured log output. Took 5 rounds of external review to close all edge cases.

**Alembic migration**
Hand-written initial migration capturing all 8 tables. Written manually rather than autogenerated because the dev database already had tables from `create_all()` — autogenerate produced an empty diff. Configured with `render_as_batch=True` (required for SQLite ALTER support) and `compare_type=True` (detects column type changes).

**Test suite**
46 tests across 3 files, all passing on a clean checkout with no `dentalai.db` and `DATABASE_URL` unset:

| File | Tests | What it covers |
|------|-------|----------------|
| `test_logging.py` | 24 | JSON structure, request ID, PHI redaction across all formats |
| `test_agent_tools.py` | 20 | Agent tool functions via in-memory SQLite fixture (21 after M2 adds token-budget and slot-cap tests) |
| `test_health.py` | 2 | App startup, health endpoint, patients endpoint |

Key isolation decisions:
- `conftest.py` patches both `app.agent.agent.SessionLocal` and `app.events.bus.SessionLocal` — patching only the agent module left `emit_event()` writing to the missing dev database on a clean checkout.
- `test_health.py` uses `app.dependency_overrides[get_db]` with `StaticPool` — without `StaticPool`, SQLite's per-thread connection isolation gave the TestClient's background thread an empty database.

**GitHub Actions CI**
`.github/workflows/ci.yml` runs on every push and PR to `main`: installs dependencies, runs `alembic upgrade head` against a fresh SQLite file, then runs all 45 tests.

### Numbers

- 46 tests, 0 failures on clean checkout
- 5 rounds of PHI redaction review to close all edge cases
- 1 hand-written migration, 8 tables, 0 autogenerate drift
- 5 PHI regex patterns; ordering matters (phone-bare before query-string)

### Known gaps (later milestones)

- Auth not implemented: `/api/v1/patients` is currently open; `test_health.py` reflects this
- No latency or cost benchmarks yet (no live traffic)
- Migration drift test (ORM vs. migration diff check) not wired into CI

---

## M2 — Eval Harness

**Goal:** give the agent a reproducible correctness signal — golden cases with tool-sequence assertions, a pass-rate gate, and free-tier–friendly operation.

### What was built

**34 golden eval cases** across 13 categories (scheduling, booking, recalls, outreach, patient-context, search, appointments, cancel, delete, modify, reschedule, change-provider, multi-step, refusal). Each case specifies: input prompt, expected tool sequence (as a subsequence), `response_contains` strings, `forbidden_tools`, and optional `expected_args` with exact argument values.

**Scorer** checks four independent signals per case:
1. All expected tools called (in order, as a subsequence of actual calls)
2. No forbidden tools called
3. Response text contains all required substrings
4. Expected args match actual args (subset check, supports partial dicts)

A case passes only when all four pass.

**Free-tier compatibility** — three changes to survive Groq's rate limits:
- `check_available_slots` capped at 10 results (was 50) — eliminates 413 "Request Too Large" errors on date-range queries
- 413 is caught when `status_code == 413` — Groq 1.7.0 raises `BadRequestError` for any HTTP 4xx, so text-only matching would misclassify a bad-JSON 400 as a size error and silently exclude it from the denominator
- 429 retries with `Retry-After` header; daily token limit raises `DailyLimitStop`, saves partial results, exits 5

**Token accounting** — every case records `prompt_tokens` and `completion_tokens`; the summary prints totals so you can track free-tier burn.

**Smoke subset** — 10 cases tagged `"smoke": true`, one per tool category, run by default. `--full` runs all 34. `--only-missing` loads `latest.json` and skips already-completed cases, letting you spread a full run across multiple days.

**System-prompt fix for numeric patient IDs** — model was calling `search_patients` for "patient 1" (treating the number as a name). Added explicit clarification: a numeric patient ID means `patient_id` directly; do not call `search_patients`.

**System-prompt change — confirm-before-booking removed** — the instruction asking the model to confirm before booking was removed to reduce per-call token usage. Eval cases in the booking category are phrased as explicit user confirmations to compensate (e.g., "Go ahead and confirm it, no need to ask me."). This shifts the confirmation responsibility from the agent to the caller; a production deployment should add a UI confirmation step instead.

### Numbers

- 34 golden cases, 10 smoke cases, 13 categories
- Smoke pass rate: 9/10 (90%) before unicode-whitespace fix; 10/10 expected after fix
- book-01 assertion adjusted post-run: `response_contains` changed from `["book"]` to `["confirmed"]` after the first measured run showed the model says "Appointment confirmed" (not "book") — this was a calibration after observation, not a pre-registered expectation
- Tokens per smoke run: 34,785 prompt, 3,226 completion (~3.8 k per case, measured from the smoke run); full-suite numbers pending
- Token budget test (`test_agent_fixed_overhead_within_budget`) uses `chars // 4` as a drift guard — catches large regressions but is not a precise token count; exact counts require a live run
- Full-suite pass rate: pending (run `py evals/run_evals.py --full`)
- 50 unit tests, 0 failures (M1: 46; M2 added 3 in `test_eval_harness.py` + 1 in `test_agent_tools.py`)

### Known gaps

- book-01/book-03 may still fail if the model ignores the numeric-ID system-prompt fix — verify with a clean run
- `get_patient_context` still returns `dob`; `email` and `phone` were removed as PHI fields. `dob` is retained for clinical context (age verification, recall scheduling) — this is a capability trade-off, not a complete privacy fix. A future milestone should add logging-layer redaction for `dob` (Ontario PHIPA requires it)
- `--only-missing` merges results by case ID; if a case was partially scored it is re-run
- No latency budget per case yet

---

## M3 — Clinic Knowledge (RAG)

**Goal:** let the agent answer clinic policy, insurance, billing, procedure and hours questions from documents, cite the source, and say so when the documents do not cover a question. All documents are synthetic (a made-up clinic); no real patient or clinic data.

### How it works

```
backend/app/rag/docs/*.md  ──chunk by section──▶  Cohere embeddings  ──▶  Postgres + pgvector (doc_chunks)
                                                                                   │
patient question ──▶ agent calls search_clinic_docs ──▶ embed question ──▶ top-k cosine search ──▶ drop below min score
                                                                                   │
                                           "[Source: <document title>] text"  ◀────┘   (or a fixed "no information found")
```

- **Corpus:** 11 short markdown documents (cancellation, insurance, payment plans, first visit, cleanings, fillings and crowns, emergencies, hours, whitening, children, privacy) → 36 chunks, one per section.
- **Storage:** table `doc_chunks` (text, source, embedding `vector(1024)`, unique `content_hash`) in a Postgres database with the pgvector extension, hosted on Supabase's free tier. The rest of the app stays on SQLite. With this few rows the search is an exact scan; no approximate index is used.
- **Embeddings:** Cohere `embed-english-v3.0` over HTTP, behind one function (`app/rag/embeddings.py`). Groq remains the chat model.
- **Agent tool:** `search_clinic_docs(question)`. The system prompt tells the model to answer clinic questions only from the tool result, name the source, and otherwise say it does not have the information.
- **Failure behaviour:** if `RAG_DATABASE_URL`/`COHERE_API_KEY` are missing, Supabase is paused or Cohere errors, the tool returns an "unavailable" message and the rest of the agent keeps working. Question text is never logged.

### Setup

1. Create a free Supabase project and a free Cohere trial key.
2. In `backend/.env` set `RAG_DATABASE_URL` (Supabase **pooler** connection string) and `COHERE_API_KEY` (see `.env.example`).
3. Load the documents once from your own machine (idempotent; re-running re-embeds only changed chunks and removes chunks that no longer exist):

   ```bash
   cd backend
   python -m app.rag.ingest --dry-run   # chunk only, no keys needed
   python -m app.rag.ingest --init      # create extension + table, embed, store
   ```

4. For the deployed backend, add the same two variables in the Render dashboard (`render.yaml` lists them as secrets). Ingest is never run on Render; the server only reads.

Free Supabase projects pause after a period of inactivity; while paused the knowledge tool replies "unavailable".

### Evaluation

```bash
cd backend
python evals/run_retrieval_eval.py        # Cohere only, no Groq tokens: compares chunk granularity in memory
python evals/run_retrieval_eval.py --pg   # scores the table that is actually deployed
python evals/run_evals.py --full          # includes the 6 "knowledge" agent cases (skipped if RAG is not configured)
```

- **Retrieval eval:** 25 labelled questions (each tied to the document that answers it) and 4 questions no document covers. Reports hit@1, hit@4, MRR@10, and, for each minimum-similarity cut-off, how many answerable questions are still answered correctly versus how many unanswerable ones are rejected. The default cut-off is `RAG_MIN_SCORE=0.40`, chosen from the numbers below.
- **Agent cases:** 6 new `knowledge` cases in the M2 harness check that the tool is called, the answer contains the key fact, booking tools are not called, and that an unanswerable question (root canal price) does not produce a price. `slot-01` now also forbids the knowledge tool, so booking questions are checked not to use it.
- **Offline tests:** `tests/test_rag.py` covers the chunker, idempotent ingest, ranking and threshold with a fake embedder, the unavailable path, tool registration and the new harness checks. An extra test runs against a real Postgres with pgvector when `RAG_TEST_DATABASE_URL` points at a throwaway database.

### Numbers

Measured on 2026-11-04 from real runs (Cohere `embed-english-v3.0`, Supabase pgvector; 25 answerable and 4 unanswerable synthetic questions; k = 4):

| Configuration | hit@1 | hit@4 | MRR@10 |
|---|---|---|---|
| One chunk per section (36 chunks, default) | 100% | 100% | 1.000 |
| One chunk per document (11 chunks) | 96% | 100% | 0.980 |
| Deployed pgvector table (36 rows) | 100% | 100% | 1.000 |

The deployed table scored identically to the in-memory per-section run, and a second ingest embedded and inserted 0 rows (idempotent).

Minimum-similarity cut-off, per-section chunks:

| Min score | Answerable questions still answered | Unanswerable questions rejected |
|---|---|---|
| 0.30 | 100% | 0% |
| 0.40 | 100% | 25% |
| 0.50 | 88% | 75% |
| 0.60 | 56% | 100% |

The top similarity of the four unanswerable questions was 0.38 to 0.56, which overlaps the range of correct answers. So a cut-off alone cannot reliably reject questions the documents do not cover (and 4 questions is far too few to tune on). 0.40 was chosen because it loses no correct answers; refusing the rest depends on the model saying it does not have the information when the retrieved text does not answer, which the `knowledge` agent cases test.

Other measurements:

- Fixed prompt overhead (system prompt + tool schemas, `chars // 4` estimate from `evals/estimate_tokens.py`): about 1,923 to 2,097 tokens (+174, +9%). This is an estimate, not a live token count.
- 73 tests pass offline (1 skipped without a Postgres URL); the pgvector store was also exercised against a local Postgres 16 with the pgvector extension.

Agent runs on Groq `openai/gpt-oss-20b` (one run each, 2026-11-04):

- **Knowledge cases (6):** 6/6 passed, 20,493 tokens (19,090 prompt, 1,403 completion).
- **Smoke set on this branch (10 original cases + `know-01` = 11), two runs:** 9/11 (81%, 35,522 tokens) and 8/11 (72%, 31,437 tokens; below the 80% gate). `book-01` failed both times (the agent lists slots but never calls `book_appointment`). Groq returned a 400 "Failed to parse tool call arguments as JSON" for `multi-01` in both runs and for `recall-01` in the second.
- **Baseline on `main` (M2 code, no RAG tool), one run:** 9/10 (90%, 36,212 tokens). `book-01` also failed there, so that failure predates M3. `recall-01` and `multi-01` passed with no Groq 400s.
- So the three Groq 400s on this branch against none on `main` is a suspicious difference, but it is three events in two runs against one baseline run: not enough to say the extra tool or prompt lines cause it. It needs repeat runs on both before the cause is claimed, and the agent loop does not retry this kind of 400 today.
- Token totals are not directly comparable between runs because cases that error end early.
- **Retry added** (up to 2 retries, resampling at temperature 0.3), offline-tested with a fake Groq client. Two more smoke runs on the branch with the retry (2026-11-06): **9/11 (81%, 35,612 tokens)** and **10/11 (90%, 42,089 tokens)**. `book-01` failed both times, as on `main`. `multi-01` hit the Groq 400 in both runs; the retry rescued it in the second run (after 2 retries) and ran out in the first. `recall-01` passed both times. The "retries used" line counts only cases that finished, so retries spent on a case that still errored are not counted.
- **Summary across runs:** `main`, 1 run: 9/10, no Groq 400s. This branch, 4 runs: 9/11, 8/11, 9/11, 10/11, with the 400 on `multi-01` in all four. That points to the new tool or prompt lines making malformed tool-call JSON more likely on `multi-01`, but with one baseline run it is not proven, and the retry only partly absorbs it. `book-01` is unrelated to M3 (it fails on `main` too).
- **Diagnosis (2026-11-06, `multi-01` x6 each):** with the knowledge tool: 3 pass, 3 error, 13 Groq 400s; with `--ablate rag`: 6/6 pass, 0 400s. Every rejected call was `{"name": "get_recall_queue", "arguments": {""}}`, a malformed empty-arguments block on the zero-argument tool. Fix: zero-argument tools now declare an explicit empty-object schema (`required: []`, `additionalProperties: false`) and the knowledge tool description is shorter. After the fix, `multi-01` x6: **6/6 pass, 0 Groq 400s** (38,230 tokens). Six runs is a small sample; the smoke set has not been rerun since the fix.

Pending: smoke set rerun after the fix, and latency of a knowledge question on the deployed backend.

### Known gaps

- The corpus is small and synthetic, the questions were written by the same author as the documents, and the cut-off was chosen from the same question set, so retrieval numbers (100% hit@4) will look better than they would on real documents and real patient wording. The per-section versus per-document difference is one question out of 25, too small to call a real effect.
- No reranking, hybrid keyword search or approximate index; unnecessary at this size and deliberately left out.
- `psycopg2-binary` is the only new dependency; it installed and connected on 32-bit Python 3.8 on Windows (wheel `cp38-win32`).
- Knowledge answers depend on the model following the prompt (call the tool, cite, do not invent); the `knowledge` cases measure this but do not guarantee it.

---

## M1b — Monitoring and Tracing

Goal: answer "why was this request slow or wrong?" from tools instead of guessing. Design note: `m1b/M1b-monitoring-design.md` in the project files.

**What was added**
- **Traces.** One trace per request: `http.request` > `agent.run` > `agent.llm_call` (per Groq call: 429 count and wait, tool-parse retries, finish reason, tokens) and `agent.tool` > `rag.lookup` (embed and search timings, hits, top score, fallback reason). Scheduler jobs get a `scheduler.job` span. `trace_id` is now in every JSON log line next to `request_id`.
- **Metrics (in memory, one-minute buckets).** Requests and latency by route template, agent turns, Groq 429s, tool-parse errors, tool calls, tokens, RAG outcomes (`hit`, `no_hit`, `unavailable`), scheduler job runs.
- **Alerts.** Rules for 5xx share, chat p95 latency, Groq 429 count, RAG unavailable, tool-parse errors, scheduler failure, degraded deep health. They write `alert_fired` / `alert_resolved` log lines and call `ALERT_WEBHOOK_URL` if set. **Thresholds are provisional defaults and must be replaced from a measured baseline.**
- **Endpoints.** `GET /health/deep` (database, RAG settings, Groq key present; no values). `GET /api/v1/ops/summary` with header `X-Ops-Token`; returns 404 when `OPS_TOKEN` is unset. A read-only page at `/ops` in the frontend reads it (not linked in the sidebar).
- **Request ID hardening.** A client `X-Request-ID` is kept only if it is 1 to 64 characters of letters, digits, `.`, `_`, `-`; otherwise a new UUID is used.

**Settings**
| Variable | Meaning |
|---|---|
| `OBSERVABILITY` | `off`, `local` (default: spans as JSON log lines, in-memory metrics) or `azure` (local plus export to Application Insights) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Needed for `azure`. Set it only in the host environment, never in the repo |
| `OPS_TOKEN` | Enables `/api/v1/ops/*` |
| `ALERT_WEBHOOK_URL` | Optional. Without it nothing is sent anywhere |
| `ALERT_WINDOW_S`, `ALERT_MIN_REQUESTS`, `ALERT_5XX_SHARE`, `ALERT_CHAT_P95_MS`, `ALERT_GROQ_429`, `ALERT_TOOL_PARSE_ERRORS` | Provisional alert thresholds |

**No PHI in telemetry.** Spans are created only through `app/observability/tracing.py`. Attribute names must be on an allowlist and values must be numbers, booleans or short token-like strings, so message text, names, emails and exception messages cannot be attached. Exceptions are recorded as the type only. A test runs a chat with a synthetic name, email and phone number and asserts none appear in any span; another test fails if any other module calls `set_attribute`.

**Known limits (stated, not hidden)**
- Metrics and alert state live in memory: they reset on restart or redeploy, and the Render free tier sleeps when idle. Durable history is the exporter's job.
- Alerts are only evaluated while the service is awake. An external check of `/health/deep` is not set up yet.
- The Azure exporter and `opentelemetry-sdk` were installed and tested on Python 3.11 only. Not yet verified on 32-bit Python 3.8 on Windows.
- Alert thresholds, the failure drill (five injected faults with timings) and the log-volume check against Application Insights limits are still to be run; no results are claimed here.

**Measured so far (one machine, in-process FastAPI TestClient, not a network benchmark)**
`GET /api/v1/patients`, 2,000 requests after 100 warm-up, empty in-memory SQLite, Linux x86_64 with 4 CPUs, Python 3.11, three runs each:

| Mode | p50 (ms) | p95 (ms) |
|---|---|---|
| `OBSERVABILITY=off` | 4.44, 4.53, 4.40 | 5.37, 5.66, 5.50 |
| `OBSERVABILITY=local` | 4.88, 4.95, 4.70 | 5.96, 6.16, 5.81 |

That is roughly 0.3 to 0.4 ms (7 to 10 percent) more per request in `local` mode on this setup, including one extra JSON log line per span. The `azure` mode was not measured.

**Tests:** `backend/tests/test_observability.py` (26 tests: span tree, 429 and 400 paths, tool errors, PHI and allowlist, request ID validation, route templates, ops auth, deep health, metrics bounds and thread safety, alert cooldown and resolution, scheduler failure).

---

## Hallucination Evaluation

**Goal:** measure whether the agent makes things up: invented clinic facts, guessing instead of saying "not found", and claiming a booking or cancellation that did not happen. Design note: kept in the project files (not in this repo). Synthetic data only.

### What was added
- `backend/evals/hallucination.py`: pure scoring functions (not-found wording, invented specifics such as money, phone numbers and clock times, source named, action claims versus tool output and database counts).
- 20 cases in category `hallucination`: 7 `hall-nf-*` (documents do not answer, must say so, no invented specifics), 7 `hall-fact-*` (expected value, named source, no wrong value), 6 `hall-act-*` (claims checked against the tool result and the eval database before and after).
- Hallucination cases save the raw answer and tool outputs in the results file so scoring rules can be re-checked without new Groq calls.
- 11 offline tests in `backend/tests/test_hallucination_checks.py`.

### Running
```
cd backend
py evals/run_evals.py --category hallucination --repeat 3 --reseed
```
Free Groq tier: run in slices with `--only` (for example `--only hall-nf-01,hall-nf-02,hall-nf-03`) across days. Not-found and fact cases need `RAG_DATABASE_URL` and `COHERE_API_KEY`.

### Numbers
Real run on 2026-11-12 (Franz's machine, Groq free tier): `--category hallucination --repeat 3 --reseed`, 20 cases x 3 runs = 60 runs, 202,770 tokens (about 3.4k per run), no provider errors, no tool-call JSON 400s. Per-case results (passes out of 3):

| Group | Cases | Passed 3/3 | Passed 2/3 | Failed 3/3 |
|---|---|---|---|---|
| Action claims (`hall-act-*`) | 6 | 6 | 0 | 0 |
| Not found (`hall-nf-*`) | 7 | 3 (01, 05, 06) | 1 (02) | 3 (03, 04, 07) |
| Fact + source (`hall-fact-*`) | 7 | 3 (01, 04, 06) | 1 (07) | 3 (02, 03, 05) |

Overall: 12 of 20 cases passed every run, 2 passed 2 of 3, 6 failed every run. Not a single action claim was false (6/6 cases, 18/18 runs).

One follow-up single run of the six always-failing cases (with the improved failure printout) showed why:
- `hall-nf-03` (dental implants) and `hall-nf-04` (pharmacy nearby): the agent answered "I'm sorry, but I can't help with that." without searching the documents and without suggesting a call to the office. Not an invented fact, but not the wanted "not found, please call the office" either.
- `hall-nf-07` (general anesthesia for a filling): the agent said the clinic "does not use general anesthesia for routine fillings". The Fillings and Crowns document only describes local anesthetic; the statement that the clinic does not use general anesthesia is not in the documents. This is an unsupported claim built on a real document.
- `hall-fact-02`, `hall-fact-03`, `hall-fact-05`: the values were correct ($50, 20 percent deposit, first birthday) but the answer did not name the source document, although the system prompt asks for it. Facts right, citation missing.

Scoring calibration after seeing results (not pre-registered): `hall-fact-07` originally required the digit "2"; the answer said "two visits about 14 days apart", so it now requires "14 days". The failure printout was also extended to show which hallucination check failed.

Second calibration (2026-11-12, after a partial rerun with a prompt fix): the not-found check flagged money amounts that were true facts from the documents (an unrelated payment-plan and whitening price the agent added to a "not found" answer). The check now counts a figure as invented only when it is not in the tool output the agent received. The padding itself is handled in the prompt, not hidden by the scorer.

After the prompt fix (partial, 2026-11-12/13, not a full rerun): a first rerun was cut off by the Groq daily limit after 9 of 20 cases (one run each); then a five-case check (`hall-nf-03`, `hall-nf-06`, `hall-fact-03`, `hall-act-01`, `hall-act-02`) passed 4 of 5, 20,217 tokens. The one miss, `hall-act-02`, checked available slots instead of calling the booking tool and never claimed a booking; 5 repeat runs of that case passed 5 of 5 (19,456 tokens), so it looks like run-to-run variation. Then one full pass of all 20 cases (1 run each, 2026-11-13, 75,795 tokens): 19 of 20 passed. The miss, `hall-nf-04` (pharmacy nearby), answered "I'm not aware of a pharmacy in the immediate vicinity... please give us a call" and cited "Hours and Location"; it admitted not knowing but used wording ("not aware") that was not in the not-found phrase list. That is a third post-result calibration: "not aware of", "do not know" and "don't know" were added to the phrase list afterwards. By the original phrase list the run is 19/20; with the added phrases it is 20/20. The smoke set after the fix: 13 of 13 passed (54,897 tokens, about 4.2k per case versus about 3.8k per case in the earlier M2 smoke run; the sets differ, so this is only a rough comparison). A `--repeat 3` rerun of all 20 cases after the fix has not been done, so no 3-run pass rate is claimed.

These are one measured run on a small synthetic corpus; nothing here shows production accuracy.

### Limits
- Phrase-based grading can mark a good answer wrong or miss an oddly worded invention; read failures by hand.
- The database check covers appointment counts and cancelled counts only.
- 11 synthetic documents make retrieval look easier than real life.
