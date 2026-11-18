"""Run the charter's six LightGBM candidates and calendar-only diagnostic on validation."""

import itertools
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
import lightgbm as lgb
import numpy as np
import pandas as pd
import argparse
import os
from prepare_forecast_features import FIRST_TARGET, HOUR, TEST, VALIDATION
from score_validation_baselines import KEY, MIDPOINT, SOURCE, summarize
from utils import ROOT, project_path, sha256

BASE = ROOT / "reports/baselines/20261108T233614690012Z/report.json"
PARAMS = dict(objective="poisson", metric="l1", learning_rate=0.05, num_threads=4,
              seed=42, deterministic=True, force_col_wise=True, verbosity=-1)
CALENDAR = ["pickup_zone_id", "hour", "day_of_week", "is_weekend"]


def evaluate(train, valid, features, leaves, minimum):
    """Fit a global count model and score its best iteration on validation.

    Args:
        train, valid: Chronological zone-hour data with matching zone categories.
        features: Approved predictors.
        leaves, minimum: Tree leaf limit and minimum samples per leaf.

    Output:
        Configuration metrics and unrounded predictions at the selected iteration.
    """
    params = dict(PARAMS, num_leaves=leaves, min_child_samples=minimum)
    training = lgb.Dataset(train[features], label=train.pickup_count, categorical_feature=["pickup_zone_id"])
    validation = lgb.Dataset(valid[features], label=valid.pickup_count, reference=training)
    start = perf_counter()
    model = lgb.train(
        params, training, 
        num_boost_round=500, 
        valid_sets=[validation],
        callbacks=[lgb.early_stopping(50, verbose=False)]
    )
    predictions = model.predict(valid[features], num_iteration=model.best_iteration, num_threads=4)
    if not np.isfinite(predictions).all() or (predictions < 0).any():
        raise ValueError("Invalid Poisson forecasts")
    errors = (valid.pickup_count - predictions).abs()
    return {"num_leaves": leaves, "min_child_samples": minimum, "iterations": model.best_iteration,
            "mae": float(errors.mean()), "wmape_pct": float(100 * errors.sum() / valid.pickup_count.sum()),
            "seconds": perf_counter() - start}, predictions


def load_validation_inputs(source_report: Path = SOURCE, baseline_report: Path = BASE):
    """Load verified train and validation inputs with shared zone categories.

    Args:
        source_report: Path to the forecast-feature validation report.
        baseline_report: Path to baseline results for the same feature snapshot.

    Output:
        Feature report, baseline report, training rows and validation rows.

    Raises:
        ValueError: Input fingerprints, dates, keys or zone categories disagree.
    """
    source = json.loads(source_report.read_text())
    base = json.loads(baseline_report.read_text())
    path = ROOT / source["dataset_path"]
    if (sha256(path) != base["source_sha256"] or base["source_sha256"] != source["dataset_sha256"]
            or sha256(source_report) != base["source_report_sha256"] or source["status"] != "VALIDATED"):
        raise ValueError("Feature snapshot differs from the baseline experiment")
    features = source["predictors"]
    frames = []
    for split, start, stop in [("train", FIRST_TARGET, VALIDATION - HOUR),
                               ("validation", VALIDATION, TEST - HOUR)]:
        frame = pd.read_parquet(path, columns=["hour_start", "pickup_count", *features],
                                filters=[("split", "=", split)]).sort_values(KEY).reset_index(drop=True)
        if (len(frame) != source["split_rows"][split] or frame.duplicated(KEY).any()
                or frame.isna().any().any() or not frame.hour_start.between(start, stop, inclusive="left").all()):
            raise ValueError(f"Invalid {split} rows")
        frames.append(frame)
    train, valid = frames
    zones = sorted(train.pickup_zone_id.unique())
    for frame in frames:
        frame["pickup_zone_id"] = pd.Categorical(frame.pickup_zone_id, categories=zones)
    if valid.pickup_zone_id.isna().any():
        raise ValueError("Unknown validation zone")
    return source, base, train, valid


