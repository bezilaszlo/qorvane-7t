# Plan: weather sensor metrics service

Proof of concept: a REST API that ingests weather sensor readings and answers
aggregate queries (min / max / sum / avg) over a time range.

## Guiding principles

- **Minimal, stable, robust.** Scale and workload profile (ingest- vs query-heavy)
  are unknown, so we build the simplest correct thing and measure both paths.
- **Optimizations are documented, not built.** Each one is framed as
  "if we observe X, do Y" in the README's *Limitations & next steps*.
- **Durable before acknowledged.** A write is acknowledged only after the
  Postgres transaction commits.
- **Idempotent ingest.** Clients and sensors retry; duplicates are no-ops.
- Reference: *Designing Data-Intensive Applications* (Kleppmann).

## Stack

| Concern | Choice |
|---|---|
| Runtime / packaging | Python 3.13, `uv` |
| API | FastAPI, Pydantic v2, fully async |
| DB access | SQLAlchemy 2.0 async + asyncpg, Alembic migrations |
| Database | Plain Postgres 17 (pinned image), single unpartitioned table, Docker Compose |
| UI | Single static page: Alpine.js + uPlot, served by FastAPI |
| Tests | pytest + httpx `AsyncClient` against a real Postgres |
| Load test | k6 (Docker) |
| Quality gates | ruff (lint + format), ty, pre-commit |
| Agent docs | `AGENTS.md` only (references the FastAPI skill) |

## Assumptions

These fill gaps in the brief and will be listed in the README.

1. **Sensors and metrics are implicit.** They exist once a reading arrives; there's no
   registration step. Metric names are an open set validated by pattern
   (`^[a-z][a-z0-9_]{0,31}$`); the same goes for sensor ids. One implicit unit per metric.
2. **Timestamps** must carry a timezone (ISO 8601) and are stored in UTC. If omitted
   at ingest, the server time is used. Readings more than 5 minutes in the future are rejected.
3. **Date range** must be between 1 day and 31 days ("one month"), with `start < end`.
   Out-of-range requests get 422 and are never clamped. If no range is given, it's the last 24 hours. If only
   `end` is given, `start = end - 24h`; if only `start`, `end = now`.
4. **One statistic per query**, applied to every requested metric.
5. **Results are per sensor and metric.** An aggregate across sensors is a possible
   extension.
6. **Unknown sensors or metrics** in a query produce no rows (empty result), not 404,
   because sensors are implicit.
7. **No data in range** → `value: null`, `count: 0`. We never divide by zero.
8. **Duplicates**: same `(sensor_id, metric, ts)` is treated as a retry; the first
   write wins (`ON CONFLICT DO NOTHING`). The response reports how many rows were inserted and how many were duplicates.
9. Values must be finite floats (NaN/inf rejected).
10. No authentication (out of scope for the PoC).

## Data model

```sql
CREATE TABLE readings (
    sensor_id  text             NOT NULL,
    metric     text             NOT NULL,
    ts         timestamptz      NOT NULL,
    value      double precision NOT NULL,
    PRIMARY KEY (sensor_id, metric, ts)   -- idempotency + range-query index
);
```

- Narrow, long table: adding a metric needs no migration.
- The primary key doubles as the query index: `WHERE sensor_id IN (...) AND metric IN (...)
  AND ts >= ... AND ts < ...` goes straight to the matching rows.

### Why plain Postgres, no partitioning

- The data is time series, but at an unknown and likely prototype scale a single indexed table
  handles it. Query cost is driven by the number of rows aggregated, which partitioning does
  not reduce. The index already narrows to them.
- Partitioning (native `PARTITION BY RANGE (ts)` or TimescaleDB hypertables) pays off at
  volume: cheap retention by dropping partitions, smaller per-partition indexes under heavy
  ingest, per-partition vacuum. That's a documented next step, not a prototype need.
- Rollups, not partitioning, are what speed up long-range queries.
- Plain Postgres runs anywhere, including AWS RDS and Aurora, which don't offer TimescaleDB.
- The decision is cheap to reverse: the schema is already time-series shaped. Adopting
  TimescaleDB is one `create_hypertable(..., migrate_data => true)` migration, with no app changes.
- The perf test backs this up with numbers (latency vs table size).

## API

Base path `/api/v1`. Errors use FastAPI's standard shape (`422` validation, `400` bad request,
`503` DB unavailable).

### `POST /api/v1/readings`

Accepts a batch (1..1000 readings), so a single reading and a batch use the same endpoint.

```json
{
  "readings": [
    {"sensor_id": "sensor-1", "ts": "2026-11-25T10:00:00Z",
     "metrics": {"temperature": 21.3, "humidity": 40.0}}
  ]
}
```

→ `201 {"inserted": 2, "duplicates": 0}`. The response is sent after commit, in one multi-row
`INSERT ... ON CONFLICT DO NOTHING` per request.

### `GET /api/v1/stats`

Query params: `sensor_id` (repeatable; omitted = all), `metric` (repeatable, required),
`stat` (`min|max|sum|avg`), `start`, `end` (optional ISO 8601).

