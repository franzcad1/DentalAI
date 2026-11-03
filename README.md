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

# Full suite (all 34 cases)
python evals/run_evals.py --full

# Resume after a daily-limit stop
python evals/run_evals.py --only-missing

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
