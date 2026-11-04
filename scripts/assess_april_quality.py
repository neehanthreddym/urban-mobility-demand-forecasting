#!/usr/bin/env python3
"""Read-only April 2025 screening; write aggregate diagnostics, never cleaned data.

Run from the project root with:
    uv run --locked python scripts/assess_april_quality.py

Exit codes: 0 = preliminary checks pass, 2 = review required, 1 = input/run error.
This script does not establish source completeness or validate source timezone semantics.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
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


ROOT = Path(__file__).resolve().parents[1]
BOROUGHS = {"Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"}
START = pd.Timestamp("2025-04-01")
END = pd.Timestamp("2025-05-01")
THRESHOLD_PERCENT = 1.0


def sha256(path: Path) -> str:
    """Fingerprint a file using bounded-memory reads.

    Args:
        path: File to read without modification.

    Output:
        str: SHA-256 hexadecimal digest of the file contents.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_path(value: str) -> Path:
    """Anchor relative paths to the repository root; preserve absolute paths.

    Args:
        value: Relative or absolute filesystem path.

    Output:
        Path: Project-anchored or unchanged absolute path; existence is not checked.
    """
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def verify_input(path: Path, entries: list[dict]) -> dict:
    """Return provenance after matching one manifest entry and verifying size/hash.

    Args:
        path: Local input file to verify.
        entries: Manifest file records containing paths, sizes, hashes, and sources.

    Output:
        dict: Verified path, size, checksum, and recorded source/download metadata.

    Raises:
        ValueError: Manifest match is ambiguous/missing or input size/hash differs.
    """
    matches = [item for item in entries if project_path(item["path"]).resolve() == path.resolve()]
    if len(matches) != 1:
        raise ValueError(f"Expected one manifest entry for {path}; found {len(matches)}")
    item = matches[0]
    size = path.stat().st_size
    digest = sha256(path)
    if size != item["size_bytes"] or digest != item["sha256"]:
        raise ValueError(f"Manifest size/checksum mismatch: {path}. Preserve and investigate the file.")
    return {"path": str(path.resolve()), "size_bytes": size, "sha256": digest,
            "manifest_match": True, "source_url": item["source_url"],
            "download_date": item.get("download_date"),
            "download_date_status": item.get("download_date_status")}


