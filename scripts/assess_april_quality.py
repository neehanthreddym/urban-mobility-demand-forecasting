#!/usr/bin/env python3
"""Read-only April 2025 screening; write aggregate diagnostics, never cleaned data.

Run from the project root with:
    uv run --locked python scripts/assess_april_quality.py

Exit codes: 0 = preliminary checks pass, 2 = review required, 1 = input/run error.
This script does not establish source completeness or validate source timezone semantics.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from utils import (
    UTILS_PATH, ROOT, THRESHOLD_PERCENT, hourly_coverage, screen_batches,
    pickup_time_type, project_path, read_lookup, sha256, verify_input, april_keys,
)

START = pd.Timestamp("2025-04-01")
END = pd.Timestamp("2025-05-01")


def assess(trips: Path, lookup_path: Path, manifest: Path) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """Screen April pickups in batches; return diagnostics and hourly/daily counts.

    Verify input integrity and count reconciliation without modifying source data.
    Interpret naive timestamps as NYC wall time for screening only; flag quality
    thresholds and possible coverage gaps without asserting source completeness.

    Args:
        trips: April 2025 yellow-taxi Parquet file.
        lookup_path: Taxi-zone reference CSV.
        manifest: JSON manifest containing the expected input sizes and hashes.

    Output:
        tuple[dict, pd.DataFrame, pd.DataFrame]: Diagnostic report, hourly counts
        with coverage flags, and daily counts; no files are written here.

    Raises:
        ValueError: Input integrity, reference/schema checks, or reconciliation
        fails, or the trip file contains no rows.
    """
    entries = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    inputs = [verify_input(path, entries) for path in (trips, lookup_path)]
    lookup, nyc = read_lookup(lookup_path)
    parquet = pq.ParquetFile(trips)
    schema = parquet.schema_arrow
    time_type = pickup_time_type(schema)

    counts, dispositions, hours, zones, minimum, maximum = screen_batches(parquet, lookup, nyc, START, END)
    counts = april_keys(counts)
    dispositions = april_keys(dispositions)
    total = counts["total_rows"]
    hourly, daily = hourly_coverage(hours, START, END)
    key_percent = 100 * counts["combined_key_quality_failures"] / total
    outside_percent = 100 * counts["out_of_april_timestamp"] / total
    zero_hours = int(hourly["zero_observed_records"].sum())
    low_hours = int(hourly["unusually_low_review_flag"].sum())
    reasons = []
    if key_percent > THRESHOLD_PERCENT:
        reasons.append("Combined missing/invalid timestamp or missing/unmapped zone exceeds 1% of all rows")
    if outside_percent > THRESHOLD_PERCENT:
        reasons.append("Out-of-April timestamp count exceeds 1% of all rows")
    if zero_hours:
        reasons.append(f"{zero_hours} April hours have zero observed accepted records; investigate coverage")
    if low_hours:
        reasons.append(f"{low_hours} hours fall below 10% of the same-clock-hour monthly median; inspect possible gaps")
    status = "REVIEW_REQUIRED" if reasons else "PASS_PRELIMINARY"
    report = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status, "review_reasons": reasons,
        "scope": "April 2025 recorded NYC yellow-taxi pickups; preliminary screening only",
        "inputs": inputs, "manifest_sha256": sha256(manifest),
        "script_sha256": sha256(Path(__file__)),
        "shared_validation_script_sha256": sha256(UTILS_PATH),
        "environment": {"python": platform.python_version(), "pandas": version("pandas"), "pyarrow": version("pyarrow")},
        "source_schema": str(schema), "source_timestamp_timezone": time_type.tz,
        "timestamp_interpretation": "America/New_York; naive-source semantics require external validation",
        "observed_pickup_min": str(minimum), "observed_pickup_max": str(maximum),
        "counts": dict(counts), "exclusive_row_dispositions": dict(dispositions),
        "percent_of_all_rows": {"combined_key_quality_failures": key_percent, "out_of_april_timestamp": outside_percent},
        "lookup": {"unique_ids": len(lookup), "in_scope_nyc_ids": len(nyc),
                   "duplicate_ids": 0,
                   "zones_with_zero_accepted_records": sorted(nyc - set(zones))},
        "hourly_coverage": {"expected_april_hours": len(hourly),
                            "zero_observed_hours": zero_hours,
                            "unusually_low_hours": low_hours,
                            "low_count_heuristic_fraction": 0.1},
        "reconciliation_passed": True,
        "limitations": [
            "Nonzero counts cannot prove complete vendor submissions or absence of outages.",
            "Hourly zero values describe observed accepted records, not imputed model targets.",
            "Low-count flags use full-month data for quality diagnostics only; not forecasting features.",
            "No raw rows are removed, corrected, deduplicated, or saved by this script.",
            "Full-row duplicates and unrelated fare/distance/duration anomalies are not assessed.",
            "No zone-hour modeling table is produced; this is not final three-month data acceptance.",
            "Naive timestamp timezone semantics still require source evidence before modeling.",
        ],
    }
    return report, hourly, daily


def markdown(report: dict) -> str:
    """Format assessment counts, review flags, and limitations as Markdown.

    Args:
        report: Diagnostic dictionary returned by assess().

    Output:
        str: Human-readable Markdown report; no file is written here.
    """
    lines = ["# April 2025 Preliminary Data-Quality Report", "",
             f"Status: **{report['status']}**", "",
             f"Run (UTC): {report['run_at_utc']}", "",
             "## Counts", "", "| Check | Rows |", "|---|---:|"]
    lines.extend(f"| {name} | {count:,} |" for name, count in report["counts"].items())
    lines += ["", "Diagnostic counts can overlap. Exclusive dispositions are in report.json.",
              "", "## Thresholds", ""]
    for name, percentage in report["percent_of_all_rows"].items():
        lines.append(f"- {name}: {percentage:.6f}% (review when greater than 1%).")
    lines += ["", "## Review reasons", ""]
    lines.extend(f"- {reason}" for reason in report["review_reasons"])
    if not report["review_reasons"]:
        lines.append("No automatic review flags. This is not proof of source completeness.")
    lines += ["", "## Limitations", ""]
    lines.extend(f"- {limitation}" for limitation in report["limitations"])
    lines += ["", "See hourly_counts.csv for every April hour and its review flags;",
              "daily_counts.csv for day totals; report.json for schema, provenance, and exact counts.", ""]
    return "\n".join(lines)


def main() -> int:
    """Run the CLI and save a unique report bundle while preserving input files.

    Output:
        int: Assessment exit code: 0 for a preliminary pass, 2 for review flags,
        or 1 for a caught input/run error. Argument parsing uses argparse exits.
        Prints a summary and, on completed assessment, writes report.json,
        report.md, hourly_counts.csv, and daily_counts.csv to a new run folder.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trips", default="data/raw/yellow_tripdata_2025-04.parquet")
    parser.add_argument("--lookup", default="data/reference/taxi_zone_lookup.csv")
    parser.add_argument("--manifest", default="data/manifest.json")
    parser.add_argument("--output-root", default="reports/data_quality/april_2025")
    args = parser.parse_args()
    try:
        trips, lookup, manifest = (project_path(value) for value in
                                   (args.trips, args.lookup, args.manifest))
        for path in (trips, lookup, manifest):
            if not path.is_file():
                raise ValueError(f"Input file not found: {path}")
        print("Verifying manifest and scanning April in batches...", flush=True)
        report, hourly, daily = assess(trips, lookup, manifest)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output = project_path(args.output_root) / run_id
        # Refuse paths inside immutable input directories, even with --output-root.
        for input_directory in (trips.parent.resolve(), lookup.parent.resolve()):
            if output.resolve().is_relative_to(input_directory):
                raise ValueError("Report output must not be inside a raw/reference input directory")
        output.mkdir(parents=True, exist_ok=False)
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (output / "report.md").write_text(markdown(report), encoding="utf-8")
        hourly.to_csv(output / "hourly_counts.csv")
        daily.to_csv(output / "daily_counts.csv")
        print(f"Status: {report['status']}")
        print(f"Rows scanned: {report['counts']['total_rows']:,}")
        for name, percentage in report["percent_of_all_rows"].items():
            print(f"{name}: {percentage:.6f}% (review if >1%)")
        coverage = report["hourly_coverage"]
        print(f"April hours checked: {coverage['expected_april_hours']}")
        print(f"Zero-observed hours: {coverage['zero_observed_hours']}")
        print(f"Unusually-low hours: {coverage['unusually_low_hours']}")
        print("Count reconciliation: PASS")
        for reason in report["review_reasons"]:
            print(f"REVIEW: {reason}")
        print(f"Reports saved to: {output}")
        print("Raw files unchanged. Source completeness and timezone still require validation.")
        return 2 if report["status"] == "REVIEW_REQUIRED" else 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Assessment incomplete; do not treat this run as a quality pass.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
