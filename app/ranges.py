from dataclasses import dataclass
from datetime import datetime, timedelta

MIN_RANGE = timedelta(hours=24)
MAX_RANGE = timedelta(days=31)


@dataclass(frozen=True)
class RangeError(Exception):
    message: str
    field: str | None


def resolve_range(
    start: datetime | None, end: datetime | None, now: datetime
) -> tuple[datetime, datetime]:
    """Resolve the half-open window [start, end) from tz-aware inputs; never clamps."""
    # Name the parameter at fault; None when both were given and only the pair is wrong.
    field = "start" if end is None else "end" if start is None else None
    end = end or now
    start = start or end - MIN_RANGE
    if start >= end:
        raise RangeError("start must be before end", field)
    if end - start < MIN_RANGE:
        raise RangeError("range must be at least 24 hours", field)
    if end - start > MAX_RANGE:
        raise RangeError("range must be at most 31 days", field)
    return start, end
