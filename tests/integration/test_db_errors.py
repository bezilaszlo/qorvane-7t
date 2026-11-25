import socket
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import Settings, get_settings
from app.db import (
    IDLE_IN_TRANSACTION_TIMEOUT,
    LOCK_TIMEOUT,
    STATEMENT_TIMEOUT,
    create_engine,
)
from app.errors import classify_db_error
from app.models import readings

pytestmark = pytest.mark.anyio


def ms(td) -> str:
    return str(int(td.total_seconds() * 1000))


async def test_statement_timeout_is_503(engine: AsyncEngine):
    with pytest.raises(SQLAlchemyError) as caught:
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL statement_timeout = 10"))
            await conn.execute(text("SELECT pg_sleep(1)"))
    assert classify_db_error(caught.value) == (503, {"detail": "query timed out"})


async def test_lock_timeout_is_503(engine: AsyncEngine):
    row = {"sensor_id": "s", "metric": "m", "ts": datetime(2026, 1, 1, tzinfo=UTC), "value": 1.0}
    async with engine.connect() as holder:
        await holder.execute(text("LOCK TABLE readings IN ACCESS EXCLUSIVE MODE"))
        with pytest.raises(SQLAlchemyError) as caught:
            async with engine.begin() as conn:
                await conn.execute(text("SET LOCAL lock_timeout = 10"))
                await conn.execute(insert(readings), row)
        await holder.rollback()
    assert classify_db_error(caught.value) == (503, {"detail": "database busy"})


async def test_integrity_error_is_generic_500(engine: AsyncEngine):
    row = {"sensor_id": "dup", "metric": "m", "ts": datetime(2026, 1, 1, tzinfo=UTC), "value": 1.0}
    with pytest.raises(SQLAlchemyError) as caught:
        async with engine.begin() as conn:
            await conn.execute(insert(readings), [row, row])
    assert classify_db_error(caught.value) == (500, {"detail": "internal server error"})


async def test_pool_exhausted_is_503(database_url: str):
    engine = create_async_engine(database_url, pool_size=1, max_overflow=0, pool_timeout=0.1)
    try:
        async with engine.connect():
            with pytest.raises(SQLAlchemyError) as caught:
                async with engine.connect():
                    pass
    finally:
        await engine.dispose()
    assert classify_db_error(caught.value) == (503, {"detail": "database unavailable"})


async def test_guardrails_applied(database_url: str):
    engine = create_engine(Settings(database_url=database_url))
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT name, setting FROM pg_settings WHERE name IN "
                    "('statement_timeout', 'lock_timeout', "
                    "'idle_in_transaction_session_timeout', 'application_name')"
                )
            )
            settings = dict(rows.all())
    finally:
        await engine.dispose()
    assert settings == {
        "statement_timeout": ms(STATEMENT_TIMEOUT),
        "lock_timeout": ms(LOCK_TIMEOUT),
        "idle_in_transaction_session_timeout": ms(IDLE_IN_TRANSACTION_TIMEOUT),
        "application_name": "sensor-api",
    }


def test_ready_is_503_when_database_refuses_connections(monkeypatch: pytest.MonkeyPatch):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    monkeypatch.setenv("DATABASE_URL", f"postgresql+asyncpg://u:p@127.0.0.1:{port}/db")
    get_settings.cache_clear()
    try:
        from app.main import app

        with TestClient(app) as client:
            response = client.get("/ready")
    finally:
        get_settings.cache_clear()
    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}
