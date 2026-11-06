#!/usr/bin/env python3
"""Build April's observed zone-hour counts after screening and exclusion checks.

Run: uv run --locked python scripts/build_april_zone_hour.py
Raw files and historical reports are unchanged. Exit 0 on success, 1 on failure.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from assess_april_quality import ROOT, project_path, read_lookup, sha256, verify_input

TZ = "America/New_York"
START = pd.Timestamp("2025-04-01", tz=TZ)
END = pd.Timestamp("2025-05-01", tz=TZ)
QUALITY = "reports/data_quality/april_2025/20261104T053754311799Z/report.json"
EXCLUSIONS = "reports/data_quality/april_2025_exclusions/20261105T074607348105Z/report.json"


def aggregate_batch(frame: pd.DataFrame, nyc: set[int], mapped: set[int]) -> tuple[Counter, Counter]:
    """Count accepted pickups by zone-hour and track exclusive row dispositions.

    Args:
        frame: Batch with pickup timestamp and PULocationID columns.
        nyc: In-scope NYC reference IDs.
        mapped: All validated lookup IDs, including non-NYC entries.

    Output:
        tuple: Counter keyed by (zone ID, timezone-aware hour) and exclusive
        disposition counts. Naive clocks are localized under assumption D05.
    """
    pickup = pd.to_datetime(frame["tpep_pickup_datetime"], errors="coerce")
    if pickup.dt.tz is None:
        pickup = pickup.dt.tz_localize(TZ, ambiguous="raise", nonexistent="raise")
    else:
        pickup = pickup.dt.tz_convert(TZ)
    zone = frame["PULocationID"].astype("Int64")
    valid_time = pickup.notna()
    valid_zone = zone.isin(mapped)
    in_month = valid_time & pickup.ge(START) & pickup.lt(END)
    accepted = in_month & zone.isin(nyc)
    selected = pd.DataFrame({"pickup_zone_id": zone[accepted],
                             "hour_start": pickup[accepted].dt.floor("h")})
    grouped = selected.groupby(["pickup_zone_id", "hour_start"]).size()
    cells = Counter({(int(key[0]), key[1]): int(value) for key, value in grouped.items()})
    dispositions = Counter({
        "bad_timestamp": int((~valid_time).sum()),
        "bad_zone_after_timestamp_check": int((valid_time & ~valid_zone).sum()),
        "out_of_april_after_key_checks": int((valid_time & valid_zone & ~in_month).sum()),
        "mapped_non_nyc_in_april": int((in_month & valid_zone & ~zone.isin(nyc)).sum()),
        "accepted": int(accepted.sum()),
    })
    if sum(dispositions.values()) != len(frame):
        raise ValueError("Batch dispositions do not reconcile")
    return cells, dispositions


def complete_grid(cells: Counter, zone_ids: set[int]) -> pd.DataFrame:
    """Retain all in-scope zone-hours, including zero observed-count cells.

    Args:
        cells: Nonzero accepted counts keyed by (zone ID, localized hour).
        zone_ids: Frozen in-scope zone universe, including inactive zones.

    Output:
        DataFrame: Unique zone-hour keys and nonnegative int64 pickup_count.

    Raises:
        ValueError: Any key lies outside the grid or a count is invalid.
    """
    if not zone_ids:
        raise ValueError("NYC zone universe is empty")
    hours = pd.date_range(START, END, freq="h", inclusive="left")
    index = pd.MultiIndex.from_product([sorted(zone_ids), hours],
                                      names=["pickup_zone_id", "hour_start"])
    if any(key not in index for key in cells):
        raise ValueError("Aggregated key outside the approved zone-hour grid")
    if any(not isinstance(value, int) or value < 0 for value in cells.values()):
        raise ValueError("Counts must be nonnegative integers")
    table = index.to_frame(index=False)
    table["pickup_zone_id"] = table["pickup_zone_id"].astype("int64")
    table["pickup_count"] = pd.Series([cells.get(key, 0) for key in index], dtype="int64")
    return table


def build(quality_path: Path, exclusions_path: Path) -> tuple[pd.DataFrame, dict]:
    """Gate input snapshots, aggregate in batches, and validate the complete grid.

    Args:
        quality_path: Preliminary screening JSON with successful coverage checks.
        exclusions_path: Reconciled exclusion JSON referencing that screening.

    Output:
        tuple: Prepared zone-hour DataFrame and reproducibility/validation record.
        No files are written by this function.

    Raises:
        ValueError: Reports, snapshots, schema, coverage, or counts disagree.
    """
    manifest_path = ROOT / "data/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    exclusions = json.loads(exclusions_path.read_text(encoding="utf-8"))
    if quality["status"] != "PASS_PRELIMINARY" or exclusions["status"] != "RECONCILED":
        raise ValueError("Successful screening and reconciled exclusions are required")
    if not quality["reconciliation_passed"] or not exclusions["reconciliation_passed"]:
        raise ValueError("Prior report reconciliation failed")
    if exclusions["baseline_report"]["sha256"] != sha256(quality_path):
        raise ValueError("Exclusion report references a different screening report")
    if quality["counts"] != exclusions["counts"]:
        raise ValueError("Prior diagnostic counts disagree")
    coverage = quality["hourly_coverage"]
    if (coverage["expected_april_hours"] != 720 or coverage["zero_observed_hours"] != 0
            or coverage["unusually_low_hours"] != 0 or quality["review_reasons"]):
        raise ValueError("Coverage requires review before zero-count grid completion")
    if exclusions["geographic_classification_totals"]["unresolved_reference"]:
        raise ValueError("Unresolved geographic labels require review")

    trips = ROOT / "data/raw/yellow_tripdata_2025-04.parquet"
    lookup_path = ROOT / "data/reference/taxi_zone_lookup.csv"
    inputs = [verify_input(path, manifest["files"]) for path in (trips, lookup_path)]
    for report in (quality, exclusions):
        for item in inputs:
            matches = [old for old in report["inputs"]
                       if Path(old["path"]).name == Path(item["path"]).name]
            if len(matches) != 1 or any(matches[0][key] != item[key]
                                       for key in ("sha256", "size_bytes")):
                raise ValueError("A prior report does not describe the current input snapshot")
    lookup, nyc = read_lookup(lookup_path)
    if len(nyc) != quality["lookup"]["in_scope_nyc_ids"]:
        raise ValueError("Zone universe differs from screening")
    source = pq.ParquetFile(trips)
    names = ("tpep_pickup_datetime", "PULocationID")
    schema = source.schema_arrow
    if any(schema.names.count(name) != 1 for name in names):
        raise ValueError("Required source columns missing or duplicated")
    if (not pa.types.is_timestamp(schema.field(names[0]).type)
            or not pa.types.is_integer(schema.field(names[1]).type)):
        raise ValueError("Unexpected timestamp or zone source type")
    if schema.field(names[0]).type.tz != quality["source_timestamp_timezone"]:
        raise ValueError("Source timezone metadata differs from screening")
    cells: Counter = Counter()
    dispositions: Counter = Counter()
    for batch in source.iter_batches(batch_size=100_000, columns=list(names)):
        local_cells, local_dispositions = aggregate_batch(batch.to_pandas(), nyc, set(lookup))
        cells.update(local_cells)
        dispositions.update(local_dispositions)
    if dict(dispositions) != exclusions["exclusive_row_dispositions"]:
        raise ValueError("Current scan does not reproduce the exclusion dispositions")
    if sum(dispositions.values()) != source.metadata.num_rows:
        raise ValueError("Scanned row count differs from metadata")
    table = complete_grid(cells, nyc)
    expected_rows = len(nyc) * 720
    expected_total = exclusions["counts"]["accepted_for_april_nyc_screening"]
    if (len(table) != expected_rows or table.duplicated(["pickup_zone_id", "hour_start"]).any()
            or table.isna().any().any() or (table["pickup_count"] < 0).any()
            or int(table["pickup_count"].sum()) != expected_total):
        raise ValueError("Zone-hour validation or count reconciliation failed")
    report = {
        "status": "VALIDATED", "inputs": inputs,
        "manifest_sha256": sha256(manifest_path),
        "quality_report_sha256": sha256(quality_path),
        "exclusions_report_sha256": sha256(exclusions_path),
        "script_sha256": sha256(Path(__file__)),
        "shared_validation_script_sha256": sha256(ROOT / "scripts/assess_april_quality.py"),
        "environment": {"python": platform.python_version(),
                        "pandas": version("pandas"), "pyarrow": version("pyarrow")},
        "configuration": {"start_inclusive": START.isoformat(), "end_exclusive": END.isoformat(),
                          "timezone_assumption": TZ, "batch_size": 100_000},
        "zones": len(nyc), "hours_per_zone": 720, "rows": len(table),
        "accepted_pickups": expected_total, "exclusive_dispositions": dict(dispositions),
        "zero_observed_zone_hours": int(table["pickup_count"].eq(0).sum()),
        "count_reconciliation_passed": True,
        "limitations": ["Timezone semantics remain an explicit D05 assumption.",
                        "Zeros mean no accepted records observed after preliminary coverage checks; completeness is not proven.",
                        "Counts represent recorded served pickups, not unmet demand.",
                        "No deduplication, feature engineering, or train/test splitting performed."],
    }
    return table, report


def main() -> int:
    """Build and persist a new prepared snapshot plus aggregate validation report.

    Output:
        int: 0 on success, 1 on a caught error; argparse handles CLI errors.
        Writes ignored Parquet data and a versionable JSON report in unique run
        folders. Validates the Parquet round-trip before reporting success.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality-report", default=QUALITY)
    parser.add_argument("--exclusions-report", default=EXCLUSIONS)
    args = parser.parse_args()
    try:
        print("Verifying reports and building April zone-hour counts...", flush=True)
        table, report = build(project_path(args.quality_report), project_path(args.exclusions_report))
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output = ROOT / "data/processed/april_2025" / run_id
        reports = ROOT / "reports/data_preparation/april_2025" / run_id
        output.mkdir(parents=True, exist_ok=False)
        dataset = output / "zone_hour_demand.parquet"
        table.to_parquet(dataset, index=False, compression="zstd")
        pd.testing.assert_frame_equal(table, pd.read_parquet(dataset))
        report.update({"run_at_utc": datetime.now(timezone.utc).isoformat(),
                       "dataset_path": str(dataset.relative_to(ROOT)),
                       "dataset_sha256": sha256(dataset), "parquet_round_trip_passed": True})
        reports.mkdir(parents=True, exist_ok=False)
        (reports / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("Status: VALIDATED")
        print(f"Zones: {report['zones']}")
        print("Hours per zone: 720")
        print(f"Zone-hour rows: {report['rows']:,}")
        print(f"Accepted pickups: {report['accepted_pickups']:,}")
        print("Unique keys, integer counts, reconciliation, Parquet round-trip: PASS")
        print(f"Prepared data: {dataset}")
        print(f"Validation report: {reports / 'report.json'}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}\nBuild incomplete; do not use partial output as validated data.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
