import uuid
from datetime import UTC, datetime, timedelta


def new_sensor() -> str:
    return f"bb-{uuid.uuid4().hex}"


def new_metric() -> str:
    return f"m_{uuid.uuid4().hex[:12]}"


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def past_anchor(days: int = 3) -> datetime:
    return (datetime.now(UTC) - timedelta(days=days)).replace(second=0, microsecond=0)


def reading(sensor_id: str, ts: datetime | None, metrics: dict[str, float]) -> dict:
    body: dict = {"sensor_id": sensor_id, "metrics": metrics}
    if ts is not None:
        body["ts"] = iso(ts)
    return body


def by_key(results: list[dict]) -> dict[tuple[str, str], dict]:
    return {(row["sensor_id"], row["metric"]): row for row in results}
