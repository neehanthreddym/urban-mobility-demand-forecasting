#!/usr/bin/env python3
"""Screen an approved yellow-taxi month using the established April quality rules.

Run: uv run --locked python scripts/assess_month_quality.py --month 2025-04
Exit codes: 0 = preliminary pass, 2 = review required, 1 = input/run failure.
No raw data, prior reports, model features, or train/test splits are modified.
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
    pickup_time_type, project_path, read_lookup, sha256, verify_input,
    SUPPORTED_MONTHS, TZ, month_bounds, verify_snapshots,
)


def assess_month(month: str, trips: Path, lookup_path: Path, manifest: Path) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """Screen one month in batches; return diagnostics and hourly/daily counts.

    Verify input integrity and count reconciliation without modifying source data.
    Interpret naive timestamps as NYC wall time for screening only; flag quality
    thresholds and possible coverage gaps without asserting source completeness.

    Args:
        month: Calendar month in YYYY-MM format; clock-change months are rejected.
        trips: Yellow-taxi Parquet file for the requested month.
        lookup_path: Taxi-zone reference CSV.
        manifest: JSON manifest containing the expected input sizes and hashes.

    Output:
        tuple[dict, pd.DataFrame, pd.DataFrame]: Diagnostic report, hourly counts
        with coverage flags, and daily counts; no files are written here.

    Raises:
        ValueError: Input integrity, reference/schema checks, or reconciliation
        fails, or the trip file contains no rows.
    """
    start, end = month_bounds(month)
    entries = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    inputs = [verify_input(path, entries) for path in (trips, lookup_path)]
    trip_entry = next(item for item in entries if project_path(item["path"]).resolve() == trips.resolve())
    if trip_entry.get("study_month") != month:
        raise ValueError("Trip manifest study_month must match the requested month")
    lookup, nyc = read_lookup(lookup_path)
    parquet = pq.ParquetFile(trips)
    schema = parquet.schema_arrow
    time_type = pickup_time_type(schema)

    counts, dispositions, hours, zones, minimum, maximum = screen_batches(parquet, lookup, nyc, start, end)
    total = counts["total_rows"]
    hourly, daily = hourly_coverage(hours, start, end)
    key_percent = 100 * counts["combined_key_quality_failures"] / total
    outside_percent = 100 * counts["out_of_month_timestamp"] / total
    zero_hours = int(hourly["zero_observed_records"].sum())
    low_hours = int(hourly["unusually_low_review_flag"].sum())
    reasons = []
    if key_percent > THRESHOLD_PERCENT:
        reasons.append("Combined missing/invalid timestamp or missing/unmapped zone exceeds 1% of all rows")
    if outside_percent > THRESHOLD_PERCENT:
        reasons.append("Out-of-month timestamp count exceeds 1% of all rows")
    if zero_hours:
        reasons.append(f"{zero_hours} {month} hours have zero observed accepted records; investigate coverage")
    if low_hours:
        reasons.append(f"{low_hours} hours fall below 10% of the same-clock-hour monthly median; inspect possible gaps")
    status = "REVIEW_REQUIRED" if reasons else "PASS_PRELIMINARY"
    report = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status, "review_reasons": reasons,
        "scope": f"{month} recorded NYC yellow-taxi pickups; preliminary screening only",
        "month": month,
        "configuration": {"start_inclusive": start.isoformat(), "end_exclusive": end.isoformat(),
                          "timezone_assumption": TZ, "batch_size": 100_000,
                          "review_threshold_percent": THRESHOLD_PERCENT},
        "inputs": inputs, "manifest_sha256": sha256(manifest),
        "script_sha256": sha256(Path(__file__)),
        "shared_validation_script_sha256": sha256(UTILS_PATH),
        "environment": {"python": platform.python_version(), "pandas": version("pandas"), "pyarrow": version("pyarrow")},
        "source_schema": str(schema), "source_timestamp_timezone": time_type.tz,
        "timestamp_interpretation": "America/New_York; naive-source semantics require external validation",
        "observed_pickup_min": str(minimum), "observed_pickup_max": str(maximum),
        "counts": dict(counts), "exclusive_row_dispositions": dict(dispositions),
        "percent_of_all_rows": {"combined_key_quality_failures": key_percent, "out_of_month_timestamp": outside_percent},
        "lookup": {"unique_ids": len(lookup), "in_scope_nyc_ids": len(nyc),
                   "duplicate_ids": 0,
                   "zones_with_zero_accepted_records": sorted(nyc - set(zones))},
        "hourly_coverage": {"expected_month_hours": len(hourly),
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


def compare_april(report: dict, baseline: dict) -> None:
    """Require numerical parity with the preserved legacy April screening.

    Args:
        report: Monthly checker result for April 2025.
        baseline: Original April quality report dictionary.

    Output:
        None on successful snapshot/count/coverage comparison.

    Raises:
        ValueError: Snapshot identities or checked results differ.
    """
    if report["month"] != "2025-04":
        raise ValueError("Legacy April comparison is valid only for --month 2025-04")
    verify_snapshots(report["inputs"], baseline["inputs"])
    count_names = {
        "out_of_april_timestamp": "out_of_month_timestamp",
        "in_april_mapped_non_nyc_scope_exclusions": "in_month_mapped_non_nyc_scope_exclusions",
        "accepted_for_april_nyc_screening": "accepted_for_month_nyc_screening",
    }
    expected_counts = {count_names.get(key, key): value for key, value in baseline["counts"].items()}
    disposition_names = {
        "out_of_april_after_key_checks": "out_of_month_after_key_checks",
        "mapped_non_nyc_in_april": "mapped_non_nyc_in_month",
    }
    expected_dispositions = {disposition_names.get(key, key): value
                             for key, value in baseline["exclusive_row_dispositions"].items()}
    expected_coverage = {
        ("expected_month_hours" if key == "expected_april_hours" else key): value
        for key, value in baseline["hourly_coverage"].items()
    }
    comparisons = {
        "counts": (report["counts"], expected_counts),
        "exclusive dispositions": (report["exclusive_row_dispositions"], expected_dispositions),
        "coverage": (report["hourly_coverage"], expected_coverage),
    }
    for name in ("status", "lookup", "source_schema", "source_timestamp_timezone",
                 "observed_pickup_min", "observed_pickup_max", "reconciliation_passed"):
        comparisons[name] = (report[name], baseline[name])
    for name, (actual, expected) in comparisons.items():
        if actual != expected:
            raise ValueError(f"Legacy April regression mismatch: {name}")


def markdown(report: dict) -> str:
    """Format the month's screening findings and limitations for review.

    Args:
        report: Diagnostic dictionary returned by assess_month().

    Output:
        str: Markdown report; does not write files.
    """
    lines = [f"# {report['month']} Preliminary Data-Quality Report", "",
             f"Status: **{report['status']}**", "", f"Run (UTC): {report['run_at_utc']}", "",
             "## Counts", "", "| Check | Rows |", "|---|---:|"]
    lines.extend(f"| {key} | {value:,} |" for key, value in report["counts"].items())
    lines += ["", "Diagnostic counts can overlap; exclusive dispositions are in report.json.",
              "", "## Review thresholds", ""]
    lines.extend(f"- {key}: {value:.6f}% (review if greater than 1%)."
                 for key, value in report["percent_of_all_rows"].items())
    lines += ["", "## Coverage", "",
              f"- Expected hours: {report['hourly_coverage']['expected_month_hours']}",
              f"- Zero-observed hours: {report['hourly_coverage']['zero_observed_hours']}",
              f"- Unusually-low hours: {report['hourly_coverage']['unusually_low_hours']}",
              "", "## Review reasons", ""]
    lines.extend(f"- {reason}" for reason in report["review_reasons"])
    if not report["review_reasons"]:
        lines.append("No automatic review flags; source completeness is not proven.")
    if report.get("april_regression"):
        lines += ["", f"Legacy April comparison: {report['april_regression']['status']}"]
    lines += ["", "## Limitations", ""]
    lines.extend(f"- {item}" for item in report["limitations"])
    lines += ["", "Coverage flags are quality diagnostics, not causal findings or modeling features.",
              "For June, do not use final-test-period patterns to change features, thresholds, or model choices.",
              "Do not silently amend exclusion rules in response to these diagnostics.", ""]
    return "\n".join(lines)


def main() -> int:
    """Screen a month and save a unique aggregate report bundle.

    Output:
        int: 0 for preliminary pass, 2 for review flags, 1 for a caught error.
        Writes JSON, Markdown, and hourly/daily diagnostic CSVs; argparse
        handles invalid command-line options. Original files remain unchanged.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, choices=SUPPORTED_MONTHS)
    parser.add_argument("--manifest", default="data/manifest.json")
    parser.add_argument("--lookup", default="data/reference/taxi_zone_lookup.csv")
    parser.add_argument("--compare-april-report", help="Original April report JSON; valid only for April")
    args = parser.parse_args()
    try:
        if args.compare_april_report and args.month != "2025-04":
            raise ValueError("Use --compare-april-report only with April")
        trips = ROOT / f"data/raw/yellow_tripdata_{args.month}.parquet"
        print(f"Verifying manifest and screening {args.month} in batches...", flush=True)
        report, hourly, daily = assess_month(
            args.month, trips, project_path(args.lookup), project_path(args.manifest)
        )
        if args.compare_april_report:
            baseline_path = project_path(args.compare_april_report)
            compare_april(report, json.loads(baseline_path.read_text(encoding="utf-8")))
            report["april_regression"] = {
                "status": "PASS", "baseline_path": str(baseline_path),
                "baseline_sha256": sha256(baseline_path),
            }
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output = ROOT / "reports/data_quality/monthly" / args.month / run_id
        output.mkdir(parents=True, exist_ok=False)
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (output / "report.md").write_text(markdown(report), encoding="utf-8")
        hourly.to_csv(output / "hourly_counts.csv")
        daily.to_csv(output / "daily_counts.csv")
        print(f"Status: {report['status']}")
        print(f"Rows scanned: {report['counts']['total_rows']:,}")
        for key, value in report["percent_of_all_rows"].items():
            print(f"{key}: {value:.6f}% (review if >1%)")
        for key in ("expected_month_hours", "zero_observed_hours", "unusually_low_hours"):
            print(f"{key}: {report['hourly_coverage'][key]}")
        print(f"Accepted records: {report['counts']['accepted_for_month_nyc_screening']:,}")
        print("Count reconciliation: PASS")
        if args.compare_april_report:
            print("Legacy April comparison: PASS")
        for reason in report["review_reasons"]:
            print(f"REVIEW: {reason}")
        print(f"Reports saved to: {output}")
        print("Raw files unchanged. Timezone and completeness limitations remain.")
        return 2 if report["status"] == "REVIEW_REQUIRED" else 0
    except Exception as exc:
        print(f"ERROR: {exc}\nScreening incomplete; do not treat partial outputs as a pass.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
