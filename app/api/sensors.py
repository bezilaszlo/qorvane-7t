from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import select

from app.db import ReadConnDep
from app.models import readings
from app.schemas import SensorMetric, SensorsResponse

router = APIRouter(prefix="/api/v1", tags=["sensors"])


@router.get("/sensors")
async def list_sensors(conn: ReadConnDep) -> SensorsResponse:
    since = datetime.now(UTC) - timedelta(hours=24)
    stmt = (
        select(readings.c.sensor_id, readings.c.metric)
        .where(readings.c.ts >= since)
        .distinct()
        .order_by(readings.c.sensor_id, readings.c.metric)
    )
    rows = (await conn.execute(stmt)).all()
    return SensorsResponse(sensors=[SensorMetric(**row._mapping) for row in rows])
