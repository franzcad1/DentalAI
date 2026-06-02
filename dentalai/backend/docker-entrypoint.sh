#!/bin/bash
# docker-entrypoint.sh
# Runs the seed script only when the database is empty, then starts the server.
# This makes `docker-compose up` fully self-contained on first boot.
set -e

echo "==> Checking database state..."

# Python snippet: create tables if missing, print 'yes' if seed needed
NEEDS_SEED=$(python -c "
from sqlalchemy import text
from app.db.session import engine, Base
from app.models import orm  # registers all ORM models with Base

# Idempotent: creates tables that don't exist yet
Base.metadata.create_all(bind=engine)

try:
    with engine.connect() as conn:
        count = conn.execute(text('SELECT COUNT(*) FROM patients')).scalar()
    print('no' if (count or 0) > 0 else 'yes')
except Exception:
    print('yes')
")

if [ "$NEEDS_SEED" = "yes" ]; then
    echo "==> Database is empty — running seed script..."
    python -m app.db.seed
    echo "==> Seed complete."
else
    echo "==> Database already populated — skipping seed."
fi

echo "==> Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
