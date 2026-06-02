"""Application factory.

Using create_app() instead of a module-level `app` instance means:
- Tests can spin up isolated app instances without shared state.
- Startup/shutdown lifespan logic is co-located and easy to extend.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import appointments, patients, recalls, slots, webhooks
from app.auth import create_access_token
from app.db.session import Base, engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Create all tables on startup (idempotent — safe to call repeatedly)
    Base.metadata.create_all(bind=engine)
    token = create_access_token()
    logger.info("=" * 60)
    logger.info("DentalAI dev server ready")
    logger.info("Test Bearer token (valid 24 h):")
    logger.info("  %s", token)
    logger.info("=" * 60)
    yield
    # Teardown hook — add cleanup (e.g. Redis disconnect) here later


def create_app() -> FastAPI:
    app = FastAPI(
        title="DentalAI API",
        description="Mock dental practice management system — NexHealth Synchronizer-style API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check is intentionally unauthenticated
    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(patients.router, prefix="/api/v1")
    app.include_router(appointments.router, prefix="/api/v1")
    app.include_router(slots.router, prefix="/api/v1")
    app.include_router(recalls.router, prefix="/api/v1")
    app.include_router(webhooks.router, prefix="/api/v1")

    return app


app = create_app()
