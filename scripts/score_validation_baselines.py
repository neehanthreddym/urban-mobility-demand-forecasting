"""Score the three charter baselines on the pinned validation panel."""

import csv
import fcntl
import json
import argparse
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
import pandas as pd
from prepare_forecast_features import FIRST_TARGET, HOUR, TEST, VALIDATION
from utils import ROOT, project_path, sha256

SOURCE = ROOT / "reports/data_preparation/forecast_features/20261108T064005732515Z/report.json"
# Insertion order implements the charter tie-break.
BASELINES = {"weekly": "lag_168", "daily": "lag_24", "persistence": "lag_2"}
MIDPOINT = VALIDATION + pd.Timedelta(days=7)
KEY = ["pickup_zone_id", "hour_start"]


def summarize(rows, group):
    """Aggregate signed-independent absolute errors over common forecast cells.

    Args:
        rows: Scored cells with actual, forecast, zero indicator and absolute error.
        group: Column identifying the reporting slice.

    Output:
        Counts, volumes, MAE and pooled WMAPE per group. Zero-volume WMAPE is missing.
    """
    result = rows.groupby(group, observed=True).agg(
        cells=("actual", "size"), actual_total=("actual", "sum"),
        forecast_total=("forecast", "sum"), absolute_error=("error", "sum"),
        zero_share=("zero", "mean"),
    )
    result["mae"] = result.absolute_error / result.cells
    result["wmape_pct"] = 100 * result.absolute_error / result.actual_total.replace(0, float("nan"))
    return result.reset_index()


def main():
    """Verify the feature snapshot, freeze the training-zone ranking and score validation.

    Output:
        Timestamped aggregate metrics, diagnostics, provenance and an experiment log entry.
    """
    started = perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", default=str(SOURCE), help="Forecast-feature validation report.")
    args = parser.parse_args()
    source_report = project_path(args.source_report)
    source = json.loads(source_report.read_text())
    path = ROOT / source["dataset_path"]
    if source["status"] != "VALIDATED" or sha256(path) != source["dataset_sha256"]:
        raise ValueError("Feature file differs from validated snapshot")
    train = pd.read_parquet(path, columns=KEY + ["pickup_count"], filters=[("split", "=", "train")])
    if not train.hour_start.between(FIRST_TARGET, VALIDATION - HOUR, inclusive="left").all():
        raise ValueError("Training rows outside the initial fitting interval")
    ranking = (train.groupby(KEY[0], observed=True).pickup_count.sum().reset_index()
               .sort_values(["pickup_count", KEY[0]], ascending=[False, True]))
    top = ranking.head(20)[KEY[0]].tolist()
    valid = pd.read_parquet(path, columns=KEY + ["pickup_count", *BASELINES.values()],
                            filters=[("split", "=", "validation")]).sort_values(KEY)
    hours = pd.date_range(VALIDATION, TEST - HOUR, inclusive="left", freq="h")
    grid = pd.MultiIndex.from_product([sorted(ranking[KEY[0]]), hours], names=KEY)
    if not pd.MultiIndex.from_frame(valid[KEY]).equals(grid) or len(valid) != source["split_rows"]["validation"]:
        raise ValueError("Validation keys differ from the full zone-hour grid")
    numeric = valid[["pickup_count", *BASELINES.values()]]
    if numeric.isna().any().any() or numeric.lt(0).any().any() or valid.pickup_count.sum() == 0:
        raise ValueError("Invalid forecasts/targets or zero total validation volume")

    rows = pd.DataFrame({"zone": valid[KEY[0]], "actual": valid.pickup_count,
                         "zero": valid.pickup_count.eq(0), "hour": valid.hour_start.dt.hour,
                         "weekday": valid.hour_start.dt.day_of_week, "date": valid.hour_start.dt.date,
                         "week": valid.hour_start.ge(MIDPOINT).astype(int) + 1, "period": "pooled"})
    metrics, slices = [], []
    median_zone_wmape = {}
    for name, column in BASELINES.items():
        rows["forecast"] = valid[column]
        rows["error"] = (rows.actual - rows.forecast).abs()
        pooled = summarize(rows, "period")
        weeks = summarize(rows, "week").rename(columns={"week": "period"})
        weeks["period"] = weeks.period.map({1: "week_1", 2: "week_2"})
        metrics.append(pd.concat([pooled, weeks]).assign(baseline=name))
        for group in ("zone", "hour", "weekday", "date"):
            detail = summarize(rows, group)
            if group == "zone":
                median_zone_wmape[name] = float(detail.wmape_pct.median())
            slices.append(detail.rename(columns={group: "value"}).assign(slice=group, baseline=name))
    scores = pd.concat(metrics, ignore_index=True)
    pooled_scores = scores[scores.period.eq("pooled")].set_index("baseline")
    winner = min(BASELINES, key=lambda name: pooled_scores.loc[name, "absolute_error"])
    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = ROOT / "reports/baselines" / run
    folder.mkdir(parents=True, exist_ok=False)
    scores.to_csv(folder / "validation_metrics.csv", index=False, na_rep="N/A")
    pd.concat(slices).to_csv(folder / "validation_slices.csv", index=False, na_rep="N/A")
    ranking.head(20).to_csv(folder / "top20_training_zones.csv", index=False)
    report = {"experiment_id": run, "source_sha256": source["dataset_sha256"],
              "source_report": os.path.relpath(source_report, ROOT), "source_report_sha256": sha256(source_report),
              "script_sha256": sha256(Path(__file__)), "git_revision": subprocess.check_output(
                  ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "baseline_lags": BASELINES, "seed": "N/A (deterministic)",
              "validation_start": VALIDATION.isoformat(), "validation_end_exclusive": (TEST - HOUR).isoformat(),
              "top20_training_zones": top, "median_positive_volume_zone_wmape_pct": median_zone_wmape,
              "selected_baseline": winner, "mae": float(pooled_scores.loc[winner, "mae"]),
              "wmape_pct": float(pooled_scores.loc[winner, "wmape_pct"]),
              "runtime_seconds": perf_counter() - started, "artifact_path": str(folder.relative_to(ROOT))}
    (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    fields = ["experiment_id", "git_revision", "source_sha256", "script_sha256", "validation_start",
              "validation_end_exclusive", "seed", "selected_baseline", "mae", "wmape_pct",
              "runtime_seconds", "artifact_path"]
    with (ROOT / "reports/experiments.csv").open("a+", newline="") as log:
        fcntl.flock(log, fcntl.LOCK_EX)
        log.seek(0, 2)
        writer = csv.DictWriter(log, fieldnames=fields, extrasaction="ignore")
        if log.tell() == 0:
            writer.writeheader()
        writer.writerow(report)
        log.flush()
    print(scores[["baseline", "period", "cells", "mae", "wmape_pct"]].to_string(index=False))
    print(f"Selected {winner}. Reports: {folder}")


if __name__ == "__main__":
    main()
