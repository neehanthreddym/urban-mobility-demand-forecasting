#!/usr/bin/env python3
"""Inspect April date/geographic exclusions without changing source data.

Run: uv run --locked python scripts/inspect_april_exclusions.py
Exit codes: 0 = reconciled/classified, 2 = unresolved reference category,
1 = input, reconciliation, or execution failure.
Aggregate reports are versionable; row-level date excerpts stay in data/interim/.
"""

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
import pyarrow as pa
import pyarrow.parquet as pq

from assess_april_quality import (
    BOROUGHS, END, ROOT, START, project_path, read_lookup, sha256, verify_input,
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


def inspect(baseline_path: Path) -> tuple[dict, list[dict], list[dict]]:
    """Scan the original snapshot and reconcile exclusion detail to its report.

    Args:
        baseline_path: JSON report from the completed April quality screening.

    Output:
        tuple: Aggregate inspection report, minimal date-exclusion excerpts,
        and geographic counts grouped by lookup ID/labels/classification.

    Raises:
        ValueError: Input snapshots/schema differ, counts fail reconciliation,
        or results disagree with the supplied baseline report.
    """
    manifest_path = ROOT / "data/manifest.json"
    trips = ROOT / "data/raw/yellow_tripdata_2025-04.parquet"
    lookup_path = ROOT / "data/reference/taxi_zone_lookup.csv"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    inputs = [verify_input(path, manifest["files"]) for path in (trips, lookup_path)]
    # Compare content identities rather than machine-specific absolute paths.
    for item in inputs:
        matches = [old for old in baseline["inputs"]
                   if Path(old["path"]).name == Path(item["path"]).name]
        if len(matches) != 1 or any(
            matches[0][key] != item[key] for key in ("sha256", "size_bytes")
        ):
            raise ValueError(f"Input differs from baseline snapshot: {item['path']}")
    records, nyc = load_reference(lookup_path)
    parquet = pq.ParquetFile(trips)
    required = ("tpep_pickup_datetime", "PULocationID")
    schema = parquet.schema_arrow
    if any(schema.names.count(name) != 1 for name in required):
        raise ValueError("Required pickup timestamp/zone columns are missing or duplicated")
    time_type = schema.field(required[0]).type
    if not pa.types.is_timestamp(time_type) or not pa.types.is_integer(schema.field(required[1]).type):
        raise ValueError("Unexpected pickup timestamp/zone types; review schema before proceeding")
    if time_type.tz != baseline["source_timestamp_timezone"]:
        raise ValueError("Source timezone metadata differs from the baseline")

    counts: Counter = Counter()
    dispositions: Counter = Counter()
    directions = Counter({"before_april": 0, "on_or_after_may": 0})
    geographic: Counter = Counter()
    excerpts: list[dict] = []
    row_offset = 0
    for batch in parquet.iter_batches(batch_size=100_000, columns=list(required)):
        frame = batch.to_pandas().reset_index(drop=True)
        original = frame[required[0]]
        pickup = pd.to_datetime(original, errors="coerce")
        if time_type.tz is not None:
            pickup = pickup.dt.tz_convert("America/New_York").dt.tz_localize(None)
        zone = frame[required[1]].astype("Int64")
        valid_time = pickup.notna()
        missing_zone = zone.isna()
        unmapped = ~missing_zone & ~zone.isin(records)
        bad_zone = missing_zone | unmapped
        in_month = valid_time & pickup.ge(START) & pickup.lt(END)
        outside_month = valid_time & ~in_month
        geo_mask = in_month & ~bad_zone & ~zone.isin(nyc)
        accepted = in_month & zone.isin(nyc)

        masks = {
            "missing_pickup_timestamp": original.isna(),
            "unparseable_pickup_timestamp": pickup.isna() & original.notna(),
            "missing_pickup_zone": missing_zone,
            "unmapped_pickup_zone": unmapped,
            "combined_key_quality_failures": ~valid_time | bad_zone,
            "out_of_april_timestamp": outside_month,
            "in_april_mapped_non_nyc_scope_exclusions": geo_mask,
            "accepted_for_april_nyc_screening": accepted,
        }
        counts["total_rows"] += len(frame)
        for name, mask in masks.items():
            counts[name] += int(mask.sum())
        dispositions["bad_timestamp"] += int((~valid_time).sum())
        dispositions["bad_zone_after_timestamp_check"] += int((valid_time & bad_zone).sum())
        dispositions["out_of_april_after_key_checks"] += int((outside_month & ~bad_zone).sum())
        dispositions["mapped_non_nyc_in_april"] += int(geo_mask.sum())
        dispositions["accepted"] += int(accepted.sum())
        geographic.update({int(key): int(value) for key, value in zone[geo_mask].value_counts().items()})
        for index in frame.index[outside_month]:
            zone_id = None if pd.isna(zone.loc[index]) else int(zone.loc[index])
            reference = records.get(zone_id, {})
            direction = "before_april" if pickup.loc[index] < START else "on_or_after_may"
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
            if len(excerpts) > baseline["counts"]["out_of_april_timestamp"]:
                raise ValueError("More date exclusions than baseline; aborting rather than accumulating excerpts")
        row_offset += len(frame)

    if counts["total_rows"] != parquet.metadata.num_rows:
        raise ValueError("Scanned row count differs from Parquet metadata")
    if sum(dispositions.values()) != counts["total_rows"]:
        raise ValueError("Exclusive dispositions do not reconcile to source rows")
    for name, value in counts.items():
        if value != baseline["counts"][name]:
            raise ValueError(f"Baseline count mismatch for {name}: {value} vs {baseline['counts'][name]}")
    if dict(dispositions) != baseline["exclusive_row_dispositions"]:
        raise ValueError("Exclusive dispositions differ from baseline")
    if sum(directions.values()) != counts["out_of_april_timestamp"]:
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
    if sum(totals.values()) != counts["in_april_mapped_non_nyc_scope_exclusions"]:
        raise ValueError("Geographic categories do not reconcile")
    status = "REVIEW_REQUIRED" if totals["unresolved_reference"] else "RECONCILED"
    report = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "inputs": inputs,
        "manifest_sha256": sha256(manifest_path),
        "baseline_report": {"path": str(baseline_path.resolve()), "sha256": sha256(baseline_path)},
        "script_sha256": sha256(Path(__file__)),
        "shared_validation_script_sha256": sha256(ROOT / "scripts/assess_april_quality.py"),
        "environment": {"python": platform.python_version(),
                        "pandas": version("pandas"), "pyarrow": version("pyarrow")},
        "counts": dict(counts), "exclusive_row_dispositions": dict(dispositions),
        "date_exclusions_by_direction": dict(directions),
        "geographic_classification_totals": dict(totals),
        "baseline_counts_match": True, "reconciliation_passed": True,
        "timestamp_assumption": "Recorded clock values interpreted as America/New_York under D05; source DST semantics unverified",
        "treatment": "Retain exclusion rules for the April NYC target; preserve original files and historical screening report",
        "limitations": [
            "Geographic classification interprets lookup labels, not independently verified trip coordinates.",
            "Unknown/unspecified categories do not establish that pickups occurred outside NYC.",
            "Date and geography are disjoint in the exclusive dispositions; diagnostic key failures can overlap.",
            "Derived source_row_number is physical scan position, not an official unique trip identifier.",
            "No date correction, timezone shift, deduplication, or modeling table is performed.",
            "RECONCILED establishes accounting/classification only, not overall source completeness.",
        ],
    }
    return report, excerpts, groups


