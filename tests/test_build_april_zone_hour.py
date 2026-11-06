"""Synthetic tests only: do not read or modify downloaded trip data."""

from collections import Counter

import pandas as pd
import pytest

from build_april_zone_hour import START, TZ, aggregate_batch, complete_grid


def test_boundaries_and_exclusive_dispositions():
    """April includes its first instant, excludes May, and separates invalid keys."""
    frame = pd.DataFrame({
        "tpep_pickup_datetime": pd.to_datetime([
            "2025-03-31 23:59:59", "2025-04-01 00:00:00", "2025-04-01 00:59:59",
            "2025-04-30 23:59:59", "2025-05-01 00:00:00", None,
            "2025-04-02 12:00:00", "2025-04-02 12:00:00", "2025-04-02 12:00:00",
        ]),
        "PULocationID": pd.Series([2, 2, 2, 2, 2, 2, 264, 999, None], dtype="Int64"),
    })
    cells, dispositions = aggregate_batch(frame, {2, 3}, {1, 2, 3, 264, 265})
    assert cells[(2, START)] == 2
    assert cells[(2, pd.Timestamp("2025-04-30 23:00", tz=TZ))] == 1
    assert sum(cells.values()) == 3
    assert dispositions == {"bad_timestamp": 1, "bad_zone_after_timestamp_check": 2,
                            "out_of_april_after_key_checks": 2,
                            "mapped_non_nyc_in_april": 1, "accepted": 3}
    assert sum(dispositions.values()) == len(frame)


def test_naive_localization_preserves_clock_hour():
    """A naive 09:30 pickup must stay in the assumed NYC 09:00 bucket."""
    frame = pd.DataFrame({"tpep_pickup_datetime": pd.to_datetime(["2025-04-03 09:30"]),
                          "PULocationID": [2]})
    cells, _ = aggregate_batch(frame, {2}, {2})
    assert cells == {(2, pd.Timestamp("2025-04-03 09:00", tz=TZ)): 1}


def test_grid_retains_inactive_zones_and_integer_zeros():
    """Grid completion retains zero-observed zones without losing accepted counts."""
    table = complete_grid(Counter({(2, START): 3}), {2, 3})
    assert len(table) == 2 * 720
    assert not table.duplicated(["pickup_zone_id", "hour_start"]).any()
    assert str(table["hour_start"].dt.tz) == TZ
    assert pd.api.types.is_integer_dtype(table["pickup_count"])
    assert table["pickup_count"].sum() == 3
    assert table.loc[table["pickup_zone_id"].eq(3), "pickup_count"].eq(0).all()
    assert not table.isna().any().any()


def test_grid_rejects_out_of_scope_keys():
    """Do not silently discard aggregates outside the approved zone universe."""
    with pytest.raises(ValueError, match="outside"):
        complete_grid(Counter({(999, START): 1}), {2})


@pytest.mark.parametrize("count", [-1, 1.5])
def test_grid_rejects_invalid_counts(count):
    """Reject negative or non-integer counts before writing a prepared dataset."""
    with pytest.raises(ValueError, match="nonnegative integers"):
        complete_grid(Counter({(2, START): count}), {2})
