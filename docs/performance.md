# Performance

k6 load tests (scripts in `perf/`) against the Compose stack. The unit under test is **one API pod**:
the `api` container is limited to 2 CPU / 2 GB (`cpus: 2`, `mem_limit: 2g` in `compose.yaml`) with
`WORKERS=2` (one process per CPU) and SQLAlchemy's default pool (5 + 10 overflow per worker).
Postgres is **not** limited and stock; it stands in for a separately sized managed database.
Everything runs on one laptop, so the numbers show curve shapes, the bottleneck and the per-pod
capacity on this hardware, not benchmark-lab figures.

Measured code: current master (points sorted before insert, commit before ack, 5 s statement
timeout, default pool sizing). Queries above 5 s are cancelled by Postgres and returned as
`503 "query timed out"`; these appear below as errors.

## Method

Each script is a **concurrency sweep**: a 10 s warm-up (5 VUs, excluded from results) and then one
closed-loop scenario per level, VUs = c, `c = 1, 2, 5, 25` (ingest runs also include 10), a fixed duration
each (15 s; the ingest runs used 20 s). Per level the `RESULT` line reports requests/s, p50/p95/p99,
non-2xx count and 503 count. Closed loop: a VU sends the next request when the previous returns, so
latency at high c includes queueing. Note that `rps` counts all responses, errors included; the
tables give successful requests/s where errors occurred.

The headline signal is the **throughput scaling factor** = peak rps / rps at c=1.

- **Ingest** (`ingest.js`, `BATCH=1|500`): 1 or 500 readings x 3 metrics per request (3 or 1,500
  points), each VU on its own sensor with unique timestamps, rows/s counted for `201` only. Perf rows
  are deleted and the table vacuumed after each run. Run at 1.3M rows present.
- **Query** (`query.js`, `CASE=day_single|day_all|d30_single|d30_all`): `GET /stats`, `stat=avg`, three
  metrics, range ending now. Swept: `day_single` (1 day, one random sensor: API-overhead-bound) and
  `d30_all` (30 days, all sensors: Postgres-bound). Run at 1.3M rows (10 sensors x 30 days x 3
  metrics) and, for `d30_all` only, 13M (100 sensors). `day_single` at 13M was not re-run: the
  earlier measurements (below) showed single-sensor queries unchanged between 1.3M and 13M, since the
  primary key narrows to the same rows.
- Thresholds in the scripts are always-pass; they exist only so k6 reports per-level sub-metrics.
- One run per cell, 15-20 s per level: expect +-10-20% noise.

Reproduce (separate project and port, so other stacks are untouched):

```bash
API_PORT=8095 docker compose -p perf2 up --build -d
T="docker compose -p perf2 -f compose.yaml -f compose.tools.yaml"
API_PORT=8095 $T run --rm seed --sensors 10 --days 30 --truncate     # ~1.3M rows
API_PORT=8095 BATCH=500 $T run --rm k6 run /perf/ingest.js           # or: make perf-ingest
API_PORT=8095 CASE=d30_all $T run --rm k6 run /perf/query.js         # or: make perf-query
API_PORT=8095 $T run --rm seed --sensors 100 --days 30 --truncate   # ~13M rows (SENSORS=100 for k6)
API_PORT=8095 $T down -v
```

`make seed|perf-ingest|perf-query` do the same on the default project. Knobs (env): `LEVELS`
(`1,2,5,25`), `DURATION` (`15s`), `WARMUP` (`10s`), `CASE`, `BATCH`, `SENSORS` (seeded sensors to pick
from). CPU was sampled with `docker stats` roughly every 2 s (100% = one core).

## Hardware

Intel Core i7-7700HQ @ 2.8 GHz (4 cores / 8 threads), 31 GiB RAM, Linux 7.2, Docker. k6, the API
(capped at 2 CPUs by Docker, i.e. a CFS quota, not pinned cores) and Postgres (unlimited, stock
`postgres:17.12`: `shared_buffers=128MB`, `work_mem=4MB`, `max_connections=100`) all share this host,
with unrelated containers present but idle. 1.3M rows = ~750 MB on disk, 13M rows = ~1.6 GB (page-cache
resident, not in `shared_buffers`). Seeding runs at ~70-80k rows/s (1.3M in 16 s, 13M in 158-192 s).

## Results (one API pod: 2 CPU / 2 GB, 2 workers; 1.3M rows unless noted)

### Query, 1 sensor, 1 day (API-bound)

