"""Combine the three validated April–June 2025 zone-hour snapshots."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from utils import ROOT, TZ, month_bounds, read_lookup, sha256

REPORTS = {
    "2025-04": "april_2025/20261106T041153628221Z/report.json",
    "2025-05": "monthly/2025-05/20261108T052612838884Z/report.json",
    "2025-06": "monthly/2025-06/20261108T055257560857Z/report.json",
}
KEY = ["pickup_zone_id", "hour_start"]


def load_month(month, report_path, zones, lookup_hash):
    """Read one snapshot and reconcile it to its report and calendar.

    Args:
        month: Expected calendar month.
        report_path: Pinned build report.
        zones: In-scope IDs from the shared lookup.
        lookup_hash: SHA-256 of the current lookup.

    Output:
        Monthly table and source provenance for the combined report.
    """
    report = json.loads(report_path.read_text())
    if (report["status"] != "VALIDATED" or not report["count_reconciliation_passed"]
            or not report["parquet_round_trip_passed"]):
        raise ValueError(f"{month}: missing successful build checks")
    lookup_inputs = [item["sha256"] for item in report["inputs"]
                     if Path(item["path"]).name == "taxi_zone_lookup.csv"]
    if lookup_inputs != [lookup_hash]:
        raise ValueError(f"{month}: lookup fingerprint differs")
    path = ROOT / report["dataset_path"]
    if sha256(path) != report["dataset_sha256"]:
        raise ValueError(f"{month}: prepared file fingerprint differs")
    frame = pd.read_parquet(path)
    if list(frame.columns) != KEY + ["pickup_count"] or frame.isna().any().any():
        raise ValueError(f"{month}: unexpected columns or missing values")
    counts = frame["pickup_count"]
    if (not pd.api.types.is_integer_dtype(counts) or counts.lt(0).any()
            or not pd.api.types.is_integer_dtype(frame["pickup_zone_id"])):
        raise ValueError(f"{month}: invalid zone IDs or pickup counts")
    start, end = month_bounds(month)
    hours = pd.date_range(start, end, freq="h", inclusive="left", tz=TZ)
    expected = pd.MultiIndex.from_product([sorted(zones), hours], names=KEY)
    keys = pd.MultiIndex.from_frame(frame[KEY])
    if str(frame["hour_start"].dt.tz) != TZ or not keys.sort_values().equals(expected):
        raise ValueError(f"{month}: zone-hour keys differ from the complete local calendar")
    pickups = int(counts.sum())
    if (len(frame), pickups, len(zones), len(hours)) != (
            report["rows"], report["accepted_pickups"], report["zones"], report["hours_per_zone"]):
        raise ValueError(f"{month}: counts differ from the build report")
    return frame, {"month": month, "report_path": str(report_path.relative_to(ROOT)),
                   "report_sha256": sha256(report_path), "dataset_path": report["dataset_path"],
                   "dataset_sha256": report["dataset_sha256"], "rows": len(frame),
                   "accepted_pickups": pickups}


def main():
    """Build a zone-sorted panel and publish its report after Parquet read-back.

    Output:
        A timestamped Parquet file and a JSON report with verified input identities.
    """
    lookup = ROOT / "data/reference/taxi_zone_lookup.csv"
    lookup_hash = sha256(lookup)
    _, zones = read_lookup(lookup)
    frames, inputs = [], []
    for month, relative_path in REPORTS.items():
        frame, source = load_month(month, ROOT / "reports/data_preparation" / relative_path,
                                   zones, lookup_hash)
        frames.append(frame)
        inputs.append(source)
    panel = pd.concat(frames, ignore_index=True).sort_values(KEY, ignore_index=True)
    steps = panel.groupby("pickup_zone_id")["hour_start"].diff().dropna()
    if panel.duplicated(KEY).any() or not steps.eq(pd.Timedelta(hours=1)).all():
        raise ValueError("Duplicate or discontinuous zone-hour sequence across months")
    pickups = int(panel["pickup_count"].sum())
    if len(panel) != sum(item["rows"] for item in inputs) or pickups != sum(
            item["accepted_pickups"] for item in inputs):
        raise ValueError("Combined totals differ from the monthly reports")
    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = Path("april_june_2025") / run
    dataset = ROOT / "data/processed" / folder / "zone_hour_demand.parquet"
    report_path = ROOT / "reports/data_preparation" / folder / "report.json"
    dataset.parent.mkdir(parents=True, exist_ok=False)
    panel.to_parquet(dataset, index=False, compression="zstd")
    pd.testing.assert_frame_equal(panel, pd.read_parquet(dataset))
    report = {"status": "VALIDATED", "inputs": inputs, "lookup_sha256": lookup_hash,
              "script_sha256": sha256(Path(__file__)), "timezone_assumption": TZ,
              "zones": len(zones), "hours_per_zone": panel["hour_start"].nunique(),
              "rows": len(panel), "accepted_pickups": pickups, "unique_keys": True,
              "continuous_hourly_per_zone": True, "parquet_round_trip_passed": True,
              "dataset_path": str(dataset.relative_to(ROOT)), "dataset_sha256": sha256(dataset)}
    report_path.parent.mkdir(parents=True, exist_ok=False)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"VALIDATED: {len(panel):,} zone-hours and {pickups:,} recorded pickups")
    print(report_path)


if __name__ == "__main__":
    main()
