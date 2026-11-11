"""Interpret final forecasts and rank hourly activity against a training-only reference."""

import json
import logging
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import numpy as np
import pandas as pd

from prepare_forecast_features import END, FIRST_TARGET, HOUR, TEST, VALIDATION
from score_validation_baselines import KEY, SOURCE, summarize
from utils import ROOT, sha256

FINAL = ROOT / "reports/final_evaluation/71dcb809d5c0409484d8b55b21751f17/report.json"


def planning_table(predictions, train):
    """Attach a fixed per-zone training reference and rank forecasts within each hour.

    Args:
        predictions: Saved zone-hour predictions with a lightgbm column.
        train: Initial training targets, ending May 31 at 22:00 NYC local time.

    Output:
        Forecast rows with training 90th percentiles, strict exceedance flags and
        competition ranks. Tied forecasts share the minimum rank.
    """
    if not train.hour_start.between(FIRST_TARGET, VALIDATION-HOUR, inclusive="left").all():
        raise ValueError("Reference includes rows outside initial training")
    reference = train.groupby("pickup_zone_id", observed=True).pickup_count.quantile(
        0.9, interpolation="linear").rename("training_p90")
    result = predictions.merge(reference, on="pickup_zone_id", how="left", validate="many_to_one")
    if result.training_p90.isna().any() or not np.isfinite(result.lightgbm).all() or result.lightgbm.lt(0).any():
        raise ValueError("Invalid forecasts or missing historical reference")
    result["high_demand_flag"] = result.lightgbm.gt(result.training_p90)
    result["forecast_rank"] = result.groupby("hour_start").lightgbm.rank(method="min", ascending=False).astype("int64")
    return result.sort_values(["hour_start", "forecast_rank", "pickup_zone_id"], ignore_index=True)