def main():
    """Read frozen train/validation inputs, select the candidate and write validation evidence.

    Output:
        Parameter scores, weekly and zone diagnostics, ablation, and selection report.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", default=str(SOURCE), help="Forecast-feature validation report.")
    parser.add_argument("--baseline-report", default=str(BASE), help="Baseline results for the selected feature report.")
    args = parser.parse_args()

    source_report = project_path(args.source_report)
    baseline_report = project_path(args.baseline_report)

    started = perf_counter()
    source, base, train, valid = load_validation_inputs(source_report, baseline_report)
    features = source["predictors"]
    actual = valid.pickup_count
    baseline_errors = (actual - valid[base["baseline_lags"][base["selected_baseline"]]]).abs()
    if not np.isclose(baseline_errors.mean(), base["mae"], atol=1e-10, rtol=0):
        raise ValueError("Weekly baseline comparison could not be reproduced")
    scores = []
    forecasts = []
    for leaves, minimum in itertools.product([15, 31], [20, 50, 100]):
        score, pred = evaluate(train, valid, features, leaves, minimum)
        scores.append(score)
        forecasts.append(pred)
        print(f"leaves={leaves} minimum={minimum} WMAPE={score['wmape_pct']:.4f}%", flush=True)
    best = min(range(len(scores)), key=lambda i: (round(scores[i]["wmape_pct"], 6), scores[i]["num_leaves"],
                                                   -scores[i]["min_child_samples"], scores[i]["iterations"]))
    candidate = scores[best]
    ablation, _ = evaluate(train, valid, CALENDAR, candidate["num_leaves"], candidate["min_child_samples"])
    rows = pd.DataFrame({"actual": actual, "forecast": forecasts[best], "zone": valid.pickup_zone_id,
                         "week": valid.hour_start.ge(MIDPOINT).astype(int) + 1, "zero": actual.eq(0),
                         "hour": valid.hour, "weekday": valid.day_of_week, "date": valid.hour_start.dt.date})
    rows["error"] = (rows.actual - rows.forecast).abs()
    by_zone = summarize(rows, "zone").set_index("zone")
    top = by_zone.loc[base["top20_training_zones"], ["mae"]].copy()
    top["baseline_mae"] = baseline_errors.groupby(valid.pickup_zone_id, observed=True).mean()
    top["passed"] = top.mae <= 1.10 * top.baseline_mae
    gain = 1 - candidate["wmape_pct"] / base["wmape_pct"] if base["wmape_pct"] else 0.
    selected = "lightgbm" if gain >= 0.05 and top.passed.all() else base["selected_baseline"]
    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = ROOT / "reports/lightgbm_validation" / run
    folder.mkdir(parents=True)
    pd.DataFrame(scores).to_csv(folder / "configurations.csv", index=False)
    top.to_csv(folder / "top20_guardrail.csv")
    for group in ("zone", "week", "hour", "weekday", "date"):
        summarize(rows, group).to_csv(folder / f"errors_by_{group}.csv", index=False, na_rep="N/A")
    report = {
        "experiment_id": run, "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "script_sha256": sha256(Path(__file__)),
        "source_sha256": source["dataset_sha256"],
        "source_report": os.path.relpath(source_report, ROOT),
        "source_report_sha256": sha256(source_report),
        "baseline_report": os.path.relpath(baseline_report, ROOT),
        "baseline_report_sha256": sha256(baseline_report),
        "platform": platform.platform(), "lightgbm_version": lgb.__version__,
        "params": PARAMS, "max_rounds": 500,
        "early_stopping_rounds": 50,
        "features": features,
        "training_rows": len(train),
        "validation_rows": len(valid),
        "validation_start": VALIDATION.isoformat(),
        "validation_end_exclusive": (TEST-HOUR).isoformat(),
        "best_candidate": candidate,
        "ablation_features": CALENDAR,
        "ablation": ablation,
        "relative_gain_pct": 100*gain,
        "top20_passed": int(top.passed.sum()),
        "selected_for_final_evaluation": selected,
        "median_positive_volume_zone_wmape_pct": by_zone.wmape_pct.median(),
        "runtime_seconds": perf_counter() - started
    }
    (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(folder, selected, flush=True)


if __name__ == "__main__":
    main()
