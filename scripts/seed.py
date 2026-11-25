"""Seed synthetic sensor readings into Postgres via COPY."""

import argparse
import asyncio
import math
import os
import random
import time
from datetime import UTC, datetime

import asyncpg

PROFILES: dict[str, tuple[float, float, float]] = {
    "temperature": (15.0, 8.0, 0.6),
    "humidity": (60.0, 20.0, 2.0),
    "wind_speed": (6.0, 3.0, 1.2),
    "pressure": (1013.0, 6.0, 0.8),
}
LOWER_BOUNDS = {"humidity": 0.0, "wind_speed": 0.0}
UPPER_BOUNDS = {"humidity": 100.0}
CREATE_STAGE = "CREATE TEMP TABLE IF NOT EXISTS stage (LIKE readings) ON COMMIT DELETE ROWS"
MERGE = "INSERT INTO readings SELECT * FROM stage ON CONFLICT (sensor_id, metric, ts) DO NOTHING"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sensors", type=int, default=10)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--interval-seconds", type=int, default=60)
    p.add_argument("--metrics", default="temperature,humidity,wind_speed")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--end", type=datetime.fromisoformat, default=None, help="ISO 8601, default now")
    p.add_argument("--truncate", action="store_true", help="TRUNCATE readings first")
    return p.parse_args()


def dsn() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/sensors")
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def build_timestamps(end: datetime, days: int, interval: int) -> list[datetime]:
    end_epoch = int(end.timestamp()) // interval * interval
    n = days * 86400 // interval
    return [datetime.fromtimestamp(end_epoch - i * interval, UTC) for i in range(n - 1, -1, -1)]


def metric_values(
    metric: str, stamps: list[datetime], rng: random.Random, sensor_offset: float
) -> list[float]:
    mean, amp, noise = PROFILES.get(metric, (10.0, 5.0, 0.5))
    lo = LOWER_BOUNDS.get(metric, -math.inf)
    hi = UPPER_BOUNDS.get(metric, math.inf)
    phase = rng.uniform(0, 2 * math.pi)
    base = mean + sensor_offset * amp * 0.3
    out = []
    for t in stamps:
        day_frac = (t.hour * 3600 + t.minute * 60 + t.second) / 86400
        v = base + amp * math.sin(2 * math.pi * day_frac + phase) + rng.gauss(0, noise)
        out.append(round(min(max(v, lo), hi), 3))
    return out


async def main() -> None:
    args = parse_args()
    metrics = [m.strip() for m in args.metrics.split(",") if m.strip()]
    end = (args.end or datetime.now(UTC)).astimezone(UTC)
    stamps = build_timestamps(end, args.days, args.interval_seconds)
    rng = random.Random(args.seed)  # noqa: S311
    width = max(3, len(str(args.sensors)))
    conn = await asyncpg.connect(dsn())
    if args.truncate:
        await conn.execute("TRUNCATE readings")
    started = time.perf_counter()
    written = inserted = 0
    for s in range(1, args.sensors + 1):
        sensor_id = f"sensor-{s:0{width}d}"
        offset = rng.uniform(-1, 1)
        records = []
        for metric in metrics:
            values = metric_values(metric, stamps, rng, offset)
            records.extend(
                zip([sensor_id] * len(stamps), [metric] * len(stamps), stamps, values, strict=True)
            )
        async with conn.transaction():
            await conn.execute(CREATE_STAGE)
            await conn.copy_records_to_table(
                "stage", records=records, columns=["sensor_id", "metric", "ts", "value"]
            )
            status = await conn.execute(MERGE)
        written += len(records)
        inserted += int(status.rsplit(" ", 1)[1])
        elapsed = time.perf_counter() - started
        print(f"{sensor_id}: {written:,} rows copied, {inserted:,} new, {elapsed:.1f}s", flush=True)
    await conn.execute("ANALYZE readings")
    await conn.close()
    elapsed = time.perf_counter() - started
    print(
        f"done: {written:,} rows copied ({inserted:,} new, {written - inserted:,} duplicates) "
        f"in {elapsed:.1f}s = {written / elapsed:,.0f} rows/s; "
        f"range {stamps[0].isoformat()} .. {stamps[-1].isoformat()}"
    )


if __name__ == "__main__":
    asyncio.run(main())
