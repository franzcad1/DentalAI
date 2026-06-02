"""Application factory.

Using create_app() instead of a module-level `app` instance means:
- Tests can spin up isolated app instances without shared state.
- Startup/shutdown lifespan logic is co-located and easy to extend.

Lifespan sequence:
  1. Create all DB tables (idempotent).
  2. Start APScheduler background jobs.
  3. Print a dev Bearer token to the console.
  4. (on shutdown) Stop the scheduler gracefully.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import appointments, patients, recalls, slots, webhooks
from app.api.agent_router import router as agent_router
from app.auth import create_access_token
from app.db.session import Base, engine
from app.events.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ── Startup ──────────────────────────────────────────────────────────
    # Create all tables on startup (safe to call repeatedly; no-ops if exist)
    Base.metadata.create_all(bind=engine)

    # Start APScheduler background jobs
    start_scheduler()

    # Print a dev token so you can hit authenticated endpoints immediately
    token = create_access_token()
    logger.info("=" * 60)
    logger.info("DentalAI dev server ready")
    logger.info("Test Bearer token (valid 24 h):")
    logger.info("  %s", token)
    logger.info("=" * 60)

    yield  # ─── server is running ───

    # ── Shutdown ─────────────────────────────────────────────────────────
    stop_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(
        title="DentalAI API",
        description=(
            "Mock dental practice management system — NexHealth Synchronizer-style API "
            "with LangChain AI scheduling and recall agent."
        ),
        version="0.2.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check — intentionally unauthenticated
    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "version": "0.2.0"}

    # NexHealth-style CRUD routes
    app.include_router(patients.router, prefix="/api/v1")
    app.include_router(appointments.router, prefix="/api/v1")
    app.include_router(slots.router, prefix="/api/v1")
    app.include_router(recalls.router, prefix="/api/v1")
    app.include_router(webhooks.router, prefix="/api/v1")

    # AI agent
    app.include_router(agent_router, prefix="/api/v1")

    return app


app = create_app()
