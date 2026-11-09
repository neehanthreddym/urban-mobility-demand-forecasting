#!/usr/bin/env python3
"""Reconcile monthly date and geographic exclusions against a pinned quality report."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from utils import (
    UTILS_PATH, BOROUGHS, PICKUP_COLUMNS, ROOT, SUPPORTED_MONTHS, april_keys, classify_pickups,
    month_bounds, pickup_time_type, project_path, read_lookup, sha256, verify_input,
    verify_snapshots,
)


def load_reference(path: Path) -> tuple[dict[int, dict[str, str]], set[int]]:
    """Load validated lookup labels for interpreting exclusion categories.

    Args:
        path: Taxi-zone lookup CSV used in the original quality assessment.

    Output:
        tuple: ID-to-label records and the set of in-scope NYC zone IDs.

    Raises:
        ValueError: Lookup keys, required labels, or NYC membership are invalid.
    """
    _, nyc = read_lookup(path)
    with path.open(newline="", encoding="utf-8-sig") as stream:
        records = {
            int(row["LocationID"]): {
                "borough": row["Borough"].strip(),
                "zone": row["Zone"].strip(),
                "service_zone": (row.get("service_zone") or "").strip(),
            }
            for row in csv.DictReader(stream)
        }
    return records, nyc


def classify_geography(record: dict[str, str]) -> str:
    """Classify reference labels conservatively, without inferring coordinates.

    Args:
        record: Lookup borough and zone labels for a mapped pickup ID.

    Output:
        str: in_scope_nyc, known_outside_nyc, unknown_or_unspecified, or
        unresolved_reference. Unknown labels never establish physical location.
    """
    borough, zone = record["borough"], record["zone"]
    if borough in BOROUGHS:
        return "in_scope_nyc"
    # Explicit reference-label rule, not an ID guessed from the trip distribution.
    if (borough.casefold(), zone.casefold()) == ("ewr", "newark airport"):
        return "known_outside_nyc"
    unknown = {"", "unknown", "n/a", "na", "unspecified", "not available"}
    if borough.casefold() in unknown or zone.casefold() in unknown:
        return "unknown_or_unspecified"
    return "unresolved_reference"


def inspect(baseline_path: Path, month: str, *, legacy: bool = False) -> tuple[dict, list[dict], list[dict]]:
    """Scan the original snapshot and reconcile exclusion detail to its report.

    Args:
        baseline_path: JSON report from the completed quality screening.
        month: Requested study month in YYYY-MM format.
        legacy: Read and emit the original April field names for its historical CLI.

    Output:
        tuple: Aggregate inspection report, minimal date-exclusion excerpts,
        and geographic counts grouped by lookup ID/labels/classification.

    Raises:
        ValueError: Input snapshots/schema differ, counts fail reconciliation,
        or results disagree with the supplied baseline report.
    """
    start, end = month_bounds(month)
    manifest_path = ROOT / "data/manifest.json"
    trips = ROOT / f"data/raw/yellow_tripdata_{month}.parquet"
    lookup_path = ROOT / "data/reference/taxi_zone_lookup.csv"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    inputs = [verify_input(path, manifest["files"]) for path in (trips, lookup_path)]
    if legacy:
        if month != "2025-04" or "month" in baseline:
            raise ValueError("Legacy mode requires the original April quality report")
    else:
        if baseline.get("month") != month:
            raise ValueError("Requested month differs from the quality report")
        if baseline["status"] != "PASS_PRELIMINARY" or not baseline["reconciliation_passed"]:
            raise ValueError("Resolve outstanding quality-screening flags before inspection")
        entry = next(item for item in manifest["files"] if project_path(item["path"]).resolve() == trips.resolve())
        if entry.get("study_month") != month:
            raise ValueError("Requested month differs from the trip manifest")
    verify_snapshots(inputs, baseline["inputs"])
    records, nyc = load_reference(lookup_path)
    parquet = pq.ParquetFile(trips)
    required = PICKUP_COLUMNS
    time_type = pickup_time_type(parquet.schema_arrow)
    if time_type.tz != baseline["source_timestamp_timezone"]:
        raise ValueError("Source timezone metadata differs from the baseline")

    counts: Counter = Counter()
    dispositions: Counter = Counter()
    before, after = ("before_april", "on_or_after_may") if legacy else ("before_month", "on_or_after_next_month")
    directions = Counter({before: 0, after: 0})
    date_key = "out_of_april_timestamp" if legacy else "out_of_month_timestamp"
    geographic: Counter = Counter()
    excerpts: list[dict] = []
    row_offset = 0
    for batch in parquet.iter_batches(batch_size=100_000, columns=list(required)):
        frame = batch.to_pandas().reset_index(drop=True)
        original = frame[required[0]]
        pickup, zone, masks, exclusive = classify_pickups(frame, records, nyc, start, end)
        outside_month = masks["out_of_month_timestamp"]
        geo_mask = exclusive["mapped_non_nyc_in_month"]
        counts["total_rows"] += len(frame)
        counts.update({name: int(mask.sum()) for name, mask in masks.items()})
        dispositions.update({name: int(mask.sum()) for name, mask in exclusive.items()})
        geographic.update({int(key): int(value) for key, value in zone[geo_mask].value_counts().items()})
        for index in frame.index[outside_month]:
            zone_id = None if pd.isna(zone.loc[index]) else int(zone.loc[index])
            reference = records.get(zone_id, {})
            direction = before if pickup.loc[index] < start else after
            directions[direction] += 1
            excerpts.append({
                # Derived row number: one-based physical scan order, NOT a trip ID.
                "source_row_number": row_offset + int(index) + 1,
                "pickup_datetime_recorded": original.loc[index].isoformat(),
                "pickup_datetime_assumed_nyc_local": pickup.loc[index].isoformat(),
                "pickup_zone_id": zone_id,
                "borough": reference.get("borough", ""),
                "zone": reference.get("zone", ""),
                "date_exclusion_reason": direction,
            })
            if len(excerpts) > baseline["counts"][date_key]:
                raise ValueError("More date exclusions than baseline; aborting rather than accumulating excerpts")
        row_offset += len(frame)

    if counts["total_rows"] != parquet.metadata.num_rows:
        raise ValueError("Scanned row count differs from Parquet metadata")
    if sum(dispositions.values()) != counts["total_rows"]:
        raise ValueError("Exclusive dispositions do not reconcile to source rows")
    if legacy:
        counts = april_keys(counts)
        dispositions = april_keys(dispositions)
    for name, value in counts.items():
        if value != baseline["counts"][name]:
            raise ValueError(f"Baseline count mismatch for {name}: {value} vs {baseline['counts'][name]}")
    if dict(dispositions) != baseline["exclusive_row_dispositions"]:
        raise ValueError("Exclusive dispositions differ from baseline")
    if sum(directions.values()) != counts[date_key]:
        raise ValueError("Date categories do not reconcile")

    groups = []
    totals = Counter({"known_outside_nyc": 0, "unknown_or_unspecified": 0,
                      "unresolved_reference": 0})
    for zone_id, count in sorted(geographic.items()):
        reference = records[zone_id]
        category = classify_geography(reference)
        if category == "in_scope_nyc":
            raise ValueError("An in-scope zone entered the geographic exclusions")
        totals[category] += count
        groups.append({"pickup_zone_id": zone_id, **reference,
                       "classification": category, "record_count": count})
    if sum(totals.values()) != dispositions["mapped_non_nyc_in_april" if legacy else "mapped_non_nyc_in_month"]:
        raise ValueError("Geographic categories do not reconcile")
    status = "REVIEW_REQUIRED" if totals["unresolved_reference"] else "RECONCILED"
    report = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "inputs": inputs,
        "manifest_sha256": sha256(manifest_path),
        "baseline_report": {"path": str(baseline_path.resolve()), "sha256": sha256(baseline_path)},
        "script_sha256": sha256(Path(__file__)),
        "shared_validation_script_sha256": sha256(UTILS_PATH),
        "environment": {"python": platform.python_version(),
                        "pandas": version("pandas"), "pyarrow": version("pyarrow")},
        "counts": dict(counts), "exclusive_row_dispositions": dict(dispositions),
        "date_exclusions_by_direction": dict(directions),
        "geographic_classification_totals": dict(totals),
        "baseline_counts_match": True, "reconciliation_passed": True,
        "timestamp_assumption": "Recorded clock values interpreted as America/New_York under D05; source DST semantics unverified",
        "treatment": "Retain exclusion rules for the monthly NYC target; preserve original files and historical screening report",
        "limitations": [
            "Geographic classification interprets lookup labels, not independently verified trip coordinates.",
            "Unknown/unspecified categories do not establish that pickups occurred outside NYC.",
            "Date and geography are disjoint in the exclusive dispositions; diagnostic key failures can overlap.",
            "Derived source_row_number is physical scan position, not an official unique trip identifier.",
            "No date correction, timezone shift, deduplication, or modeling table is performed.",
            "RECONCILED establishes accounting/classification only, not overall source completeness.",
        ],
    }
    if not legacy:
        report["month"] = month
    return report, excerpts, groups


def write_outputs(report: dict, excerpts: list[dict], groups: list[dict]) -> tuple[Path, Path]:
    """Save aggregate reports separately from ignored row-level date excerpts.

    Args:
        report: Reconciled diagnostic summary and provenance.
        excerpts: Minimal out-of-month records, intended for local inspection.
        groups: Aggregate geographic exclusion counts by lookup ID and labels.

    Output:
        tuple[Path, Path]: Unique public-report and private-excerpt directories.
        Writes JSON/Markdown/aggregate CSVs and a local-only row-level CSV.
    """
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    month = report.get("month")
    folder = Path("monthly_exclusions") / month if month else Path("april_2025_exclusions")
    excerpt_name = "out_of_month_records.csv" if month else "out_of_april_records.csv"
    public = ROOT / "reports/data_quality" / folder / run_id
    private = ROOT / "data/interim" / folder / run_id
    public.mkdir(parents=True, exist_ok=False)
    private.mkdir(parents=True, exist_ok=False)
    report["local_date_excerpt_path"] = str((private / excerpt_name).relative_to(ROOT))
    geo_columns = ["pickup_zone_id", "borough", "zone", "service_zone", "classification", "record_count"]
    with (public / "geographic_exclusions.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=geo_columns)
        writer.writeheader()
        writer.writerows(groups)
    with (public / "date_exclusions_summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["date_exclusion_reason", "record_count"])
        writer.writerows(report["date_exclusions_by_direction"].items())
    excerpt_columns = ["source_row_number", "pickup_datetime_recorded", "pickup_datetime_assumed_nyc_local",
                       "pickup_zone_id", "borough", "zone", "date_exclusion_reason"]
    with (private / excerpt_name).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=excerpt_columns)
        writer.writeheader()
        writer.writerows(excerpts)
    lines = [f"# {month or 'April 2025'} Exclusion Inspection", "", f"Status: **{report['status']}**", "",
             "Input identities, diagnostic counts, and exclusive dispositions match the original report.",
             "", "## Date exclusions", ""]
    lines.extend(f"- {name}: {value:,}" for name, value in report["date_exclusions_by_direction"].items())
    lines += ["", "## Geographic classifications", ""]
    lines.extend(f"- {name}: {value:,}" for name, value in report["geographic_classification_totals"].items())
    lines += ["", "See geographic_exclusions.csv for per-ID labels and counts.",
              "Unknown geography is not evidence that a pickup happened outside NYC.",
              "", "## Exclusive row dispositions", ""]
    lines.extend(f"- {name}: {value:,}" for name, value in report["exclusive_row_dispositions"].items())
    lines += ["", "## Treatment", "", report["treatment"], "",
              "If unresolved_reference is nonzero, inspect those labels before finalizing the classification.",
              "", "Row-level date excerpts are saved separately under ignored data/interim/.",
              "Do not publish those excerpts as part of the aggregate report.",
              "", "## Limitations", ""]
    lines.extend(f"- {item}" for item in report["limitations"])
    (public / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (public / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return public, private


def main(*, legacy: bool = False) -> int:
    """Run the inspection and print output locations.

    Args:
        legacy: Use the original April CLI, report format, and output locations.

    Output:
        int: Zero on reconciliation, two for unresolved labels, one on failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    if legacy:
        parser.add_argument("--baseline-report", default="reports/data_quality/april_2025/20261104T053754311799Z/report.json")
    else:
        parser.add_argument("--month", required=True, choices=SUPPORTED_MONTHS)
        parser.add_argument("--baseline-report", required=True, help="Pinned monthly quality report JSON")
    args = parser.parse_args()
    month = "2025-04" if legacy else args.month
    try:
        print(f"Verifying snapshots and inspecting {month} exclusions...", flush=True)
        report, excerpts, groups = inspect(project_path(args.baseline_report), month, legacy=legacy)
        public, _ = write_outputs(report, excerpts, groups)
        print(f"Status: {report['status']}")
        print(f"Rows scanned: {report['counts']['total_rows']:,}")
        print(f"Out-of-month records: {sum(report['date_exclusions_by_direction'].values()):,}")
        for name, value in report["date_exclusions_by_direction"].items():
            print(f"  {name}: {value:,}")
        print(f"Geographic exclusions: {sum(report['geographic_classification_totals'].values()):,}")
        for name, value in report["geographic_classification_totals"].items():
            print(f"  {name}: {value:,}")
        print(f"Accepted records: {report['exclusive_row_dispositions']['accepted']:,}")
        print("Baseline count comparison: PASS")
        print("Exclusive count reconciliation: PASS")
        print(f"Aggregate reports: {public}")
        print(f"Local-only date excerpts: {ROOT / report['local_date_excerpt_path']}")
        print("Original data and prior reports unchanged. Timezone semantics remain an assumption.")
        return 2 if report["status"] == "REVIEW_REQUIRED" else 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Inspection incomplete; do not treat any partial outputs as reconciled findings.", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())