| c | req/s | p50 | p95 | p99 | errors |
|---:|---:|---:|---:|---:|---:|
| 1 | 242 | 3.7 ms | 5.5 ms | 6.2 ms | 0 |
| 2 | 463 | 4.0 ms | 5.4 ms | 6.3 ms | 0 |
| 5 | 716 | 6.7 ms | 9.2 ms | 12.5 ms | 0 |
| 25 | 744 | 31 ms | 50 ms | 79 ms | 0 |

Scaling factor 3.1x. The API hit its 200% cap (peak 196%); Postgres ~180%.

### Ingest, batch 1 (3 points per request, API-bound)

| c | req/s | rows/s | p50 | p95 | p99 | errors |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 207 | 620 | 4.3 ms | 6.4 ms | 10.6 ms | 0 |
| 2 | 411 | 1,232 | 4.4 ms | 5.5 ms | 11.1 ms | 0 |
| 5 | 659 | 1,978 | 6.9 ms | 10.5 ms | 22.2 ms | 0 |
| 10 | 763 | 2,290 | 12.3 ms | 16.0 ms | 40.8 ms | 0 |
| 25 | 723 | 2,169 | 30.8 ms | 61.7 ms | 98.0 ms | 0 |

Scaling factor 3.7x. API peak 197%, Postgres 129%.

### Ingest, batch 500 (1,500 points per request, Postgres-bound)

| c | req/s | rows/s | p50 | p95 | p99 | errors |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 20.4 | 30,525 | 38 ms | 58 ms | 69 ms | 0 |
| 2 | 31.1 | 46,725 | 53 ms | 72 ms | 84 ms | 0 |
| 5 | 49.5 | 74,250 | 85 ms | 121 ms | 148 ms | 0 |
| 10 | 61.4 | 92,025 | 139 ms | 218 ms | 267 ms | 0 |
| 25 | 66.8 | 100,125 | 335 ms | 587 ms | 740 ms | 0 |

Scaling factor 3.3x. API peak 190%, Postgres 407%.

### Query, all sensors, 30 days (Postgres-bound)

| Rows | c | req/s (all) | ok/s | p50 | p95 | p99 | 503 (of requests) |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1.3M | 1 | 1.6 | 1.6 | 645 ms | 683 ms | 689 ms | 0 |
| 1.3M | 2 | 2.3 | 2.3 | 893 ms | 1,016 ms | 1,034 ms | 0 |
| 1.3M | 5 | 2.7 | 2.7 | 1.77 s | 3.10 s | 4.36 s | 0 |
| 1.3M | 25 | 6.6 | 3.3 | 4.99 s | 5.15 s | 5.18 s | 49 of 99 |
| 13M | 1 | 0.5 | 0.5 | 1.86 s | 2.26 s | 2.28 s | 0 |
| 13M | 2 | 0.7 | 0.7 | 3.20 s | 3.33 s | 3.37 s | 0 |
| 13M | 5 | 1.0 | 0 | 5.02 s | 5.02 s | 5.03 s | 15 of 15 |
| 13M | 25 | 5.0 | 0 | 5.03 s | 5.15 s | 5.21 s | 75 of 75 |

Scaling factor (ok/s) 2.1x at 1.3M, 1.4x at 13M. Postgres peaked at 750-780% CPU
(parallel workers), the API at ~41%: the pod is idle, the database is the limit. The 503s are the
5 s statement timeout shedding load; at 13M two or more concurrent clients already exceed it.
The 13M p95/p99 rest on 7-75 requests per level.

All other scenarios had zero non-2xx responses.

### Comparison with the earlier, unlimited-API runs

Earlier: no container limits (4 cores / 8 threads shared by API, Postgres and k6), `WORKERS=2`, pool
5 + 5, fixed VUs, code before sorting / commit-before-ack / timeouts. Rough equivalents:

| Scenario | Earlier (unlimited, 2 workers) | Now (2 CPU pod) |
|---|---|---|
| ingest batch 1, 16 VUs / c=10-25 | 766 req/s, p95 27 ms | 723-763 req/s, p95 16-62 ms |
| ingest batch 500, 16 VUs / c=25 | 115k rows/s, p95 252 ms | 100k rows/s, p95 587 ms (c=10: 92k, 218 ms) |
| query 1 day, 1 sensor, 8 VUs / c=5-25 | 716 req/s, p95 14 ms | 716-744 req/s, p95 9-50 ms |
| query 30 days, all, 8 VUs / c=5 | ~2.5 req/s, p95 4.9 s | 2.7 req/s, p95 3.1 s |
| query 30 days, all, 13M, 2 VUs / c=2 | p50 12.0 s | p50 3.2 s |