def read_lookup(path: Path) -> tuple[dict[int, str], set[int]]:
    """Validate lookup keys/labels; return ID-to-borough mapping and NYC zone IDs.

    Args:
        path: Taxi-zone lookup CSV with LocationID, Borough, and Zone columns.

    Output:
        tuple[dict[int, str], set[int]]: All ID-to-borough mappings and the subset
        of IDs belonging to NYC's five boroughs.

    Raises:
        ValueError: Required columns/labels are missing, IDs are invalid or
        duplicated, or no usable NYC reference entries exist.
    """
    lookup: dict[int, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"LocationID", "Borough", "Zone"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Lookup lacks required columns: {sorted(required)}")
        for line, row in enumerate(reader, start=2):
            try:
                zone_id = int(row["LocationID"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid lookup LocationID at line {line}") from exc
            if zone_id in lookup:
                raise ValueError(f"Duplicate lookup LocationID: {zone_id}; join would be ambiguous")
            if not row["Borough"] or not row["Zone"]:
                raise ValueError(f"Missing borough/zone label at lookup line {line}")
            lookup[zone_id] = row["Borough"].strip()
    if not lookup:
        raise ValueError("Lookup is empty")
    nyc = {zone_id for zone_id, borough in lookup.items() if borough in BOROUGHS}
    if not nyc:
        raise ValueError("Lookup contains no recognized NYC borough zones")
    return lookup, nyc


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
    required = ("tpep_pickup_datetime", "PULocationID")
    if any(schema.names.count(name) != 1 for name in required):
        raise ValueError("Trip file must contain exactly one pickup timestamp and pickup-zone column")
    time_type = schema.field(required[0]).type
    zone_type = schema.field(required[1]).type
    if not pa.types.is_timestamp(time_type):
        raise ValueError(f"Unexpected timestamp type {time_type}; review schema before parsing")
    if not pa.types.is_integer(zone_type):
        raise ValueError(f"Unexpected zone type {zone_type}; review schema before coercing identifiers")

    counts: Counter = Counter()
    dispositions: Counter = Counter()
    hours: Counter = Counter()
    zones: Counter = Counter()
    minimum = maximum = None
    for batch in parquet.iter_batches(batch_size=100_000, columns=list(required)):
        frame = batch.to_pandas()
        original_time = frame[required[0]]
        # Preserve nullable integer IDs rather than filling missing IDs with a real code.
        zone = frame[required[1]].astype("Int64")
        missing_time = original_time.isna()
        pickup = pd.to_datetime(original_time, errors="coerce")
        if time_type.tz is not None:
            pickup = pickup.dt.tz_convert("America/New_York").dt.tz_localize(None)
        # Naive source timestamps are screened AS NYC wall time, not proven to be so.
        invalid_time = pickup.isna() & ~missing_time
        valid_time = pickup.notna()
        missing_zone = zone.isna()
        unmapped_zone = ~missing_zone & ~zone.isin(lookup)
        bad_zone = missing_zone | unmapped_zone
        bad_time = ~valid_time
        in_month = valid_time & pickup.ge(START) & pickup.lt(END)
        out_of_month = valid_time & ~in_month
        outside_nyc = in_month & ~bad_zone & ~zone.isin(nyc)
        accepted = in_month & zone.isin(nyc)

        masks = {"missing_pickup_timestamp": missing_time,
                 "unparseable_pickup_timestamp": invalid_time,
                 "missing_pickup_zone": missing_zone,
                 "unmapped_pickup_zone": unmapped_zone,
                 "combined_key_quality_failures": bad_time | bad_zone,
                 "out_of_april_timestamp": out_of_month,
                 "in_april_mapped_non_nyc_scope_exclusions": outside_nyc,
                 "accepted_for_april_nyc_screening": accepted}
        counts["total_rows"] += len(frame)
        for name, mask in masks.items():
            counts[name] += int(mask.sum())
        # Exclusive dispositions reconcile to input; the diagnostics above can overlap.
        dispositions["bad_timestamp"] += int(bad_time.sum())
        dispositions["bad_zone_after_timestamp_check"] += int((valid_time & bad_zone).sum())
        dispositions["out_of_april_after_key_checks"] += int((out_of_month & ~bad_zone).sum())
        dispositions["mapped_non_nyc_in_april"] += int(outside_nyc.sum())
        dispositions["accepted"] += int(accepted.sum())
        valid_pickups = pickup[valid_time]
        if not valid_pickups.empty:
            batch_min, batch_max = valid_pickups.min(), valid_pickups.max()
            minimum = batch_min if minimum is None else min(minimum, batch_min)
            maximum = batch_max if maximum is None else max(maximum, batch_max)
        hours.update({key: int(value) for key, value in
                      pickup[accepted].dt.floor("h").value_counts().items()})
        zones.update({int(key): int(value) for key, value in zone[accepted].value_counts().items()})

    total = counts["total_rows"]
    if total == 0:
        raise ValueError("Trip file is empty")
    if total != parquet.metadata.num_rows:
        raise ValueError("Scanned rows do not match Parquet metadata")
    if sum(dispositions.values()) != total:
        raise ValueError("Exclusive row dispositions do not reconcile to source rows")
    if sum(hours.values()) != counts["accepted_for_april_nyc_screening"]:
        raise ValueError("Hourly counts do not reconcile to accepted rows")
    if sum(zones.values()) != sum(hours.values()):
        raise ValueError("Zone totals do not reconcile to hourly totals")

    index = pd.date_range(START, END, freq="h", inclusive="left")
    observed = pd.Series([hours.get(hour, 0) for hour in index], index=index, dtype="int64")
    hourly = observed.rename("observed_accepted_records").to_frame()
    hourly.index.name = "hour_start_assumed_nyc_local"
    reference = observed.groupby(observed.index.hour).transform("median")
    hourly["same_clock_hour_month_median"] = reference
    hourly["zero_observed_records"] = observed.eq(0)
    
    # Diagnostic heuristic, NOT a acceptance threshold or proof of an outage.
    hourly["unusually_low_review_flag"] = observed.gt(0) & observed.lt(0.1 * reference)
    daily = observed.resample("D").sum().rename("observed_accepted_records").to_frame()
    daily.index.name = "date_assumed_nyc_local"
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
        "environment": {"python": platform.python_version(), "pandas": version("pandas"), "pyarrow": version("pyarrow")},
        "source_schema": str(schema), "source_timestamp_timezone": time_type.tz,
        "timestamp_interpretation": "America/New_York; naive-source semantics require external validation",
        "observed_pickup_min": str(minimum), "observed_pickup_max": str(maximum),
        "counts": dict(counts), "exclusive_row_dispositions": dict(dispositions),
        "percent_of_all_rows": {"combined_key_quality_failures": key_percent, "out_of_april_timestamp": outside_percent},
        "lookup": {"unique_ids": len(lookup), "in_scope_nyc_ids": len(nyc),
                   "duplicate_ids": 0,
                   "zones_with_zero_accepted_records": sorted(nyc - set(zones))},
        "hourly_coverage": {"expected_april_hours": len(index),
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
