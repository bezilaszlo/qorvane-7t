import os
from collections.abc import Callable
from datetime import datetime

import httpx
import pytest
from helpers import iso, past_anchor

BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(pytest.mark.blackbox)


@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=30) as http:
        try:
            http.get("/health")
        except httpx.TransportError as exc:
            pytest.exit(
                f"API not reachable at {BASE_URL} ({exc!r}); start the stack: docker compose up -d",
                returncode=2,
            )
        yield http


@pytest.fixture
def anchor() -> datetime:
    return past_anchor()


@pytest.fixture
def post_readings(client: httpx.Client) -> Callable[[list[dict]], httpx.Response]:
    def post(readings: list[dict]) -> httpx.Response:
        return client.post("/api/v1/readings", json={"readings": readings})

    return post


@pytest.fixture
def seed(post_readings: Callable[[list[dict]], httpx.Response]) -> Callable[[list[dict]], dict]:
    def run(readings: list[dict]) -> dict:
        response = post_readings(readings)
        assert response.status_code == 201, response.text
        return response.json()

    return run


@pytest.fixture
def get_stats(client: httpx.Client) -> Callable[..., httpx.Response]:
    def run(
        *,
        stat: str | None = "avg",
        metric: str | list[str] | None = None,
        sensor_id: str | list[str] | None = None,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
    ) -> httpx.Response:
        def text(value: datetime | str) -> str:
            return iso(value) if isinstance(value, datetime) else value

        params: dict[str, str | list[str]] = {}
        if stat is not None:
            params["stat"] = stat
        if metric is not None:
            params["metric"] = metric
        if sensor_id is not None:
            params["sensor_id"] = sensor_id
        if start is not None:
            params["start"] = text(start)
        if end is not None:
            params["end"] = text(end)
        return client.get("/api/v1/stats", params=params)

    return run