The 2-CPU cap costs little: with 2 workers the old runs were already using about two cores of API.
The old 13M 30-day figure (12 s) did not reproduce; the same query measured 1.9-3.2 s here
(a throwaway fixed-VU run on this machine gave 2.9 s too), so the old number was most likely inflated
by host contention and should not be relied on. The old worker sweep (WORKERS = 1, 2, 4, 8) is
superseded: the pod has 2 CPUs and 2 workers.

## Interpretation

- **No serialization.** Every API-bound path scales 3-3.7x from c=1 to peak, i.e. well above 2x:
  at c=1 one request is in flight, so each worker mostly waits on Postgres or the network and the pod
  uses a fraction of its CPUs. A flat factor (~1x) would mean requests are serialized, for example by a
  blocking call on the event loop.
- **Small writes and cheap reads are API-bound at 2 CPU.** Batch-1 ingest and 1-day/1-sensor queries
  saturate the pod at c ~ 5-10 (~720-760 req/s) with the API at its 200% cap; at c=25 throughput is
  flat and only latency grows (p95 50-62 ms), with no errors. The pod's ceiling for these paths is
  CPU in the API (JSON, Pydantic, driver), not the pool or Postgres (129-180%).
- **Large batches are database-bound.** Batch 500 reaches ~100k rows/s (the API at ~190% is
  also busy serialising 1,500 points per request, but Postgres at ~400% is the larger consumer);
  rows/s was still rising at c=25 (p95 587 ms). Batching is the main ingest lever: ~50x the rows/s
  of batch 1.
- **Wide queries are Postgres CPU, and a pod cannot help.** All-sensor 30-day queries read every row in
  range: they take Postgres to ~750% while the API sits at ~41%. Latency grows linearly with sensors
  (645 ms at 10 sensors, ~1.9 s at 100 at c=1) and with queueing, and under concurrency they hit the 5 s
  statement timeout and are shed with 503. This is the intended behavior of the guardrail
  (the pool wait and statement timeout bound the damage); more API replicas would add load, not
  capacity.
- Caveats: one run per cell, 15-20 s each, closed-loop clients, everything on one host with k6 and
  Postgres competing with the API for cores (Postgres can use all 8 threads), warm cache, stock
  Postgres, CFS-quota CPU limit. Differences of ~10-20% are within noise.

## How to read a future run

- **Scaling factor falls toward 1x** (peak rps / rps at c=1): requests are being serialized, e.g. a
  blocking call on the event loop or a single shared lock.
- **p95 at c=1 rises** (here ~5 ms for 1-day queries, ~6 ms for batch-1 ingest): per-request cost
  regressed (query plan, validation, serialization).
- **p95 at c=25 rises while throughput stays flat**: the pod is saturated, which is expected.
- **Errors at high c** (503s): load shedding by the pool wait or the statement timeout, expected beyond
  pod or database capacity; the remedy is more replicas for API-bound paths, rollups or a bigger
  database for the wide query. Non-503 errors are always a bug.

## What the numbers point to

- **Capacity per pod (2 CPU / 2 GB, this hardware, Postgres unlimited):** at p95 under 1 s, one pod
  sustains about 740 req/s of 1-day/1-sensor queries (p95 50 ms at c=25), about 760 req/s of
  batch-1 ingest (~2.3k rows/s, p95 16 ms at c=10), about 67 req/s of batch-500 ingest (~100k rows/s,
  p95 587 ms at c=25), and only about 2 req/s of 30-day all-sensor queries at 10 sensors
  (p95 1.0 s at c=2); at 100 sensors that query misses 1 s at any concurrency (2.3 s at c=1). Size
  API replicas from the first three; do not size for the last, fix it.
- **Query-heavy / rollups:** hourly (or daily) min/max/sum/count rollups, via a rollup table or
  TimescaleDB continuous aggregates, bring 30-day all-sensor queries from seconds to milliseconds and
  remove the timeouts. This is the clearest finding.
- **Ingest-heavy:** clients should batch. Beyond ~100k rows/s on one Postgres the next steps are a
  durable log in front of the DB with `COPY`-based writers, then sharding by `sensor_id`;
  group-commit style buffering would help batch-1 traffic from many small devices.
- **Large volume / retention:** partitioning and compression are about retention and index size, not
  these latencies; single-sensor queries were flat from 1.3M to 13M (4 ms and ~36-41 ms p50 at 1 day and
  30 days in earlier runs). The 100M point was not measured.
- **Capacity sizing:** `workers x (pool_size + max_overflow)` is 2 x 15 = 30 connections per pod
  against Postgres `max_connections=100`: about three pods fit before the limit needs raising or a
  pooler is added. The pool was not the limit in these runs.
