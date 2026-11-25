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
| DB access | SQLAlchemy 2.0 Core (async) + asyncpg, Alembic migrations |
| Database | Plain Postgres 17 (pinned image), single unpartitioned table, Docker Compose |
| UI | Single static page: Alpine.js (pinned CDN version), served by FastAPI |
| Tests | pytest + sync `httpx.Client`: black-box over HTTP against the running stack, plus unit tests |
| Load test | k6 (Docker) |
| Quality gates | ruff (lint + format), ty, pre-commit |
| Agent docs | `AGENTS.md` only (references the FastAPI skill) |

## Assumptions

These fill gaps in the brief and will be listed in the README.

1. **Sensors and metrics are implicit.** They exist once a reading arrives; there's no
   registration step. Metric names are an open set validated by `^[a-z][a-z0-9_]{0,31}$`;
   sensor ids allow hyphens and longer values (`^[a-z0-9][a-z0-9_-]{0,63}$`). One implicit unit per metric.
2. **Timestamps** must carry a timezone (ISO 8601) and are stored in UTC. If omitted
   at ingest, the server time is used. Readings more than 5 minutes in the future are rejected.
3. **Date range** is half-open `[start, end)` and must be between 1 day (24h) and 31 days ("one month"), with `start < end`.
   Out-of-range requests get 422 and are never clamped. If no range is given, it's the last 24 hours. If only
   `end` is given, `start = end - 24h`; if only `start`, `end = now`.
4. **One statistic per query**, applied to every requested metric.
5. **Results are per sensor and metric.** An aggregate across sensors is a possible
   extension.
6. **Unknown sensors, unknown metrics, or no data in range** produce no rows (`results: []`),
   not 404 or null placeholders, matching `GROUP BY` (every returned row has `count >= 1`, so
   we never divide by zero).
7. **Duplicates**: same `(sensor_id, metric, ts)` is treated as a retry (including duplicates
   within the same batch); the first write wins (`ON CONFLICT DO NOTHING`). The response reports
   how many `(sensor_id, metric, ts)` points were inserted and how many were duplicates.
8. Values must be finite floats (NaN/inf rejected).
9. No authentication (out of scope for the PoC).

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

Accepts a batch (1..1000 readings, each with at least 1 metric, capped at 10,000 total metric
points per request to bound request size and transaction time), so a single reading and a
batch use the same endpoint.

```json
{
  "readings": [
    {"sensor_id": "sensor-1", "ts": "2026-11-25T10:00:00Z",
     "metrics": {"temperature": 21.3, "humidity": 40.0}}
  ]
}
```

→ `201 {"inserted": 2, "duplicates": 0}` (counts are per `(sensor_id, metric, ts)` point). The
response is sent after commit, in one `INSERT ... SELECT FROM unnest(...) ON CONFLICT DO NOTHING`
per request. Four array parameters instead of a multi-row `VALUES`: asyncpg caps a statement at
32,767 bind arguments, which 10,000 points × 4 columns would exceed.

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
- Connection per request via dependency (`engine.begin()`), and the transaction commits before the response.
- Settings via `pydantic-settings` (env vars), documented in `.env.example`.
- Run with `fastapi run --workers $WORKERS`; Alembic migrations run as a one-shot `migrate`
  service before `api` starts (never inside worker lifespan).

## Repository layout

```
app/            main.py, config.py, db.py, models.py, schemas.py, api/ (readings, stats, sensors, health)
alembic/        migrations
static/         index.html, app.js (Alpine.js)
scripts/        seed.py (bulk COPY of synthetic data)
tests/          blackbox/ (HTTP-only contract tests), unit/ (pure logic)
perf/           k6 scripts: ingest.js, query.js + results write-up
compose.yaml    db, migrate (one-shot), api (+ k6 via profile)
AGENTS.md, README.md, pyproject.toml, uv.lock, .pre-commit-config.yaml
```

## Milestones

Red/green order: the stack runs first, then the black-box tests are written against the API
contract and fail, then the implementation makes them pass. One commit per milestone.

- [x] **M1 Skeleton:** `docker compose up` starts the whole stack (Postgres + migrations + API
      serving the static UI). uv project, ruff, ty, pre-commit, config, async DB wiring, Alembic
      migration for `readings`, working `/health` and `/ready`. Core endpoints exist with their
      request/response schemas but return `501 Not Implemented`. `AGENTS.md`. No core logic.
- [x] **M2 Black-box test harness (red):** pytest suite that talks to the running API over HTTP
      only (see Testing). It covers the ingest and query contract and the assumptions above. It
      runs against the compose stack, and every core test fails against the 501 stubs.
- [x] **M3 Implement (green):** ingest (validation, idempotent batch insert, ack after commit)
      and query (range resolution, SQL aggregates, empty results) until the suite passes.
      Range resolution also gets plain unit tests.
- [ ] **M4 Data:** seed script (N sensors × 30 days, daily sine + noise, several metrics) via `COPY`.
- [ ] **M5 UI:** single page that picks sensors, metrics, stat and range, then shows a results table and simple per-metric bar comparison.
- [ ] **M6 Perf:** k6 ingest (single vs batch) and query (1 day vs 31 days) scenarios; worker-count
      and data-volume sweeps; results table in `perf/README.md`.
- [ ] **M7 Docs:** README with run instructions, assumptions, architecture, limitations and next steps.

Cut unless time allows: a live simulator (a small loop posting to the API).

### Way of working

- Milestones are delegated to subagents with a written brief. The orchestrator reviews each
  diff before it is committed, and an independent reviewer checks the riskier ones (M3).
- The test suite is the contract: M3 may not change M2 tests to make them pass. A test
  change needs a stated reason (a test bug or a deliberate contract change recorded here).
- Pre-commit (ruff, ty, unit tests) is the fast verification loop for humans and agents alike.

## Testing

- **Black-box first.** The main suite (`tests/blackbox/`) only uses HTTP against a running
  stack (`API_BASE_URL`, default the compose stack). It never imports app code or touches the
  DB, so it tests the contract, not the implementation, and could run against any deployment.
- **Isolation without DB access.** Each test uses unique sensor ids (uuid suffix) and explicit
  past timestamps, so tests don't interfere and need no truncation. "All sensors" queries
  assert on the test's own sensors being present with the right values.
- Real Postgres behind the API: aggregation and constraint behavior is where bugs live, and
  SQLite would hide them.
- Key cases: duplicate ingest is a no-op (`duplicates` count, including intra-batch duplicates);
  empty range returns empty `results`; range validation edges (exactly 1 day, 31 days, too short,
  too long, inverted, half-open `[start, end)` bounds, naive timestamps, defaults); all four stats
  on known values; multiple sensors and metrics; all-sensors query; NaN/inf, empty `metrics`, and
  bad name rejection; batch reading/point limits; future timestamps.
- Unit tests (`tests/unit/`) only for pure logic such as range resolution. These run in
  pre-commit; the black-box suite needs the stack up.

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
