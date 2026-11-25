from datetime import UTC, datetime, timedelta, timezone

import pytest
from helpers import by_key, iso, new_metric, new_sensor, parse, reading

DAY = timedelta(days=1)


def seed_series(seed, sensor, metric, start, values):
    seed([reading(sensor, start + timedelta(minutes=i), {metric: v}) for i, v in enumerate(values)])


@pytest.mark.parametrize(
    ("stat", "expected"),
    [("min", -2.5), ("max", 9.0), ("sum", 13.5), ("avg", 13.5 / 4)],
)
def test_each_stat_on_known_values(seed, get_stats, anchor, stat, expected):
    sensor, metric = new_sensor(), new_metric()
    seed_series(seed, sensor, metric, anchor, [-2.5, 9.0, 3.0, 4.0])

    response = get_stats(stat=stat, metric=metric, sensor_id=sensor, start=anchor, end=anchor + DAY)
    assert response.status_code == 200
    (row,) = response.json()["results"]
    assert row["sensor_id"] == sensor
    assert row["metric"] == metric
    assert row["value"] == pytest.approx(expected)
    assert row["count"] == 4


def test_multiple_sensors_and_metrics(seed, get_stats, anchor):
    s1, s2 = new_sensor(), new_sensor()
    temp, hum = new_metric(), new_metric()
    seed(
        [
            reading(s1, anchor, {temp: 10.0, hum: 50.0}),
            reading(s1, anchor + timedelta(minutes=1), {temp: 20.0, hum: 70.0}),
            reading(s2, anchor, {temp: 100.0, hum: 1.0}),
        ]
    )
    response = get_stats(
        stat="sum", metric=[temp, hum], sensor_id=[s1, s2], start=anchor, end=anchor + DAY
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 4
    rows = by_key(results)
    assert rows[(s1, temp)]["value"] == pytest.approx(30.0)
    assert rows[(s1, temp)]["count"] == 2
    assert rows[(s1, hum)]["value"] == pytest.approx(120.0)
    assert rows[(s1, hum)]["count"] == 2
    assert rows[(s2, temp)]["value"] == pytest.approx(100.0)
    assert rows[(s2, temp)]["count"] == 1
    assert rows[(s2, hum)]["value"] == pytest.approx(1.0)
    assert rows[(s2, hum)]["count"] == 1


def test_only_requested_sensors_and_metrics_are_returned(seed, get_stats, anchor):
    s1, s2 = new_sensor(), new_sensor()
    wanted, other = new_metric(), new_metric()
    seed([reading(s, anchor, {wanted: 1.0, other: 2.0}) for s in (s1, s2)])
    results = get_stats(
        stat="sum", metric=wanted, sensor_id=s1, start=anchor, end=anchor + DAY
    ).json()["results"]
    assert [(r["sensor_id"], r["metric"]) for r in results] == [(s1, wanted)]


def test_all_sensors_when_sensor_id_omitted(seed, get_stats, anchor):
    sensors = [new_sensor() for _ in range(3)]
    metric = new_metric()
    seed([reading(s, anchor, {metric: float(i)}) for i, s in enumerate(sensors, start=1)])

    response = get_stats(stat="max", metric=metric, start=anchor, end=anchor + DAY)
    assert response.status_code == 200
    rows = by_key(response.json()["results"])
    assert set(rows) == {(s, metric) for s in sensors}
    for i, s in enumerate(sensors, start=1):
        assert rows[(s, metric)]["value"] == pytest.approx(float(i))
        assert rows[(s, metric)]["count"] == 1


def test_response_echoes_stat_and_resolved_range(get_stats, anchor):
    start, end = anchor, anchor + timedelta(days=2)
    response = get_stats(stat="min", metric=new_metric(), start=start, end=end)
    assert response.status_code == 200
    body = response.json()
    assert body["stat"] == "min"
    assert parse(body["start"]) == start
    assert parse(body["end"]) == end
    assert body["results"] == []


def test_range_is_half_open(seed, get_stats, anchor):
    sensor, metric = new_sensor(), new_metric()
    start, end = anchor, anchor + DAY
    seed(
        [
            reading(sensor, start, {metric: 1.0}),
            reading(sensor, start + timedelta(hours=1), {metric: 10.0}),
            reading(sensor, end - timedelta(seconds=1), {metric: 100.0}),
            reading(sensor, end, {metric: 1000.0}),
        ]
    )
    (row,) = get_stats(stat="sum", metric=metric, sensor_id=sensor, start=start, end=end).json()[
        "results"
    ]
    assert row["value"] == pytest.approx(111.0)
    assert row["count"] == 3


def test_range_with_non_utc_offset(seed, get_stats, anchor):
    sensor, metric = new_sensor(), new_metric()
    seed([reading(sensor, anchor, {metric: 5.0})])
    plus_two = timezone(timedelta(hours=2))
    start = anchor - timedelta(hours=1)
    end = (start + DAY).astimezone(plus_two).isoformat()
    response = get_stats(stat="sum", metric=metric, sensor_id=sensor, start=start, end=end)
    assert response.status_code == 200
    assert [r["value"] for r in response.json()["results"]] == [5.0]


@pytest.mark.parametrize("miss", ["sensor", "metric", "range"])
def test_no_matching_data_returns_empty_results(seed, get_stats, anchor, miss):
    sensor, metric = new_sensor(), new_metric()
    seed([reading(sensor, anchor, {metric: 1.0})])
    start = anchor + 2 * DAY if miss == "range" else anchor
    response = get_stats(
        stat="avg",
        metric=new_metric() if miss == "metric" else metric,
        sensor_id=new_sensor() if miss == "sensor" else sensor,
        start=start,
        end=start + DAY,
    )
    assert response.status_code == 200
    assert response.json()["results"] == []


@pytest.mark.parametrize(
    "length",
    [timedelta(hours=24), timedelta(days=31)],
    ids=["exactly-24h", "exactly-31d"],
)
def test_range_length_bounds_are_inclusive(get_stats, anchor, length):
    start = anchor - timedelta(days=1)
    response = get_stats(metric=new_metric(), start=start, end=start + length)
    assert response.status_code == 200
    assert parse(response.json()["end"]) - parse(response.json()["start"]) == length


@pytest.mark.parametrize(
    "length",
    [timedelta(hours=24) - timedelta(seconds=1), timedelta(days=31) + timedelta(seconds=1)],
    ids=["24h-minus-1s", "31d-plus-1s"],
)
def test_range_length_out_of_bounds_rejected(get_stats, anchor, length):
    start = anchor - timedelta(days=1)
    response = get_stats(metric=new_metric(), start=start, end=start + length)
    assert response.status_code == 422


def test_start_equal_to_end_rejected(get_stats, anchor):
    assert get_stats(metric=new_metric(), start=anchor, end=anchor).status_code == 422


def test_start_after_end_rejected(get_stats, anchor):
    response = get_stats(metric=new_metric(), start=anchor + DAY, end=anchor)
    assert response.status_code == 422


@pytest.mark.parametrize("which", ["start", "end"])
def test_naive_timestamp_rejected(get_stats, anchor, which):
    naive = anchor.replace(tzinfo=None).isoformat()
    params = {"start": iso(anchor), "end": iso(anchor + DAY)}
    params[which] = naive
    assert get_stats(metric=new_metric(), **params).status_code == 422


def test_unparseable_timestamp_rejected(get_stats):
    assert get_stats(metric=new_metric(), start="yesterday").status_code == 422


def test_default_range_is_last_24_hours(seed, get_stats):
    sensor, metric = new_sensor(), new_metric()
    now = datetime.now(UTC)
    seed(
        [
            reading(sensor, now - timedelta(hours=3), {metric: 1.0}),
            reading(sensor, now - timedelta(hours=2), {metric: 3.0}),
            reading(sensor, now - timedelta(hours=30), {metric: 1000.0}),
        ]
    )
    response = get_stats(stat="sum", metric=metric, sensor_id=sensor)
    assert response.status_code == 200
    body = response.json()
    assert abs(parse(body["end"]) - now) < timedelta(minutes=1)
    assert parse(body["end"]) - parse(body["start"]) == DAY
    (row,) = body["results"]
    assert row["value"] == pytest.approx(4.0)
    assert row["count"] == 2


def test_only_end_given_starts_24_hours_earlier(seed, get_stats, anchor):
    sensor, metric = new_sensor(), new_metric()
    end = anchor + timedelta(days=1)
    seed(
        [
            reading(sensor, end - timedelta(hours=23), {metric: 2.0}),
            reading(sensor, end - timedelta(hours=25), {metric: 1000.0}),
        ]
    )
    response = get_stats(stat="sum", metric=metric, sensor_id=sensor, end=end)
    assert response.status_code == 200
    body = response.json()
    assert parse(body["end"]) == end
    assert parse(body["start"]) == end - DAY
    assert [r["value"] for r in body["results"]] == [2.0]


def test_only_start_given_ends_now(seed, get_stats):
    sensor, metric = new_sensor(), new_metric()
    now = datetime.now(UTC)
    start = (now - timedelta(days=2)).replace(second=0, microsecond=0)
    seed(
        [
            reading(sensor, start + timedelta(hours=1), {metric: 4.0}),
            reading(sensor, now - timedelta(hours=1), {metric: 5.0}),
            reading(sensor, start - timedelta(hours=1), {metric: 1000.0}),
        ]
    )
    response = get_stats(stat="sum", metric=metric, sensor_id=sensor, start=start)
    assert response.status_code == 200
    body = response.json()
    assert parse(body["start"]) == start
    assert abs(parse(body["end"]) - now) < timedelta(minutes=1)
    assert [r["value"] for r in body["results"]] == [9.0]


@pytest.mark.parametrize("age", [timedelta(hours=1), timedelta(days=40)], ids=["1h", "40d"])
def test_only_start_giving_range_outside_bounds_rejected(get_stats, age):
    start = datetime.now(UTC) - age
    assert get_stats(metric=new_metric(), start=start).status_code == 422


def test_missing_metric_rejected(get_stats):
    assert get_stats(stat="avg", metric=None).status_code == 422


@pytest.mark.parametrize("stat", ["AVG", "median"])
def test_invalid_stat_rejected(get_stats, stat):
    assert get_stats(stat=stat, metric=new_metric()).status_code == 422


@pytest.mark.parametrize(("param", "value"), [("sensor_id", "Sensor-1"), ("metric", "Temperature")])
def test_malformed_sensor_id_or_metric_rejected(get_stats, anchor, param, value):
    params = {"sensor_id": new_sensor(), "metric": new_metric(), param: value}
    assert get_stats(start=anchor, end=anchor + DAY, **params).status_code == 422


def test_missing_stat_rejected(get_stats):
    assert get_stats(stat=None, metric=new_metric()).status_code == 422


def test_sum_overflow_is_a_client_error_not_500(seed, get_stats, anchor):
    sensor, metric = new_sensor(), new_metric()
    seed_series(seed, sensor, metric, anchor, [1e308, 1e308])
    response = get_stats(
        stat="sum", metric=metric, sensor_id=sensor, start=anchor, end=anchor + DAY
    )
    assert response.status_code == 422


def test_results_are_ordered_by_sensor_and_metric(seed, get_stats, anchor):
    sensors = sorted(new_sensor() for _ in range(3))
    metric = new_metric()
    seed([reading(s, anchor, {metric: 1.0}) for s in reversed(sensors)])
    results = get_stats(
        stat="sum", metric=metric, sensor_id=sensors, start=anchor, end=anchor + DAY
    )
    assert [r["sensor_id"] for r in results.json()["results"]] == sensors
