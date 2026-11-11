"""Refit the frozen validation selection and evaluate the June 15–30 final test."""

import fcntl
import json
import logging
import os
import platform
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import lightgbm as lgb
import mlflow
import numpy as np
import pandas as pd

from prepare_forecast_features import END, FIRST_TARGET, HOUR, TEST
from score_validation_baselines import BASELINES, KEY, SOURCE, summarize
from utils import ROOT, TZ, sha256

REFERENCE = ROOT / "reports/lightgbm_validation/20261111T055534905760Z/report.json"
VERIFICATION = ROOT / "reports/reproducibility/d9510d7a170f45518a7d633a0a1dcecf/report.json"
LOGGER = logging.getLogger(__name__)


def check_guardrails(candidate_wmape, baseline_wmape, zone_mae):
    """Apply the frozen overall and top-zone thresholds.

    Args:
        candidate_wmape, baseline_wmape: Pooled WMAPE percentages on identical cells.
        zone_mae: Frozen top-zone rows with candidate and baseline MAE columns.

    Output:
        Relative gain, per-zone passes, and whether LightGBM meets both thresholds.
    """
    gain = 1 - candidate_wmape / baseline_wmape if baseline_wmape else 0.0
    passed = zone_mae["mae"].le(1.10 * zone_mae["baseline_mae"])
    return gain, passed, bool(gain >= 0.05 and passed.all())


def check_grid(frame, start, end, zones):
    """Verify the complete origin grid and usable feature values.

    Args:
        frame: One fitting or test partition.
        start, end: Half-open local-time bounds.
        zones: Frozen integer zone IDs.

    Output:
        None on success. Raises ValueError for missing, duplicated or invalid rows.
    """
    hours = pd.date_range(start, end, freq="h", inclusive="left")
    expected = pd.MultiIndex.from_product([zones, hours], names=KEY)
    if (frame.isna().any().any() or not pd.MultiIndex.from_frame(frame[KEY]).equals(expected)
            or frame.pickup_count.lt(0).any()):
        raise ValueError("Partition differs from the frozen complete grid")


