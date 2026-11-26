import os
import sys
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Configure test environment before importing app modules
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://hb_admin:hb_dev_password@127.0.0.1:5432/hormozgan_bidar_test",
)
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["DATABASE_ADMIN_URL"] = TEST_DB_URL
os.environ["COOKIE_SECURE"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings

get_settings.cache_clear()

import app.db as app_db
from app.main import app
from app.models import Base
from app.seed import DEMO_STAFF, upsert_user


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_database():
    test_engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    app_db.engine = test_engine
    app_db.AsyncSessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )

    async with test_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION hb_forbid_audit_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit_log is strictly append-only';
            END;
            $$ LANGUAGE plpgsql;
        """))
        await conn.execute(text("""
            CREATE TRIGGER trg_audit_log_append_only
            BEFORE UPDATE OR DELETE ON audit_log
            FOR EACH ROW EXECUTE FUNCTION hb_forbid_audit_mutation();
        """))
        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION hb_forbid_task_event_update() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'task_events is append-only (UPDATE forbidden)';
            END;
            $$ LANGUAGE plpgsql;
        """))
        await conn.execute(text("""
            CREATE TRIGGER trg_task_events_no_update
            BEFORE UPDATE ON task_events
            FOR EACH ROW EXECUTE FUNCTION hb_forbid_task_event_update();
        """))

    async with app_db.AsyncSessionLocal() as db:
        for uname, dname, jtitle, dept, lvl, otype, roles in DEMO_STAFF:
            await upsert_user(db, uname, dname, "TestPass@1405", jtitle, dept, lvl, otype, roles)
        await db.commit()

    yield

    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with app_db.AsyncSessionLocal() as session:
        yield session


async def login_as(username: str, password: str = "TestPass@1405") -> tuple[AsyncClient, str, dict]:
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:3000")
    csrf_resp = await client.get("/api/v1/auth/csrf")
    csrf = csrf_resp.json()["csrf_token"]
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers={"X-CSRF-Token": csrf, "Origin": "http://localhost:3000"},
    )
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    data = resp.json()
    return client, data["csrf_token"], data["user"]
