from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AwareDatetime
from sqlalchemy import func, select

from app.db import ReadConnDep
from app.errors import validation_error
from app.models import readings
from app.ranges import RangeError, resolve_range
from app.schemas import Metric, SensorId, Stat, StatRow, StatsResponse

router = APIRouter(prefix="/api/v1", tags=["stats"])

AGGREGATES = {"min": func.min, "max": func.max, "sum": func.sum, "avg": func.avg}


@router.get("/stats")
async def get_stats(
    conn: ReadConnDep,
    metric: Annotated[list[Metric], Query(min_length=1)],
    stat: Stat,
    sensor_id: Annotated[list[SensorId] | None, Query()] = None,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
) -> StatsResponse:
    try:
        start, end = resolve_range(start, end, datetime.now(UTC))
    except RangeError as exc:
        raise validation_error(
            ("query", exc.field) if exc.field else ("query",), exc.message, "value_error"
        ) from exc

    stmt = (
        select(
            readings.c.sensor_id,
            readings.c.metric,
            AGGREGATES[stat](readings.c.value).label("value"),
            func.count().label("count"),
        )
        .where(readings.c.metric.in_(metric))
        # half-open [start, end)
        .where(readings.c.ts >= start, readings.c.ts < end)
        .group_by(readings.c.sensor_id, readings.c.metric)
        .order_by(readings.c.sensor_id, readings.c.metric)
    )
    if sensor_id:
        stmt = stmt.where(readings.c.sensor_id.in_(sensor_id))
    rows = (await conn.execute(stmt)).all()
    return StatsResponse(
        stat=stat,
        start=start,
        end=end,
        results=[StatRow(**row._mapping) for row in rows],
    )
