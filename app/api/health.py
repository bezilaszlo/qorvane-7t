from fastapi import APIRouter
from sqlalchemy import text

from app.db import ConnDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(conn: ConnDep) -> dict[str, str]:
    await conn.execute(text("SELECT 1"))
    return {"status": "ready"}
