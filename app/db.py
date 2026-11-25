from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.config import Settings


class DatabaseUnavailableError(Exception):
    pass


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
        connect_args={
            "timeout": settings.db_connect_timeout,
            "server_settings": {
                "application_name": "sensor-api",
                "statement_timeout": str(settings.db_statement_timeout_ms),
                "idle_in_transaction_session_timeout": str(
                    settings.db_idle_in_transaction_timeout_ms
                ),
                "lock_timeout": str(settings.db_lock_timeout_ms),
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