def run():
    """Freeze provenance before test access, refit, and publish the scored run.

    Output:
        MLflow model, predictions, diagnostics and a local aggregate final report.
    """
    source = json.loads(SOURCE.read_text())
    reference = json.loads(REFERENCE.read_text())
    verification = json.loads(VERIFICATION.read_text())
    base_path = ROOT / reference["baseline_report"]
    baseline = json.loads(base_path.read_text())
    path = ROOT / source["dataset_path"]
    if (verification["status"] != "VERIFIED"
            or sha256(path) != verification["source_sha256"]
            or sha256(SOURCE) != verification["source_report_sha256"]
            or sha256(REFERENCE) != verification["reference_report_sha256"]
            or sha256(base_path) != reference["baseline_report_sha256"]
            or sha256(ROOT / "uv.lock") != verification["lockfile_sha256"]
            or lgb.__version__ != verification["lightgbm"]):
        raise ValueError("Frozen validation inputs or environment differ")
    features = reference["features"]
    zones = verification["feature_schema"]["zone_categories"]
    setting = reference["best_candidate"]
    params = dict(reference["params"], num_leaves=setting["num_leaves"],
                  min_child_samples=setting["min_child_samples"])
    protocol = {"source_sha256": source["dataset_sha256"], "reference_sha256": sha256(REFERENCE),
                "verification_sha256": sha256(VERIFICATION), "script_sha256": sha256(Path(__file__)),
                "baseline_sha256": sha256(base_path), "lockfile_sha256": sha256(ROOT / "uv.lock"),
                "params": params, "rounds": setting["iterations"], "features": features,
                "zone_categories": zones, "frozen_top20": baseline["top20_training_zones"],
                "validation_selection": reference["selected_for_final_evaluation"],
                "test_start": TEST.isoformat(), "test_end_exclusive": END.isoformat(),
                "refit_start": FIRST_TARGET.isoformat(), "refit_end_exclusive": (TEST-HOUR).isoformat(),
                "gain_required": 0.05, "maximum_zone_mae_increase": 0.10,
                "fallback": baseline["selected_baseline"], "baseline_lags": BASELINES,
                "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "platform": platform.platform(), "python": platform.python_version(), "lightgbm": lgb.__version__}
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5050"))
    mlflow.set_experiment("urban-mobility-demand")
    with mlflow.start_run(run_name="frozen-final-test") as experiment, TemporaryDirectory() as temporary:
        folder = ROOT / "reports/final_evaluation" / experiment.info.run_id
        folder.mkdir(parents=True, exist_ok=False)
        # Publish the fixed protocol before reading the final test partition.
        (folder / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
        mlflow.log_dict(protocol, "protocol.json")
        mlflow.set_tag("stage", "final-test")
        mlflow.log_params(dict(params, rounds=setting["iterations"]))
        for file in (Path(__file__), ROOT / "uv.lock", ROOT / "scripts/score_validation_baselines.py",
                     ROOT / "scripts/prepare_forecast_features.py"):
            mlflow.log_artifact(str(file), artifact_path="source")
        train = pd.read_parquet(path, columns=["hour_start", "pickup_count", *features],
                                filters=[("refit_eligible", "=", True)]).sort_values(KEY).reset_index(drop=True)
        check_grid(train, FIRST_TARGET, TEST-HOUR, zones)
        if len(train) != source["refit_eligible_rows"]:
            raise ValueError("Refit row count differs from verified feature report")
        train["pickup_zone_id"] = pd.Categorical(train.pickup_zone_id, categories=zones)
        LOGGER.info("Refitting %s rows for %s rounds", len(train), setting["iterations"])
        fitted = lgb.train(params, lgb.Dataset(train[features], label=train.pickup_count,
                                               categorical_feature=["pickup_zone_id"]),
                           num_boost_round=setting["iterations"])
        work = Path(temporary)
        model_path = work / "model.txt"
        fitted.save_model(str(model_path))
        mlflow.log_artifact(str(model_path), "model")
        mlflow.log_dict(verification["feature_schema"], "feature_schema.json")
        test = pd.read_parquet(path, columns=["hour_start", "pickup_count", *features],
                               filters=[("split", "=", "test")]).sort_values(KEY).reset_index(drop=True)
        check_grid(test, TEST, END, zones)
        if len(test) != source["split_rows"]["test"]:
            raise ValueError("Final test count differs from the verified report")
        test["pickup_zone_id"] = pd.Categorical(test.pickup_zone_id, categories=zones)
        prediction = fitted.predict(test[features], num_threads=4)
        test[features].to_parquet(work / "inputs.parquet", index=False)
        child = """
import sys, json, pandas as pd, numpy as np, lightgbm as lgb
frame = pd.read_parquet(sys.argv[2])
schema = json.loads(sys.argv[4])
frame.pickup_zone_id = pd.Categorical(frame.pickup_zone_id, categories=schema['zone_categories'])
model = lgb.Booster(model_file=sys.argv[1])
np.save(sys.argv[3], model.predict(frame[schema['features']], num_threads=4))
"""
        subprocess.run([sys.executable, "-c", child, str(model_path), str(work / "inputs.parquet"),
                        str(work / "reload.npy"), json.dumps(verification["feature_schema"])], check=True)
        np.testing.assert_allclose(prediction, np.load(work / "reload.npy"), rtol=0, atol=1e-6)
        forecasts = test[KEY + ["pickup_count"]].copy()
        forecasts["lightgbm"] = prediction
        rows = pd.DataFrame({"zone": test.pickup_zone_id, "actual": test.pickup_count,
                             "zero": test.pickup_count.eq(0), "hour": test.hour,
                             "weekday": test.day_of_week, "date": test.hour_start.dt.date, "period": "pooled"})
        if rows.actual.sum() <= 0:
            raise ValueError("Zero test volume")
        scores, details = [], []
        for method in ["lightgbm", *BASELINES]:
            pred = prediction if method == "lightgbm" else test[BASELINES[method]].to_numpy()
            if not np.isfinite(pred).all() or (pred < 0).any():
                raise ValueError("Invalid forecasts")
            forecasts[method] = pred
            rows["forecast"] = pred
            rows["error"] = (rows.actual - pred).abs()
            scores.append(summarize(rows, "period").assign(method=method))
            for group in ("zone", "hour", "weekday", "date"):
                detail = summarize(rows, group).rename(columns={group: "value"})
                details.append(detail.assign(slice=group, method=method))
        scores = pd.concat(scores, ignore_index=True)
        slices = pd.concat(details, ignore_index=True)
        zone_scores = slices[slices.slice.eq("zone")].pivot(index="value", columns="method", values="mae")
        top = zone_scores.loc[baseline["top20_training_zones"]].copy()
        top["mae"] = top.lightgbm
        top["baseline_mae"] = top[baseline["selected_baseline"]]
        pooled = scores.set_index("method")
        gain, top["passed"], qualifies = check_guardrails(
            pooled.loc["lightgbm", "wmape_pct"], pooled.loc[baseline["selected_baseline"], "wmape_pct"], top)
        recommend = "lightgbm" if protocol["validation_selection"] == "lightgbm" and qualifies else protocol["fallback"]
        for name, table in [("metrics.csv", scores), ("error_slices.csv", slices),
                            ("top20_guardrail.csv", top.reset_index())]:
            table.to_csv(folder / name, index=False, na_rep="N/A")
            mlflow.log_artifact(str(folder / name), "evaluation")
        forecasts.to_parquet(work / "test_predictions.parquet", index=False)
        mlflow.log_artifact(str(work / "test_predictions.parquet"))
        for row in scores.itertuples():
            mlflow.log_metrics({f"{row.method}_mae": row.mae, f"{row.method}_wmape_pct": row.wmape_pct})
        result = {"run_id": experiment.info.run_id, "status": "EVALUATED", "refit_rows": len(train),
                  "test_rows": len(test), "relative_gain_pct": 100*gain,
                  "top20_passed": int(top.passed.sum()), "recommendation": recommend,
                  "lightgbm_passed_final_guardrails": qualifies, "protocol_sha256": sha256(folder / "protocol.json"),
                  "model_uri": f"runs:/{experiment.info.run_id}/model/model.txt",
                  "model_sha256": sha256(model_path), "predictions_sha256": sha256(work / "test_predictions.parquet"),
                  "reload_max_difference": float(np.max(np.abs(prediction-np.load(work / "reload.npy"))))}
        mlflow.log_dict(result, "result.json")
    (folder / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(scores[["method", "mae", "wmape_pct"]].to_string(index=False))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    lock_path = ROOT / "artifacts/final_evaluation.lock"
    lock_path.parent.mkdir(exist_ok=True)
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        existing = list((ROOT / "reports/final_evaluation").glob("*/report.json"))
        if existing:
            print(f"Final evaluation already exists: {existing[0]}")
        else:
            run()
