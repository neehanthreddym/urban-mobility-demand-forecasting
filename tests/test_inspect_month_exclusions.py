"""Exercise the exclusion inspector with synthetic files and pinned screening reports."""

import json

import pandas as pd
import pytest

import inspect_month_exclusions as inspector
from assess_month_quality import assess_month
from utils import month_bounds, sha256


@pytest.mark.parametrize("month", ["2025-05", "2025-06"])
def test_inspection_matches_month_and_separates_excerpts(month, tmp_path, monkeypatch):
    monkeypatch.setattr(inspector, "ROOT", tmp_path)
    trips = tmp_path / f"data/raw/yellow_tripdata_{month}.parquet"
    lookup = tmp_path / "data/reference/taxi_zone_lookup.csv"
    manifest = tmp_path / "data/manifest.json"
    trips.parent.mkdir(parents=True)
    lookup.parent.mkdir()
    lookup.write_text("LocationID,Borough,Zone\n2,Queens,Test\n1,EWR,Newark Airport\n265,N/A,Outside of NYC\n")
    start, end = month_bounds(month)
    hours = list(pd.date_range(start, end, freq="h", inclusive="left"))
    pd.DataFrame({
        "tpep_pickup_datetime": hours + [start - pd.Timedelta(seconds=1), end, start, start],
        "PULocationID": [2] * len(hours) + [2, 2, 1, 265],
    }).to_parquet(trips, index=False)
    manifest.write_text(json.dumps({"files": [
        {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256(path),
         "source_url": "synthetic", "study_month": month} for path in (trips, lookup)
    ]}))
    baseline, _, _ = assess_month(month, trips, lookup, manifest)
    quality = tmp_path / "report.json"
    quality.write_text(json.dumps(baseline))
    report, excerpts, groups = inspector.inspect(quality, month)
    assert report["status"] == "RECONCILED"
    assert report["date_exclusions_by_direction"] == {"before_month": 1, "on_or_after_next_month": 1}
    assert report["geographic_classification_totals"] == {
        "known_outside_nyc": 1, "unknown_or_unspecified": 1, "unresolved_reference": 0,
    }
    assert [item["source_row_number"] for item in excerpts] == [len(hours) + 1, len(hours) + 2]
    public, private = inspector.write_outputs(report, excerpts, groups)
    assert (private / "out_of_month_records.csv").is_file()
    assert public.is_relative_to(tmp_path / "reports")
    assert private.is_relative_to(tmp_path / "data/interim")
    assert not (public / "out_of_month_records.csv").exists()
    baseline["counts"]["accepted_for_month_nyc_screening"] += 1
    quality.write_text(json.dumps(baseline))
    with pytest.raises(ValueError, match="Baseline count mismatch"):
        inspector.inspect(quality, month)
