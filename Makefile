.PHONY: up down test test-integration test-blackbox lint seed perf-ingest perf-query

SEED_ARGS ?= --sensors 10 --days 30
TOOLS = docker compose -f compose.yaml -f compose.tools.yaml

up:
	docker compose up --build -d

down:
	docker compose down

test:
	uv run pytest tests/unit -q

test-integration:
	uv run pytest tests/integration -q

test-blackbox:
	uv run pytest tests/blackbox -q

lint:
	uv run ruff check && uv run ruff format --check && uv run ty check

seed:
	$(TOOLS) run --rm seed $(SEED_ARGS)

perf-ingest:
	for b in 1 500; do BATCH=$$b $(TOOLS) run --rm k6 run /perf/ingest.js; done

perf-query:
	for c in day_single d30_all; do CASE=$$c $(TOOLS) run --rm k6 run /perf/query.js; done
