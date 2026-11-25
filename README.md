# Weather sensor metrics service

A REST API that ingests weather sensor readings (temperature, humidity, wind speed, ...) and
answers aggregate queries: **min / max / sum / avg** of chosen metrics, for one, several or all
sensors, over a date range of 1 to 31 days (default: the last 24 hours).

Proof of concept: FastAPI (async) + PostgreSQL 17, run with Docker Compose, with a black-box
contract test suite, a small demo UI, a synthetic data seeder and k6 load tests with measured
single-node results.

![Prototype architecture](docs/diagrams/architecture.svg)

## Quick start

Requirements: Docker with Compose. For the tests and tooling also [uv](https://docs.astral.sh/uv/).

```bash
docker compose up --build -d          # db → one-shot migrate → api on http://localhost:8000
make seed                             # optional: 10 sensors × 30 days × 3 metrics (~1.3M rows)
open http://localhost:8000            # demo UI;  API docs at http://localhost:8000/docs
docker compose down                   # add -v to drop the data volume
```

The host port is `API_PORT` (default 8000); other settings are documented in `.env.example`.

### Try the API

```bash
# Ingest: a batch of readings, each with several metrics (ts optional, defaults to server time)
curl -s -X POST localhost:8000/api/v1/readings -H 'content-type: application/json' -d '{
  "readings": [
    {"sensor_id": "sensor-1", "ts": "2026-11-25T10:00:00Z", "metrics": {"temperature": 21.3, "humidity": 40}},
    {"sensor_id": "sensor-1", "ts": "2026-11-25T11:00:00Z", "metrics": {"temperature": 22.1, "humidity": 38}}
  ]}'
# → 201 {"inserted": 4, "duplicates": 0}     (re-sending it → {"inserted": 0, "duplicates": 4})

# Query: average temperature and humidity for sensor-1 over the last week
curl -s "localhost:8000/api/v1/stats?sensor_id=sensor-1&metric=temperature&metric=humidity&stat=avg&start=$(date -u -d '7 days ago' +%FT%TZ)"
# → {"stat": "avg", "start": "...", "end": "...",
#    "results": [{"sensor_id": "sensor-1", "metric": "humidity", "value": 39.0, "count": 2}, ...]}
```

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/readings` | Ingest 1–1000 readings (max 10,000 metric points) per request |
| `GET /api/v1/stats` | `metric` (repeatable, required), `stat` (`min\|max\|sum\|avg`), `sensor_id` (repeatable; omit = all sensors), `start`/`end` (ISO 8601 with timezone, optional) |
| `GET /api/v1/sensors` | `(sensor_id, metric)` pairs seen in the last 24 h (feeds the UI pickers) |
| `GET /health`, `GET /ready` | Liveness; readiness (checks the DB, 503 when it is down) |

## Assumptions

The brief leaves some gaps; these are the decisions made (full list in [docs/plan.md](docs/plan.md)):

- **Sensors and metrics are implicit**: they exist once a reading arrives. Names are validated
  (`sensor_id`: `^[a-z0-9][a-z0-9_-]{0,63}$`, metric: `^[a-z][a-z0-9_]{0,31}$`), one implicit unit per metric.
- **Timestamps** must carry a timezone and are stored in UTC. Omitted at ingest → server time.
  More than 5 minutes in the future, or before 1970, → 422.
- **Date range** is half-open `[start, end)`, between 24 hours and 31 days inclusive ("one month").
  Out of bounds → 422, never silently clamped. No range → last 24 h; only `end` → the 24 h before it;
  only `start` → until now.
- **One statistic per query**, applied to every requested metric. **Results are per sensor and metric.**
- **No data, an unknown sensor or an unknown metric** → `200` with `results: []` (no null rows).
- **Retries are safe**: a reading is identified by `(sensor_id, metric, ts)`; a duplicate is a
  no-op (first write wins) and is reported in `duplicates`.
- No authentication (out of scope for the proof of concept).

## Design

- **One table**, `readings(sensor_id, metric, ts, value)` with `PRIMARY KEY (sensor_id, metric, ts)`.
  The key gives idempotent ingest *and* is the index every query uses. A narrow table means a new
  metric needs no migration.
- **Durable before acknowledged.** Ingest is one `INSERT ... SELECT FROM unnest(...) ON CONFLICT
  DO NOTHING` per request, and the 201 is sent only after the transaction commits. (FastAPI's
  default `yield`-dependency scope commits *after* the response is sent; the connection
  dependency uses `scope="function"`, and a unit test guards this.) `unnest` with four array
  parameters keeps a 10,000-point batch to one statement under asyncpg's 32,767 bind-argument limit;
  points are sorted by key first so concurrent overlapping batches cannot deadlock.
- **Aggregation happens in SQL**: one `GROUP BY sensor_id, metric` with the aggregate chosen from a
  fixed mapping.
- **Plain Postgres, unpartitioned, on purpose.** The workload (ingest- vs query-heavy) and scale are
  unknown, so the simplest robust option was built and both paths were measured. TimescaleDB,
  partitioning and rollups are documented next steps, each tied to what the measurements show.
- **Async throughout** (FastAPI, SQLAlchemy 2 Core, asyncpg); `fastapi run --workers N`, one
  connection pool per worker (`workers × (pool_size + max_overflow) < max_connections`).
  Migrations run once in a separate `migrate` service, never inside the N workers.
- **Errors**: 422 for validation (also for range rules, out-of-range timestamps and numeric
  overflow), 503 when the database is unreachable or the pool is exhausted, 500 with a generic
  body (and a logged trace) for anything else.

Diagrams: [prototype architecture](docs/diagrams/architecture.svg) and the
[production target data flow](docs/diagrams/dataflow.svg) (interactive versions: the `.html`
files next to them).

## Testing

- **Black-box contract suite** (`tests/blackbox/`, 89 tests): pure HTTP against a running stack,
  never imports app code or touches the database, so it tests the contract and could run against
  any deployment. Each test uses unique sensor ids and metric names, so it runs on a shared, dirty
  database without cleanup.
- **Unit tests** (`tests/unit/`, 31 tests): range resolution, error classification and the
  commit-before-ack regression.
- Built red/green: the suite was written against the 501 stubs first and failed, then the
  implementation made it pass without editing it.

```bash
uv sync
make test                                        # unit tests (also run by pre-commit)
uv run pre-commit run --all-files                # ruff (lint + format), ty, unit tests

# Contract suite against a separate, throwaway stack, so test sensors never appear in the demo data
API_PORT=8010 docker compose -p bbtest up --build -d
API_BASE_URL=http://localhost:8010 make test-blackbox
docker compose -p bbtest down -v
```

## Performance (single node)

Measured on one laptop (i7-7700HQ, 4 cores / 8 threads) with k6, the API and Postgres on the same
host and stock Postgres settings. Method and full tables: [perf/README.md](perf/README.md).

| Scenario | Result |
|---|---|
| Ingest, 1 reading per request | ~4.5k rows/s (1.5k req/s) at 8 workers; API-bound, scales with workers |
| Ingest, 500 readings per request | ~120k rows/s, saturated from 2 workers; Postgres-bound (index + WAL) |
| Query, 1 sensor, 1 day / 30 days | p95 ~5 ms / ~55 ms, flat from 1.3M to 13M rows |
| Query, all sensors, 30 days | p95 ~0.9 s at 1.3M rows (10 sensors), ~12 s at 13M rows (100 sensors) |

The takeaway: **latency follows the number of rows aggregated, not the table size**, and client-side
batching is the biggest ingest lever. The 100M-row point was skipped (seeding would take ~20 min).
The perf runs used the code before the final review fixes (key sorting before insert, commit
scope); those changes do not alter the query path and add negligible ingest work.

## Limitations and next steps

What to do next depends on the observed workload, which the brief doesn't specify:

- **Query-heavy** (the clearest finding above): hourly min/max/sum/count rollups (rollup table or
  TimescaleDB continuous aggregates; avg = sum / count) so a 30-day query reads ~720 rows per
  sensor and metric instead of ~43k. Then read replicas and caching of hot windows.
- **Ingest-heavy**: batch on the client; then a durable log (Kafka / Kinesis) in front of the
  database to absorb bursts, decouple producers and allow replay, with `COPY`-based writers;
  shard by `sensor_id`. Split ingest and query into separately scaled deployments if they contend.
- **Large volume / retention**: time partitioning (native partitions with `pg_partman`, or
  TimescaleDB) for cheap retention and smaller indexes, plus compression. It would not speed up
  the queries measured here.
- **Reliability / HA**: the prototype is a single Postgres node. Next: streaming replication with
  automatic failover (Patroni, RDS Multi-AZ), WAL archiving and point-in-time recovery, stateless
  API replicas behind a load balancer, rate and request-size limits.
- **Data correctness**: store `received_at` next to the sensor's event time, and handle late and
  out-of-order data and clock drift explicitly; units per metric.
- **Operations**: authentication, metrics/traces/structured logs, SLOs, runbooks.

The [production target data flow](docs/diagrams/dataflow.svg) sketches where this leads:
sensors → ingest API → durable log → {raw archive, time-series store, rollups} → query API.

**Not done / known gaps**: no auth; `/sensors` lists only the last 24 h and is unpaginated; the
demo UI's error states and test-reading form were checked by code review, not by automated UI
tests; one perf run per configuration on a shared laptop (±10–20% noise).

## Project layout

```
app/            FastAPI app: api/ (readings, stats, sensors, health), db, schemas, ranges, errors
alembic/        migrations (run by the one-shot `migrate` service)
static/         demo UI (Alpine.js, no build step)
scripts/        seed.py: synthetic data via COPY (`make seed`)
tests/          blackbox/ (HTTP contract), unit/ (pure logic)
perf/           k6 scripts and results
docs/           plan.md (design decisions and milestones), diagrams/
```

## How it was built

Planned first ([docs/plan.md](docs/plan.md)), then built in milestones: skeleton with 501 stubs →
failing black-box suite → implementation → independent code review → fixes. AI coding agents did
much of the typing under that plan, with every milestone reviewed before commit; the design
decisions and trade-offs are mine and are recorded in the plan.
