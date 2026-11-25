from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.ranges import RangeError, resolve_range

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)


def test_no_range_is_last_24_hours():
    assert resolve_range(None, None, NOW) == (NOW - DAY, NOW)


def test_only_end_starts_24_hours_earlier():
    end = NOW - timedelta(days=5)
    assert resolve_range(None, end, NOW) == (end - DAY, end)


def test_only_end_in_the_future_is_allowed():
    end = NOW + timedelta(days=2)
    assert resolve_range(None, end, NOW) == (end - DAY, end)


def test_only_start_ends_now():
    start = NOW - timedelta(days=3)
    assert resolve_range(start, None, NOW) == (start, NOW)


def test_both_given_are_returned_unchanged():
    start, end = NOW - timedelta(days=10), NOW - timedelta(days=2)
    assert resolve_range(start, end, NOW) == (start, end)


@pytest.mark.parametrize("length", [DAY, timedelta(days=31)], ids=["24h", "31d"])
def test_inclusive_length_bounds(length):
    start = NOW - length
    assert resolve_range(start, NOW, NOW) == (start, NOW)


@pytest.mark.parametrize(
    "length",
    [DAY - timedelta(microseconds=1), timedelta(hours=1), timedelta(days=31, microseconds=1)],
    ids=["24h-minus-1us", "1h", "31d-plus-1us"],
)
def test_out_of_bounds_length_is_rejected_not_clamped(length):
    with pytest.raises(RangeError):
        resolve_range(NOW - length, NOW, NOW)


def test_start_equal_to_end_is_rejected():
    with pytest.raises(RangeError, match="before"):
        resolve_range(NOW, NOW, NOW)


def test_start_after_end_is_rejected():
    with pytest.raises(RangeError, match="before"):
        resolve_range(NOW, NOW - 2 * DAY, NOW)


def test_only_start_too_recent_is_rejected():
    with pytest.raises(RangeError, match="24 hours"):
        resolve_range(NOW - timedelta(hours=1), None, NOW)


def test_only_start_too_old_is_rejected():
    with pytest.raises(RangeError, match="31 days"):
        resolve_range(NOW - timedelta(days=40), None, NOW)


def test_mixed_utc_offsets_compare_by_instant():
    plus_two = timezone(timedelta(hours=2))
    start = (NOW - DAY).astimezone(plus_two)
    assert resolve_range(start, NOW, NOW) == (NOW - DAY, NOW)


def test_only_start_in_the_future_is_rejected_on_start():
    with pytest.raises(RangeError) as err:
        resolve_range(NOW + timedelta(hours=1), None, NOW)
    assert err.value.field == "start"


def test_pair_error_has_no_single_field():
    with pytest.raises(RangeError) as err:
        resolve_range(NOW, NOW - DAY, NOW)
    assert err.value.field is None