def main():
    """Verify saved forecasts and publish planning tables, diagnostics and charts.

    Output:
        MLflow analysis run, aggregate findings, and a local ignored forecast table.
    """
    logging.basicConfig(level=logging.INFO)
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5050"))
    mlflow.set_experiment("urban-mobility-demand")
    final = json.loads(FINAL.read_text())
    source = json.loads(SOURCE.read_text())
    protocol_path = FINAL.with_name("protocol.json")
    protocol = json.loads(protocol_path.read_text())
    dataset = ROOT / source["dataset_path"]
    if (final["status"] != "EVALUATED" or final["recommendation"] != "lightgbm"
            or sha256(protocol_path) != final["protocol_sha256"]
            or sha256(dataset) != protocol["source_sha256"]):
        raise ValueError("Final artifacts differ from the fixed evaluation")
    artifact_uri = f"runs:/{final['run_id']}/test_predictions.parquet"
    saved = Path(mlflow.artifacts.download_artifacts(artifact_uri=artifact_uri))
    if sha256(saved) != final["predictions_sha256"]:
        raise ValueError("Saved prediction fingerprint differs")
    pred = pd.read_parquet(saved)
    train = pd.read_parquet(dataset, columns=KEY+["pickup_count"], filters=[("split", "=", "train")])
    zones = sorted(train.pickup_zone_id.unique())
    expected = pd.MultiIndex.from_product(
        [zones, pd.date_range(TEST, END, inclusive="left", freq="h")], names=KEY)
    if (not pd.MultiIndex.from_frame(pred.sort_values(KEY)[KEY]).equals(expected)
            or len(pred) != final["test_rows"] or pred.isna().any().any()):
        raise ValueError("Prediction rows differ from the complete final-test grid")
    table = planning_table(pred, train)
    lookup_path = ROOT / "data/reference/taxi_zone_lookup.csv"
    feature_source = json.loads((ROOT / source["source_report"]).read_text())
    if sha256(lookup_path) != feature_source["lookup_sha256"]:
        raise ValueError("Lookup differs from combined dataset reference")
    lookup = pd.read_csv(lookup_path, keep_default_na=False)[["LocationID", "Borough", "Zone"]]
    table = table.merge(lookup, left_on="pickup_zone_id", right_on="LocationID", validate="many_to_one")
    if table[["Borough", "Zone"]].isna().any().any():
        raise ValueError("Unknown zone label")
    table = table.drop(columns="LocationID")
    table["forecast_origin"] = table.hour_start
    table["model_run_id"] = final["run_id"]
    errors = pd.DataFrame({"zone": table.pickup_zone_id, "date": table.hour_start.dt.date,
                           "hour": table.hour_start.dt.hour, "weekday": table.hour_start.dt.day_of_week,
                           "actual": table.pickup_count, "forecast": table.lightgbm,
                           "zero": table.pickup_count.eq(0)})
    errors["error"] = (errors.actual-errors.forecast).abs()
    zones_summary = summarize(errors, "zone").merge(lookup, left_on="zone", right_on="LocationID")
    zones_summary["bias"] = (zones_summary.forecast_total-zones_summary.actual_total)/zones_summary.cells
    dates = summarize(errors, "date")
    hours = summarize(errors, "hour")
    weekday = summarize(errors, "weekday")
    largest = zones_summary.sort_values("absolute_error", ascending=False)
    reference = table[["pickup_zone_id", "training_p90"]].drop_duplicates()
    sparse = reference.training_p90.eq(0).sum()
    with mlflow.start_run(run_name="final-error-analysis-and-planning") as run:
        folder = ROOT / "reports/planning" / run.info.run_id
        folder.mkdir(parents=True, exist_ok=False)
        output = ROOT / "reports/forecasts" / run.info.run_id
        output.mkdir(parents=True, exist_ok=False)
        table.to_parquet(output / "planning.parquet", index=False)
        table.to_csv(output / "planning.csv", index=False)
        for name, data in [("zone_errors", zones_summary), ("daily_errors", dates), ("hourly_errors", hours),
                           ("weekday_errors", weekday), ("training_reference", reference)]:
            data.to_csv(folder / f"{name}.csv", index=False, na_rep="N/A")
        flags = table.groupby("pickup_zone_id").agg(flagged_hours=("high_demand_flag", "sum"))
        flags.to_csv(folder / "flag_counts.csv")
        fig, ax = plt.subplots(figsize=(10, 5))
        busiest_errors = largest.head(10).sort_values("mae")
        ax.barh(busiest_errors.Zone, busiest_errors.mae)
        ax.set_xlabel("MAE (recorded pickups per zone-hour)")
        ax.set_title("Ten zones contributing most absolute error — June 15–30, 2025")
        fig.tight_layout()
        fig.savefig(folder / "zone_errors.png", dpi=160)
        plt.close(fig)
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(dates.date, dates.actual_total, label="Recorded")
        ax.plot(dates.date, dates.forecast_total, label="Forecast")
        ax.legend()
        ax.tick_params(axis="x", rotation=45)
        ax.set_ylabel("Daily recorded pickups")
        ax.set_title("Final-test daily totals")
        fig.tight_layout()
        fig.savefig(folder / "daily_totals.png", dpi=160)
        plt.close(fig)
        worst = largest.iloc[0]
        hardest_hour = hours.loc[hours.mae.idxmax()]
        hardest_date = dates.loc[dates.mae.idxmax()]
        notes = [
            "# Final forecast interpretation", "",
            f"The largest zone contribution to absolute error was {worst.Zone} (ID {int(worst.zone)}), "
            f"with MAE {worst.mae:.2f} pickups per zone-hour and WMAPE {worst.wmape_pct:.2f}%.",
            f"The highest average error by clock hour occurred at {int(hardest_hour.hour):02d}:00 "
            f"({hardest_hour.mae:.2f} pickups per zone-hour).",
            f"The highest daily average error occurred on {hardest_date.date} "
            f"({hardest_date.mae:.2f} pickups per zone-hour).", "",
            f"{int(table.high_demand_flag.sum()):,} of {len(table):,} forecast cells exceeded their "
            "zone's initial-training 90th percentile.", "",
            "Hourly ranks use predicted pickups only. Equal forecasts share the minimum competition rank.",
            "High-demand flags use strict forecast > training percentile and linear percentile interpolation.",
            f"{sparse} zones have a zero training 90th percentile. Any positive forecast flags these zones, "
            "so review the numeric reference and predicted volume alongside the flag.", "",
            "The reference is calculated here from the fixed initial training period. Its value was not "
            "saved before validation; the percentile rule was specified in the charter before evaluation.",
            "This analysis describes final-test errors. Subsequent model changes require a new future evaluation period.",
            "Available vehicle capacity and unserved requests are unobserved. Planning ranks identify "
            "predicted recorded pickup activity. Source timezone and reporting latency remain assumptions.",
        ]
        (folder / "findings.md").write_text("\n\n".join(notes)+"\n")
        report = {"analysis_run_id": run.info.run_id, "final_model_run_id": final["run_id"],
                  "script_sha256": sha256(Path(__file__)), "final_report_sha256": sha256(FINAL),
                  "feature_source_sha256": source["dataset_sha256"], "lookup_sha256": sha256(lookup_path),
                  "prediction_source_sha256": final["predictions_sha256"],
                  "planning_path": str((output / "planning.parquet").relative_to(ROOT)),
                  "planning_sha256": sha256(output / "planning.parquet"),
                  "rows": len(table), "flagged_cells": int(table.high_demand_flag.sum()),
                  "training_reference_start": FIRST_TARGET.isoformat(),
                  "training_reference_end_exclusive": (VALIDATION-HOUR).isoformat(),
                  "reference_materialized_after_evaluation": True,
                  "percentile": 0.9, "interpolation": "linear", "rank_ties": "min"}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        mlflow.set_tags({"stage": "planning-analysis", "final_model_run_id": final["run_id"]})
        mlflow.log_artifacts(str(folder), "analysis")
        mlflow.log_artifacts(str(output), "planning")
        mlflow.log_artifact(str(Path(__file__)), "source")
        print("\n".join(notes[2:8]))
        print(folder)


if __name__ == "__main__":
    main()
