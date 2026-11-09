"""Synthetic checks for monthly boundaries, exclusions, and legacy April parity."""

import copy
import json

import pandas as pd
import pytest

from assess_april_quality import assess as legacy_assess
from utils import sha256
from assess_month_quality import assess_month, compare_april, month_bounds


@pytest.fixture
def april_inputs(tmp_path):
    """Create tiny, hashed inputs independent of downloaded data.

    Args:
        tmp_path: Pytest-managed temporary directory.

    Output:
        tuple: Synthetic trip, lookup, and manifest paths.
    """
    trips = tmp_path / "yellow_tripdata_2025-04.parquet"
    lookup = tmp_path / "taxi_zone_lookup.csv"
    manifest = tmp_path / "manifest.json"
    pd.DataFrame({
        "tpep_pickup_datetime": pd.to_datetime([
            "2025-04-01 00:00:00", "2025-04-30 23:59:59",
            "2025-03-31 23:59:59", "2025-05-01 00:00:00",
            "2025-04-02 12:00:00", "2025-04-02 12:00:00",
            "2025-04-02 12:00:00", None,
        ]),
        "PULocationID": pd.Series([2, 2, 2, 2, 1, 999, None, 2], dtype="Int64"),
    }).to_parquet(trips, index=False)
    lookup.write_text(
        "LocationID,Borough,Zone\n1,EWR,Newark Airport\n2,Queens,Jamaica Bay\n3,Bronx,Test zone\n",
        encoding="utf-8",
    )
    manifest.write_text(json.dumps({"files": [
        {"path": str(path), "size_bytes": path.stat().st_size,
         "sha256": sha256(path), "source_url": "https://example.invalid/synthetic",
         **({"study_month": "2025-04"} if path == trips else {})}
        for path in (trips, lookup)
    ]}), encoding="utf-8")
    return trips, lookup, manifest


@pytest.mark.parametrize("month,end,hours", [
    ("2025-04", "2025-05-01", 720),
    ("2025-05", "2025-06-01", 744),
    ("2025-06", "2025-07-01", 720),
    ("2024-02", "2024-03-01", 696),
    ("2025-12", "2026-01-01", 744),
])
def test_calendar_boundaries(month, end, hours):
    """Handle different month lengths, leap years, and year rollover."""
    start, stop = month_bounds(month)
    assert stop == pd.Timestamp(end)
    assert start.day == 1
    assert len(pd.date_range(start, stop, freq="h", inclusive="left")) == hours


@pytest.mark.parametrize("month", ["2025-4", "2025-13", "2025-00", "not-a-month", "2025-05-01"])
def test_invalid_month_rejected(month):
    """Reject ambiguous or invalid month inputs instead of guessing dates."""
    with pytest.raises(ValueError, match="YYYY-MM"):
        month_bounds(month)


@pytest.mark.parametrize("month", ["2025-03", "2025-11"])
def test_clock_change_requires_policy(month):
    """Do not silently generalize the MVP's no-clock-change assumption."""
    with pytest.raises(ValueError, match="Clock-change"):
        month_bounds(month)


def test_exclusions_and_reconciliation(april_inputs):
    """Check independent expected counts for bad keys, boundaries, and scope."""
    report, hourly, daily = assess_month("2025-04", *april_inputs)
    assert report["counts"]["total_rows"] == 8
    assert report["counts"]["combined_key_quality_failures"] == 3
    assert report["counts"]["out_of_month_timestamp"] == 2
    assert report["counts"]["in_month_mapped_non_nyc_scope_exclusions"] == 1
    assert report["counts"]["accepted_for_month_nyc_screening"] == 2
    assert sum(report["exclusive_row_dispositions"].values()) == 8
    assert len(hourly) == 720 and len(daily) == 30
    assert hourly["observed_accepted_records"].sum() == 2
    assert hourly["observed_accepted_records"].iloc[0] == 1
    assert hourly["observed_accepted_records"].iloc[-1] == 1
    assert report["hourly_coverage"]["zero_observed_hours"] == 718
    assert report["lookup"]["zones_with_zero_accepted_records"] == [3]
    assert report["status"] == "REVIEW_REQUIRED"


def test_legacy_april_parity(april_inputs):
    """Reproduce legacy counts and hourly/daily tables on a fixed synthetic case."""
    original, original_hourly, original_daily = legacy_assess(*april_inputs)
    current, hourly, daily = assess_month("2025-04", *april_inputs)
    compare_april(current, original)
    pd.testing.assert_frame_equal(hourly, original_hourly)
    pd.testing.assert_frame_equal(daily, original_daily)


def test_regression_mismatch_fails(april_inputs):
    """An altered accepted-count baseline must not pass the comparison."""
    original, _, _ = legacy_assess(*april_inputs)
    current, _, _ = assess_month("2025-04", *april_inputs)
    changed = copy.deepcopy(original)
    changed["counts"]["accepted_for_april_nyc_screening"] += 1
    with pytest.raises(ValueError, match="counts"):
        compare_april(current, changed)


def test_month_manifest_mismatch_fails(april_inputs):
    """Do not screen the April snapshot as May merely by changing a CLI argument."""
    with pytest.raises(ValueError, match="study_month"):
        assess_month("2025-05", *april_inputs)


@pytest.mark.parametrize("month,hours,accepted,outside", [
    ("2025-05", 744, 1, 6),
    ("2025-06", 720, 0, 7),
])
def test_requested_month_controls_filtering(april_inputs, month, hours, accepted, outside):
    """Use requested bounds rather than leftover April constants when scanning."""
    trips, lookup, manifest = april_inputs
    record = json.loads(manifest.read_text(encoding="utf-8"))
    record["files"][0]["study_month"] = month
    manifest.write_text(json.dumps(record), encoding="utf-8")
    report, hourly, _ = assess_month(month, trips, lookup, manifest)
    assert len(hourly) == hours
    assert report["counts"]["accepted_for_month_nyc_screening"] == accepted
    assert report["counts"]["out_of_month_timestamp"] == outside
    assert hourly["observed_accepted_records"].sum() == accepted


def test_changed_input_fails(april_inputs):
    """Reject changed source bytes before relying on a prior manifest."""
    trips, lookup, manifest = april_inputs
    with trips.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="checksum mismatch"):
        assess_month("2025-04", trips, lookup, manifest)
