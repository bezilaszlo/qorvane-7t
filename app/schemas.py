from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, model_validator

SENSOR_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
METRIC_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"
MAX_READINGS = 1000
MAX_POINTS = 10_000

SensorId = Annotated[str, StringConstraints(pattern=SENSOR_ID_PATTERN)]
Metric = Annotated[str, StringConstraints(pattern=METRIC_PATTERN)]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
Stat = Literal["min", "max", "sum", "avg"]


class Reading(BaseModel):
    sensor_id: SensorId
    ts: AwareDatetime | None = None
    metrics: Annotated[dict[Metric, FiniteFloat], Field(min_length=1)]


class ReadingsBatch(BaseModel):
    readings: Annotated[list[Reading], Field(min_length=1, max_length=MAX_READINGS)]

    @model_validator(mode="after")
    def _cap_points(self) -> Self:
        if sum(len(r.metrics) for r in self.readings) > MAX_POINTS:
            raise ValueError(f"at most {MAX_POINTS} metric points per request")
        return self


class IngestResult(BaseModel):
    inserted: int
    duplicates: int


class StatRow(BaseModel):
    sensor_id: str
    metric: str
    value: float
    count: int


class StatsResponse(BaseModel):
    stat: Stat
    start: datetime
    end: datetime
    results: list[StatRow]


class SensorMetric(BaseModel):
    sensor_id: str
    metric: str


class SensorsResponse(BaseModel):
    sensors: list[SensorMetric]
