from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, status
from sqlalchemy import ARRAY, DateTime, Double, Text, bindparam, func, select
from sqlalchemy.dialects.postgresql import insert

from app.db import ConnDep
from app.errors import validation_error
from app.models import readings
from app.schemas import IngestResult, ReadingsBatch

router = APIRouter(prefix="/api/v1", tags=["readings"])

MAX_FUTURE = timedelta(minutes=5)


@router.post("/readings", status_code=status.HTTP_201_CREATED)
async def ingest_readings(batch: ReadingsBatch, conn: ConnDep) -> IngestResult:
    now = datetime.now(UTC)
    points = []
    for i, item in enumerate(batch.readings):
        ts = item.ts or now
        if ts > now + MAX_FUTURE:
            raise validation_error(
                ("body", "readings", str(i), "ts"),
                "timestamp must not be more than 5 minutes in the future",
                "value_error",
            )
        points.extend(
            {"sensor_id": item.sensor_id, "metric": metric, "ts": ts, "value": value}
            for metric, value in item.metrics.items()
        )
    # Four array parameters unnested server-side: a plain multi-row VALUES would need
    # 4 binds per point and exceed asyncpg's 32767-argument cap at 10,000 points.
    columns = {
        "sensor_id": ARRAY(Text),
        "metric": ARRAY(Text),
        "ts": ARRAY(DateTime(timezone=True)),
        "value": ARRAY(Double),
    }
    rows = select(*(func.unnest(bindparam(name, type_=type_)) for name, type_ in columns.items()))
    # ON CONFLICT skips duplicates (stored or within the batch): inserted counts real
    # rows, duplicates is the remainder.
    stmt = insert(readings).from_select(list(columns), rows).on_conflict_do_nothing()
    result = await conn.execute(stmt, {name: [p[name] for p in points] for name in columns})
    inserted = result.rowcount
    return IngestResult(inserted=inserted, duplicates=len(points) - inserted)
