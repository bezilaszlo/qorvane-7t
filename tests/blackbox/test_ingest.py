from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest
from helpers import new_metric, new_sensor, reading


def test_single_reading_with_several_metrics(post_readings, anchor):
    response = post_readings(
        [reading(new_sensor(), anchor, {"temperature": 21.3, "humidity": 40.0, "wind": 0.0})]
    )
    assert response.status_code == 201
    assert response.json() == {"inserted": 3, "duplicates": 0}


def test_batch_counts_points_per_sensor_metric_ts(post_readings, anchor):
    a, b = new_sensor(), new_sensor()
    response = post_readings(
        [
            reading(a, anchor, {"temperature": 1.0, "humidity": 2.0}),
            reading(a, anchor + timedelta(minutes=1), {"temperature": 3.0}),
            reading(b, anchor, {"temperature": 4.0}),
        ]
    )
    assert response.status_code == 201
    assert response.json() == {"inserted": 4, "duplicates": 0}


def test_resending_the_same_batch_is_all_duplicates(post_readings, anchor):
    batch = [reading(new_sensor(), anchor, {"temperature": 1.0, "humidity": 2.0})]
    assert post_readings(batch).json() == {"inserted": 2, "duplicates": 0}
    again = post_readings(batch)
    assert again.status_code == 201
    assert again.json() == {"inserted": 0, "duplicates": 2}


def test_duplicate_with_different_value_does_not_overwrite(post_readings, get_stats, anchor):
    sensor, metric = new_sensor(), new_metric()
    assert post_readings([reading(sensor, anchor, {metric: 1.0})]).json()["inserted"] == 1
    again = post_readings([reading(sensor, anchor, {metric: 99.0})])
    assert again.json() == {"inserted": 0, "duplicates": 1}

    rows = get_stats(
        stat="max", metric=metric, sensor_id=sensor, start=anchor, end=anchor + timedelta(days=1)
    ).json()["results"]
    assert rows == [{"sensor_id": sensor, "metric": metric, "value": 1.0, "count": 1}]


def test_partially_duplicate_batch(post_readings, anchor):
    sensor = new_sensor()
    assert post_readings([reading(sensor, anchor, {"temperature": 1.0})]).status_code == 201
    response = post_readings([reading(sensor, anchor, {"temperature": 5.0, "humidity": 6.0})])
    assert response.json() == {"inserted": 1, "duplicates": 1}


def test_duplicates_within_one_batch(post_readings, get_stats, anchor):
    sensor, metric = new_sensor(), new_metric()
    response = post_readings(
        [reading(sensor, anchor, {metric: 1.0}), reading(sensor, anchor, {metric: 2.0})]
    )
    assert response.status_code == 201
    assert response.json() == {"inserted": 1, "duplicates": 1}

    rows = get_stats(
        stat="sum",
        metric=metric,
        sensor_id=sensor,
        start=anchor,
        end=anchor + timedelta(days=1),
    ).json()["results"]
    assert len(rows) == 1
    assert rows[0]["count"] == 1


def test_omitted_ts_uses_server_time(post_readings, get_stats):
    sensor, metric = new_sensor(), new_metric()
    response = post_readings([reading(sensor, None, {metric: 7.5})])
    assert response.status_code == 201
    assert response.json() == {"inserted": 1, "duplicates": 0}

    rows = get_stats(stat="sum", metric=metric, sensor_id=sensor).json()["results"]
    assert rows == [{"sensor_id": sensor, "metric": metric, "value": 7.5, "count": 1}]


def test_non_utc_offset_is_accepted(post_readings, anchor):
    local = anchor.astimezone(timezone(timedelta(hours=2)))
    response = post_readings(
        [{"sensor_id": new_sensor(), "ts": local.isoformat(), "metrics": {"temperature": 1.0}}]
    )
    assert response.status_code == 201


def test_timestamp_slightly_in_the_future_is_accepted(post_readings):
    ts = datetime.now(UTC) + timedelta(minutes=1)
    assert post_readings([reading(new_sensor(), ts, {"temperature": 1.0})]).status_code == 201


