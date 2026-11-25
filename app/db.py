from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.config import Settings

# Per worker process: WORKERS * (POOL_SIZE + MAX_OVERFLOW) must stay below
# Postgres max_connections (100).
POOL_SIZE = 5
MAX_OVERFLOW = 5
POOL_TIMEOUT = timedelta(seconds=5)
CONNECT_TIMEOUT = timedelta(seconds=5)

# Postgres-side guardrails per API connection; migrations use their own engine without them.
STATEMENT_TIMEOUT = timedelta(seconds=5)
LOCK_TIMEOUT = timedelta(seconds=2)
IDLE_IN_TRANSACTION_TIMEOUT = timedelta(seconds=10)


class DatabaseUnavailableError(Exception):
    pass


def _ms(td: timedelta) -> str:
    return str(int(td.total_seconds() * 1000))


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_timeout=POOL_TIMEOUT.total_seconds(),
        pool_pre_ping=True,
        connect_args={
            "timeout": CONNECT_TIMEOUT.total_seconds(),
            "server_settings": {
                "application_name": "sensor-api",
                "statement_timeout": _ms(STATEMENT_TIMEOUT),
                "lock_timeout": _ms(LOCK_TIMEOUT),
                "idle_in_transaction_session_timeout": _ms(IDLE_IN_TRANSACTION_TIMEOUT),
            },
        },
    )


async def get_conn(request: Request) -> AsyncIterator[AsyncConnection]:
    engine: AsyncEngine = request.app.state.engine
    async with AsyncExitStack() as stack:
        try:
            conn = await stack.enter_async_context(engine.begin())
        except OSError as exc:  # refused, DNS or timeout while connecting
            raise DatabaseUnavailableError from exc
        yield conn


async def get_read_conn(request: Request) -> AsyncIterator[AsyncConnection]:
    engine: AsyncEngine = request.app.state.engine
    async with AsyncExitStack() as stack:
        try:
            conn = await stack.enter_async_context(engine.connect())
            # AUTOCOMMIT: no BEGIN/COMMIT round trips for pure reads
            conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        except OSError as exc:
            raise DatabaseUnavailableError from exc
        yield conn


# scope="function": commit runs before the response is sent (the default "request"
# scope would commit after it), so a 2xx always means the transaction committed.
ConnDep = Annotated[AsyncConnection, Depends(get_conn, scope="function")]
ReadConnDep = Annotated[AsyncConnection, Depends(get_read_conn, scope="function")]
