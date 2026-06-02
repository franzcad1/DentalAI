# DentalAI — AI-Powered Dental Practice Management

A portfolio project demonstrating production-grade AI engineering with Python, FastAPI, LangChain, and React. DentalAI mirrors the structure of the [NexHealth Synchronizer API](https://docs.nexhealth.com) — a real dental practice management platform — without requiring a live account. All data runs locally on SQLite with Faker-generated mock patients, providers, and appointments.

> **Portfolio goal:** Show end-to-end AI product engineering — typed REST API, event-driven background jobs, an LLM agent that books appointments and manages patient recalls, and a polished React dashboard.

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
│                  /api/v1/agent/chat ──────────────┐             │
└──────────────────────────┬──────────────────────  │  ───────────┘
                           │                        │
┌──────────────────────────▼──────────┐   ┌─────────▼────────────┐
│        SQLAlchemy + SQLite          │   │   LangChain Agent     │
│                                     │   │                       │
│  Patient  Provider  Location        │   │  check_available_     │
│  Appointment  AvailableSlot         │   │    slots()            │
│  PatientRecall  Event               │   │  book_appointment()   │
│                                     │   │  get_patient_context()│
└──────────────────────────┬──────────┘   │  get_recall_queue()   │
                           │              │  draft_recall_        │
┌──────────────────────────▼──────────┐   │    message()          │
│        APScheduler (background)     │   └───────────────────────┘
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
| **OpenAI SDK** | 1.40+ | Function-calling API for tool-use agent loop |
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

# 2. Set your OpenAI key (optional — all non-agent endpoints work without it)
cp backend/.env.example backend/.env
# Edit backend/.env and set OPENAI_API_KEY=sk-...

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

cp .env.example .env               # add OPENAI_API_KEY if you want agent chat
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

All endpoints except `GET /health` require a `Bearer` token in the `Authorization` header.

**Getting the dev token:** The token is printed to the backend console on startup:
```
INFO | app.main | Test Bearer token (valid 24 h):
INFO | app.main |   eyJhbGci...
```

Paste it into the frontend's token gate UI, or set `VITE_DEV_TOKEN=<token>` in `frontend/.env` to skip the gate entirely.

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

The agent is built on **OpenAI function calling** (`gpt-4o-mini`) with five tools defined using LangChain's `@tool` decorator. Each tool opens its own database session and returns a string — either JSON data or a human-readable confirmation.

### Agent Loop

```
User message
    │
    ▼
POST /chat/completions (with OPENAI_TOOL_SCHEMAS)
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
| `check_available_slots(date_from, date_to, provider_id?)` | Returns unbooked slots in a date range. Enriched with provider names. |
| `book_appointment(patient_id, slot_id, appointment_type_id, notes?)` | Creates an Appointment, marks the slot as booked, fires `appointment.booked` event. Validates against double-booking. |
| `get_patient_context(patient_id)` | Returns demographics + last appointment + current recall status for a patient. |
| `get_recall_queue()` | Returns all overdue pending recalls sorted by `days_overdue` descending. |
| `draft_recall_message(patient_id)` | Generates a personalised outreach message with tone escalation: gentle (≤30 days) → moderate (31–90) → urgent (>90 days overdue). |

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
│   └── app/
│       ├── main.py              # create_app() factory + lifespan
│       ├── auth.py              # HS256 JWT
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
│       │   └── agent.py         # tools + OpenAI function-calling loop
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

# Tool unit tests (no API key needed)
py -m pytest tests/test_agent_tools.py -v    # 6 tests

# Health smoke test
py -m pytest tests/test_health.py -v

# End-to-end agent tests (requires OPENAI_API_KEY in .env)
py -m pytest tests/test_agent_e2e.py -v -s
```