def test_batch_at_point_limit_is_accepted(post_readings, anchor):
    metrics = {f"{new_metric()}_{i}": float(i) for i in range(10)}
    batch = [reading(new_sensor(), anchor, metrics) for _ in range(1000)]
    response = post_readings(batch)
    assert response.status_code == 201
    assert response.json() == {"inserted": 10_000, "duplicates": 0}


def test_empty_readings_list_rejected(post_readings):
    assert post_readings([]).status_code == 422


def test_too_many_readings_rejected(post_readings, anchor):
    batch = [reading(new_sensor(), anchor, {"temperature": 1.0}) for _ in range(1001)]
    assert post_readings(batch).status_code == 422


def test_too_many_points_rejected(post_readings, anchor):
    metrics = {f"{new_metric()}_{i}": 1.0 for i in range(11)}
    batch = [reading(new_sensor(), anchor, metrics) for _ in range(1000)]
    assert post_readings(batch).status_code == 422


def test_empty_metrics_rejected(post_readings, anchor):
    assert post_readings([reading(new_sensor(), anchor, {})]).status_code == 422


def test_missing_metrics_rejected(post_readings):
    assert post_readings([{"sensor_id": new_sensor()}]).status_code == 422


@pytest.mark.parametrize(
    "literal",
    ["NaN", "Infinity", "-Infinity", "1e999", '"NaN"', '"inf"'],
)
def test_non_finite_value_rejected(client: httpx.Client, literal):
    sensor = new_sensor()
    body = f'{{"readings": [{{"sensor_id": "{sensor}", "metrics": {{"temperature": {literal}}}}}]}}'
    response = client.post(
        "/api/v1/readings", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("value", ["warm", None, [1.0], {"a": 1}])
def test_non_numeric_value_rejected(post_readings, anchor, value):
    assert post_readings([reading(new_sensor(), anchor, {"temperature": value})]).status_code == 422


@pytest.mark.parametrize("ts", ["2026-01-01T00:00:00", "2026-01-01", "not-a-date"])
def test_naive_or_invalid_timestamp_rejected(post_readings, ts):
    response = post_readings(
        [{"sensor_id": new_sensor(), "ts": ts, "metrics": {"temperature": 1.0}}]
    )
    assert response.status_code == 422


def test_timestamp_more_than_five_minutes_in_future_rejected(post_readings):
    ts = datetime.now(UTC) + timedelta(minutes=10)
    assert post_readings([reading(new_sensor(), ts, {"temperature": 1.0})]).status_code == 422


def test_future_timestamp_rejects_the_whole_batch(post_readings, get_stats, anchor):
    good, bad, metric = new_sensor(), new_sensor(), new_metric()
    future = datetime.now(UTC) + timedelta(hours=1)
    response = post_readings(
        [reading(good, anchor, {metric: 1.0}), reading(bad, future, {metric: 2.0})]
    )
    assert response.status_code == 422
    results = get_stats(
        stat="sum", metric=metric, start=anchor, end=anchor + timedelta(days=1)
    ).json()["results"]
    assert results == []


@pytest.mark.parametrize(
    "sensor_id",
    ["Sensor-1", "-leading-hyphen", "a" * 65, "", "has space", "_underscore-first"],
)
def test_bad_sensor_id_rejected(post_readings, anchor, sensor_id):
    assert post_readings([reading(sensor_id, anchor, {"temperature": 1.0})]).status_code == 422


@pytest.mark.parametrize(
    "metric", ["Temperature", "1temp", "_temp", "a" * 33, "", "with-hyphen", "with space"]
)
def test_bad_metric_name_rejected(post_readings, anchor, metric):
    assert post_readings([reading(new_sensor(), anchor, {metric: 1.0})]).status_code == 422


def test_boundary_length_names_accepted(post_readings, anchor):
    sensor = "a" + "b" * 63
    metric = "a" + "b" * 31
    assert post_readings([reading(sensor, anchor, {metric: 1.0})]).status_code == 201
