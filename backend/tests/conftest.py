"""Global test isolation — this file MUST set the DB env var before any `app.*` import.

backend/.env points DATABASE_URL at the production Aliyun RDS. Without the override
below, any test that touches app.database (auth router, get_current_user, ...) would
read or even WRITE production data. pydantic-settings gives environment variables
precedence over the .env file, so an unconditional os.environ assignment here —
executed during conftest import, which happens before test modules are collected —
binds app.config.Settings / app.database.engine to an in-memory SQLite database for
the whole pytest session.

SQLAlchemy (>=2.0) automatically picks StaticPool for a bare `sqlite+aiosqlite://`
URL, so all sessions share one single in-memory database.
"""
import os

# Force (not setdefault): a developer shell may already export a real DATABASE_URL.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.database import Base, engine  # noqa: E402

_tables_created = False


@pytest.fixture
async def _app_db_tables():
    """Create all app tables on the shared in-memory engine, once per session.

    Function-scoped (not session-scoped) on purpose: a session-scoped async fixture
    would need a session-scoped event loop, and keeping it lazy means test modules
    that never touch the app database stay completely unaffected.
    """
    global _tables_created
    if not _tables_created:
        from app import models  # noqa: F401  # register all models on Base.metadata

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _tables_created = True


@pytest.fixture
async def client(_app_db_tables):
    """HTTP client against the FastAPI app (tables guaranteed to exist)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# Imported late so that the env-var assignment above always runs first.
from app.main import app  # noqa: E402, F401
