from datetime import UTC, datetime, timedelta

import httpx
from helpers import new_metric, new_sensor, reading


def listed_pairs(client: httpx.Client) -> list[dict]:
    response = client.get("/api/v1/sensors")
    assert response.status_code == 200
    return response.json()["sensors"]


def test_lists_pairs_seen_in_last_24_hours(client, seed):
    sensor, metric = new_sensor(), new_metric()
    seed([reading(sensor, datetime.now(UTC) - timedelta(hours=2), {metric: 1.0})])
    assert {"sensor_id": sensor, "metric": metric} in listed_pairs(client)


def test_pair_ingested_without_ts_is_listed(client, seed):
    sensor, metric = new_sensor(), new_metric()
    seed([reading(sensor, None, {metric: 1.0})])
    assert {"sensor_id": sensor, "metric": metric} in listed_pairs(client)


def test_each_metric_of_a_sensor_is_listed(client, seed):
    sensor, m1, m2 = new_sensor(), new_metric(), new_metric()
    seed([reading(sensor, datetime.now(UTC) - timedelta(hours=1), {m1: 1.0, m2: 2.0})])
    pairs = listed_pairs(client)
    assert {"sensor_id": sensor, "metric": m1} in pairs
    assert {"sensor_id": sensor, "metric": m2} in pairs


def test_pair_older_than_24_hours_is_not_listed(client, seed):
    sensor, metric = new_sensor(), new_metric()
    seed([reading(sensor, datetime.now(UTC) - timedelta(days=3), {metric: 1.0})])
    assert {"sensor_id": sensor, "metric": metric} not in listed_pairs(client)