```
GET /api/v1/stats?sensor_id=sensor-1&metric=temperature&metric=humidity&stat=avg&start=2026-11-18T00:00:00Z
```

```json
{
  "stat": "avg", "start": "...", "end": "...",
  "results": [
    {"sensor_id": "sensor-1", "metric": "temperature", "value": 18.7, "count": 10080}
  ]
}
```

A single `SELECT sensor_id, metric, <agg>(value), count(*) ... GROUP BY sensor_id, metric`.

### Supporting endpoints

- `GET /api/v1/sensors` lists `(sensor_id, metric)` pairs seen in the last 24 h. The UI uses it for
  pickers. The window keeps it bounded; a catalog table is the next step if this gets slow.
- `GET /health` is liveness. `GET /ready` checks the DB with `SELECT 1`.

## FastAPI practices

- `async def` endpoints only; never block the event loop.
- One async engine per worker process, pool sized via settings, created and disposed
  in the lifespan handler.
- Constraint: `workers × (pool_size + max_overflow) < postgres max_connections`.
- Session per request via dependency, and the transaction commits before the response.
- Settings via `pydantic-settings` (env vars), documented in `.env.example`.
- Run with `fastapi run --workers $WORKERS`.

## Repository layout

```
app/            main.py, config.py, db.py, models.py, schemas.py, api/ (readings, stats, sensors, health)
alembic/        migrations
static/         index.html, app.js (Alpine + uPlot)
scripts/        seed.py (bulk COPY of synthetic data)
tests/          integration tests against a Postgres test DB
perf/           k6 scripts: ingest.js, query.js + results write-up
compose.yaml    db, api (+ test db / k6 via profiles)
AGENTS.md, README.md, pyproject.toml, uv.lock, .pre-commit-config.yaml
```

## Milestones

- [ ] **M1 Scaffold:** uv project, ruff, ty, pre-commit, compose with Postgres (pinned image),
      config, async DB wiring, health endpoints, `AGENTS.md`.
- [ ] **M2 Ingest:** schema + migration, `POST /readings` with validation and idempotency, tests.
- [ ] **M3 Query:** `GET /stats` with range rules, all four stats, empty-result handling, tests.
- [ ] **M4 Data:** seed script (N sensors × 30 days, daily sine + noise, several metrics) via `COPY`.
- [ ] **M5 UI:** single page that picks sensors, metrics, stat and range, then shows a table and a uPlot chart.
- [ ] **M6 Perf:** k6 ingest (single vs batch) and query (1 day vs 31 days) scenarios; worker-count
      sweep; results table in `perf/README.md`.
- [ ] **M7 Docs:** README with run instructions, assumptions, architecture, limitations and next steps.

Cut unless time allows: a live simulator (a small loop posting to the API).

## Testing

- Integration tests hit the real API and a real Postgres. Aggregation and constraint behavior
  is where bugs live, and SQLite would hide them.
- Key cases: duplicate ingest is a no-op; empty range returns null; range validation edges
  (exactly 1 day, 31 days, inverted, naive timestamps); all-sensors query; NaN rejection;
  batch size limit.
- Unit tests only for pure logic (range resolution).

## Performance test

Goal: show what a single node handles and where it saturates. We don't optimize ahead.

- Ingest: rows/s and p95 latency for batch sizes 1 and 500.
- Query: p50/p95/p99 for 1-day and 31-day ranges, single sensor and all sensors,
  on the seeded data set.
- Sweep `WORKERS` (1, 2, 4, ...) and record the hardware alongside the results.
- Data-volume sweep: seed growing data sets (e.g. 1M → 10M → 100M rows) and plot query
  latency against table size, to show where the unpartitioned table stops being enough.

## Limitations & next steps (README outline)

Decided by the measured workload profile, not up front.

- **Large volume / retention:** time partitioning, either native range partitions with
  `pg_partman` or TimescaleDB hypertables (self-hosted / Timescale Cloud), plus compression
  of old data.
- **Ingest-heavy:** put a durable log (Kafka / Kinesis) in front of the DB to absorb bursts,
  decouple producers and allow replay; `COPY`-based writers; sharding by `sensor_id`.
- **Query-heavy:** rollups (hourly min/max/sum/count, avg = sum/count) via TimescaleDB
  continuous aggregates or a rollup table, plus read replicas and caching of hot windows.
- **Reliability / HA:** Postgres replication + automatic failover (Patroni / RDS Multi-AZ),
  WAL archiving + point-in-time recovery, stateless API replicas behind a load balancer,
  rate limiting, request size limits.
- **Data correctness:** event time vs processing time (`received_at` column), late and
  out-of-order data, sensor clock drift, units per metric.
- **Lifecycle:** retention policy, raw archive to object storage (Parquet on S3).
- **Operations:** auth, metrics/traces/structured logs, SLOs, runbooks.
- **Target architecture diagram:** sensors → gateway → log → {raw archive, TSDB, stream
  rollups} → query API.