def write_outputs(report: dict, excerpts: list[dict], groups: list[dict]) -> tuple[Path, Path]:
    """Save aggregate reports separately from ignored row-level date excerpts.

    Args:
        report: Reconciled diagnostic summary and provenance.
        excerpts: Minimal out-of-April records, intended for local inspection.
        groups: Aggregate geographic exclusion counts by lookup ID and labels.

    Output:
        tuple[Path, Path]: Unique public-report and private-excerpt directories.
        Writes JSON/Markdown/aggregate CSVs and a local-only row-level CSV.
    """
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    public = ROOT / "reports/data_quality/april_2025_exclusions" / run_id
    private = ROOT / "data/interim/april_2025_exclusions" / run_id
    public.mkdir(parents=True, exist_ok=False)
    private.mkdir(parents=True, exist_ok=False)
    report["local_date_excerpt_path"] = str((private / "out_of_april_records.csv").relative_to(ROOT))
    (public / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
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
    with (private / "out_of_april_records.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=excerpt_columns)
        writer.writeheader()
        writer.writerows(excerpts)
    lines = ["# April 2025 Exclusion Inspection", "", f"Status: **{report['status']}**", "",
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
    return public, private


def main() -> int:
    """Read CLI options, inspect the snapshot, and print/save reconciled findings.

    Output:
        int: 0 for reconciled classifications, 2 for unresolved labels, or 1
        for a caught error. Argument parsing uses argparse's own exit codes.
        Prints aggregate counts and paths; creates no cleaned input dataset.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-report", default=(
        "reports/data_quality/april_2025/20261104T053754311799Z/report.json"),
        help="Original April quality report JSON; relative paths resolve from the project root")
    args = parser.parse_args()
    try:
        print("Verifying snapshots and inspecting April exclusions...", flush=True)
        report, excerpts, groups = inspect(project_path(args.baseline_report))
        public, private = write_outputs(report, excerpts, groups)
        print(f"Status: {report['status']}")
        print(f"Rows scanned: {report['counts']['total_rows']:,}")
        print(f"Out-of-April records: {report['counts']['out_of_april_timestamp']:,}")
        for name, value in report["date_exclusions_by_direction"].items():
            print(f"  {name}: {value:,}")
        print(f"Geographic exclusions: {report['counts']['in_april_mapped_non_nyc_scope_exclusions']:,}")
        for name, value in report["geographic_classification_totals"].items():
            print(f"  {name}: {value:,}")
        print(f"Accepted records: {report['counts']['accepted_for_april_nyc_screening']:,}")
        print("Baseline count comparison: PASS")
        print("Exclusive count reconciliation: PASS")
        print(f"Aggregate reports: {public}")
        print(f"Local-only date excerpts: {private / 'out_of_april_records.csv'}")
        print("Original data and prior reports unchanged. Timezone semantics remain an assumption.")
        return 2 if report["status"] == "REVIEW_REQUIRED" else 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Inspection incomplete; do not treat any partial outputs as reconciled findings.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
