# Performance

k6 load tests for the API (scripts in `perf/`), run against the Compose stack, plus single-node results.
The numbers come from one laptop, with k6, the API and Postgres on the same host, so they show the
shape of the curves and the bottleneck, not benchmark-lab figures.

## How to run

```bash
make up                                          # db + migrate + api
make seed SEED_ARGS="--sensors 10 --days 30"     # ~1.3M rows (3 metrics, 60 s interval)
make perf-query                                  # GET /stats scenarios
make perf-ingest                                 # POST /readings scenarios
```

Seed and k6 are defined in `compose.tools.yaml`, layered on `compose.yaml` by the Makefile targets, so
they run inside the Compose network (k6: `grafana/k6:1.5.0`, mounts `perf/`, targets `http://api:8000`).
API processes: `WORKERS` in `compose.yaml`. Knobs (env): `DURATION` (per scenario, default 30s), `VUS`,
`SENSORS` (query.js: how many seeded sensors to pick from, default 10). Add `--truncate` to the seed
to start from an empty table; without it, re-seeding the same `--end` only reports duplicates.
Each script prints one `RESULT ...` line per scenario (thresholds are always-pass and only
exist so that k6 reports per-scenario sub-metrics; runs never fail on latency).

Reproduction used for the tables below (separate project and port so other stacks are untouched):
`API_PORT=8030 DURATION=20s VUS=<8|16> docker compose -p perf-lane ...`, with `WORKERS` set to `<n>`
(at the time an environment override; now edit it in `compose.yaml`).

## Method

The runs used the code before two later changes: points sorted by key before insert, and the
commit moved before the response. Neither touches the query path; both add negligible ingest work.
Postgres timeouts added later (statement timeout 5 s by default) would cancel the slowest
all-sensor queries measured at 13M rows (12 s) with a 503; see [design.md](design.md).


- **Ingest** (`ingest.js`): two scenarios run one after another, 16 VUs each, 20 s: `batch1` (1 reading
  x 3 metrics = 3 points per request) and `batch500` (500 readings x 3 metrics = 1,500 points per
  request). Each VU writes its own sensor id with unique timestamps, so no insert is a duplicate.
  rows/s = requests/s x points per request, counted only for `201` responses. Perf rows are deleted
  (and the table vacuumed) after every ingest run.
- **Query** (`query.js`): `GET /stats` with `stat=avg`, three metrics, range ending now, four
  scenarios run one after another: 1 day or 30 days (the API caps at 31 days and the seed
  covers 30), single random sensor or all sensors. Closed-loop: each VU sends the next request when
  the previous returns, so latency under 8 VUs includes queueing.
- **Worker sweep**: fixed data set (10 sensors x 30 days x 3 metrics = 1,296,000 rows), `WORKERS` =
  1, 2, 4, 8 (= logical CPUs). Query at 8 VUs, ingest at 16 VUs, 20 s per scenario.
- **Volume sweep**: `WORKERS=2`, 2 VUs (so latency is mostly service time), 1.3M and 13M rows
  (100 sensors x 30 days x 3 metrics). 13M uses 40 s per scenario.
- Postgres is stock (`postgres:17.12`: `shared_buffers=128MB`, `work_mem=4MB`,
  `max_parallel_workers_per_gather=2`, `max_connections=100`); no tuning. Pool per worker is
  the compose default (5 + 5 overflow).

## Hardware

Intel Core i7-7700HQ @ 2.8 GHz (4 cores / 8 threads), 31 GiB RAM, Linux 7.2, Docker. k6, the API
and Postgres all run on this one host, and a handful of unrelated containers were running at
the same time (some memory pressure, no deliberate load). Table size: 1.3M rows = 746 MB
(84 MB heap, the rest is the primary-key index and metadata); 13M rows = 1.6 GB, which fits in the
page cache but not in `shared_buffers`.

## Results

### Seed

~83-86k rows/s via `COPY` into a temp table + `INSERT ... ON CONFLICT DO NOTHING`
(1.3M rows in 15 s, 13M rows in 156 s). 100M rows would take ~20 min, above the 15 min budget I
set, so the 100M point was **skipped** (the plan lists it as optional).

### Ingest, worker sweep (1.3M rows present, 16 VUs, 20 s per scenario)

| WORKERS | batch1 rows/s | batch1 req/s | batch1 p95 | batch500 rows/s | batch500 req/s | batch500 p95 |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1,441 | 480 | 71 ms | 82,350 | 55 | 670 ms |
| 2 | 2,298 | 766 | 27 ms | 115,350 | 77 | 252 ms |
| 4 | 3,981 | 1,327 | 16 ms | 119,325 | 80 | 261 ms |
| 8 | 4,529 | 1,510 | 19 ms | 120,675 | 81 | 259 ms |

No request failed in any run.

### Query, worker sweep (1.3M rows, 8 VUs, 20 s per scenario; latency in ms)

