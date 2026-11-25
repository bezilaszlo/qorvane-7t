from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import AwareDatetime

from app.schemas import Metric, SensorId, Stat, StatsResponse

router = APIRouter(prefix="/api/v1", tags=["stats"])


@router.get("/stats")
async def get_stats(
    metric: Annotated[list[Metric], Query(min_length=1)],
    stat: Stat,
    sensor_id: Annotated[list[SensorId] | None, Query()] = None,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
) -> StatsResponse:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
