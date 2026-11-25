import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from app.models import metadata

POSTGRES_IMAGE = "postgres:17.12-trixie"


async def _create_schema(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    await engine.dispose()


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        asyncio.run(_create_schema(url))
        yield url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url)
    yield engine
    await engine.dispose()