| WORKERS | 1 day, 1 sensor p50/p95/p99 | 1 day, all p50/p95/p99 | 30 days, 1 sensor p50/p95/p99 | 30 days, all p50/p95/p99 |
|---:|---|---|---|---|
| 1 | 17.5 / 22.3 / 26.0 | 182 / 442 / 536 | 69.7 / 107 / 232 | 1,980 / 4,374 / 5,972 |
| 2 | 10.6 / 14.4 / 18.3 | 187 / 460 / 557 | 69.1 / 108 / 166 | 2,469 / 4,887 / 6,002 |
| 4 | 7.8 / 11.3 / 14.3 | 234 / 558 / 684 | 72.6 / 130 / 174 | 3,029 / 6,306 / 6,651 |
| 8 | 6.9 / 11.6 / 15.6 | 183 / 452 / 575 | 68.0 / 117 / 175 | 2,530 / 4,568 / 6,336 |

Throughput at 8 VUs (req/s): 1 day/1 sensor 447 / 716 / 954 / 1,034 for 1 / 2 / 4 / 8 workers;
the other three scenarios stay at ~29-37, ~99-107 and ~2.4-4.1 req/s regardless of worker count.

### Query, data-volume sweep (`WORKERS=2`, 2 VUs; latency in ms)

| Rows | 1 day, 1 sensor p50/p95/p99 | 1 day, all p50/p95/p99 | 30 days, 1 sensor p50/p95/p99 | 30 days, all p50/p95/p99 |
|---:|---|---|---|---|
| 1.3M (10 sensors) | 4.0 / 5.4 / 6.0 | 59.8 / 77.1 / 90.4 | 35.2 / 50.9 / 63.8 | 842 / 932 / 1,017 |
| 13M (100 sensors) | 4.1 / 5.4 / 6.0 | 495 / 595 / 607 | 36.3 / 59.7 / 76.2 | 11,990 / 12,465 / 12,518 |
| 100M | skipped (seed ~20 min) | | | |

The 13M `30 days, all` row has only 10 requests, so its p95/p99 are effectively the max.

### CPU during runs (`docker stats`, sampled every ~2 s; 100% = one core)

| Run | API peak | Postgres peak |
|---|---:|---:|
| ingest, 1 worker | 130% | 200% |
| ingest, 2 workers | 231% | 372% |
| ingest, 4 workers | 392% | 398% |
| ingest, 8 workers | 493% | 393% |
| query, any worker count | 124-366% (the 1-day single-sensor scenario) | ~750% (the all-sensors scenarios) |

## Interpretation

- **Small writes are API-bound; large batches are database-bound.** `batch1` scales with workers
  (1.4k to 4.5k rows/s, 480 to 1,510 req/s) and flattens once the 4 physical cores are shared
  with Postgres and k6. With one worker the single API process is pegged (~130% = its event loop
  plus JSON/Pydantic validation) and p95 climbs to 71 ms. `batch500` already reaches
  ~115-120k rows/s with 2 workers and does not move with 4 or 8 (Postgres at ~400% CPU, i.e.
  all of the cores it can get while k6 and the API compete): that is insert cost (primary-key index
  maintenance + WAL, one commit per request), not Python. Rows/s rises ~50x from batch 1 to
  batch 500, so batching on the client side is the main ingest lever.
- **Queries aggregate rows, and that is Postgres CPU.** Single-sensor ranges are index-narrowed and
  cheap (1 day: ~5-10 ms; 30 days: ~35 ms with 2 VUs, since 43k rows are read). They do scale with
  workers up to the core count, because the API per-request overhead dominates there (447 to
  1,034 req/s). All-sensor queries read every row in range, take Postgres to ~750% (parallel
  workers), and are insensitive to API workers; more workers only add contention (30-day/all is
  slightly worse at 4 workers).
- **Latency tracks rows aggregated, not table size.** Going from 1.3M to 13M rows leaves the
  single-sensor queries unchanged (4 ms and 36 ms p50), because the primary key narrows to the same
  rows. The all-sensors queries grow linearly with the number of sensors, i.e. rows aggregated:
  60 ms to 495 ms (1 day) and 0.84 s to 12 s (30 days). So the table is "big enough" not when it
  is large but when a query's aggregated range is: ~13M rows per 30-day all-sensors query
  already takes 12 s, far beyond an interactive budget. This agrees with the plan's claim that
  partitioning alone would not help (same rows scanned) and rollups would.
- Caveats: one run per cell, 20-40 s each, closed-loop clients, everything on one 4-core host with
  other containers present, warm cache, stock Postgres. Differences of ~10-20% between worker
  counts (especially the query rows at 4 vs 8 workers) are within noise.

## What the numbers point to (plan: Limitations & next steps)

- **Query-heavy / rollups:** hourly (or daily) min/max/sum/count rollups, via a rollup table or
  TimescaleDB continuous aggregates, are what bring 30-day all-sensor queries from seconds
  to milliseconds. This is the clearest finding.
- **Ingest-heavy:** clients should batch (batch 500 gives ~25-50x the rows/s of batch 1 at
  equal worker count); beyond ~120k rows/s on this host the next steps are a durable log in front of the
  DB and `COPY`-based writers, then sharding by `sensor_id`. Group-commit style buffering would help
  `batch1` traffic from many small devices.
- **Large volume / retention:** partitioning and compression are about retention and index size,
  not about these latencies; the volume sweep shows no cliff at 13M (still page-cache resident). The
  100M point was not measured, so where the index stops fitting in RAM is unmeasured.
- **Capacity sizing:** `workers x (pool_size + max_overflow)` stayed far below `max_connections`
  at 8 workers (80 of 100); the pool was never the limit in these runs.
