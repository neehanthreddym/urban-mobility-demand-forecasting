"""Refit the frozen validation selection and evaluate the June 15–30 final test."""

import fcntl
import json
import logging
import os
import platform
import subprocess
import sys
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
import lightgbm as lgb
import mlflow
import numpy as np
import pandas as pd
from textwrap import dedent
from prepare_forecast_features import END, FIRST_TARGET, HOUR, TEST
from score_validation_baselines import BASELINES, KEY, SOURCE, summarize
from utils import ROOT, TZ, project_path, sha256

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


def check_frozen_protocol(current: dict, expected: dict) -> None:
    """Require a historical replay to match the recorded forecasting protocol.

    Args:
        current: Protocol prepared for the reproduction run.
        expected: Protocol saved with the original final evaluation.

    Output:
        None when all frozen fields match.

    Raises:
        ValueError: A frozen field is missing or differs.
    """
    fields = (
        "source_sha256",
        "params",
        "rounds",
        "features",
        "zone_categories",
        "frozen_top20",
        "validation_selection",
        "test_start",
        "test_end_exclusive",
        "refit_start",
        "refit_end_exclusive",
        "gain_required",
        "maximum_zone_mae_increase",
        "fallback",
        "baseline_lags",
    )
    differences = [
        field
        for field in fields
        if field not in current
        or field not in expected
        or current[field] != expected[field]
    ]
    if differences:
        raise ValueError("Historical replay differs in: " + ", ".join(differences))


def check_reproduction_metrics(current: pd.DataFrame, expected: pd.DataFrame, tolerance: float = 0.000001) -> float:
    """Compare historical replay scores by method.

    Args:
        current: Reproduced scores containing method, mae and wmape_pct.
        expected: Original scores containing the same columns.
        tolerance: Maximum absolute difference allowed for each metric.

    Output:
        Largest absolute metric difference across all methods.

    Raises:
        ValueError: Methods differ, scores are invalid or tolerance is exceeded.
    """
    current = current.set_index("method").sort_index()
    expected = expected.set_index("method").sort_index()

    if not current.index.is_unique or not expected.index.is_unique:
        raise ValueError("Historical metrics contain duplicate methods")

    if current.empty or not current.index.equals(expected.index):
        raise ValueError("Historical methods differ or are empty")

    columns = ["mae", "wmape_pct"]
    differences = (current[columns] - expected[columns]).abs().to_numpy()

    if not np.isfinite(differences).all() or (differences > tolerance).any():
        raise ValueError("Historical metrics exceed reproduction tolerance")

    return float(differences.max())


def run(source_report: Path = SOURCE, reference_report: Path = REFERENCE, verification_report: Path = VERIFICATION, reproduce_report: Path | None = None,):
    """Verify inputs, refit the selected model and record test evaluation.

    Args:
        source_report: Forecast-feature validation report.
        reference_report: Validation-selected model settings and results.
        verification_report: Successful model-reproduction evidence.
        reproduce_report: Original final-evaluation report for a historical replay.

    Output:
        MLflow model, predictions, diagnostics and a local evaluation report.

    Raises:
        ValueError: Input identities or the verified environment disagree.
    """
    source_report = project_path(source_report)
    reference_report = project_path(reference_report)
    verification_report = project_path(verification_report)
    source = json.loads(source_report.read_text())
    reference = json.loads(reference_report.read_text())
    verification = json.loads(verification_report.read_text())
    base_path = ROOT / reference["baseline_report"]
    baseline = json.loads(base_path.read_text())
    path = ROOT / source["dataset_path"]
    if (verification["status"] != "VERIFIED"
            or sha256(path) != verification["source_sha256"]
            or sha256(source_report) != verification["source_report_sha256"]
            or 	sha256(reference_report) != verification["reference_report_sha256"]
            or sha256(base_path) != reference["baseline_report_sha256"]
            or sha256(ROOT / "uv.lock") != verification["lockfile_sha256"]
            or lgb.__version__ != verification["lightgbm"]):
        raise ValueError("Frozen validation inputs or environment differ")
    features = reference["features"]
    zones = verification["feature_schema"]["zone_categories"]
    setting = reference["best_candidate"]
    params = dict(reference["params"], num_leaves=setting["num_leaves"],
                  min_child_samples=setting["min_child_samples"])
    protocol = {
                "source_sha256": source["dataset_sha256"],
                "reference_sha256": sha256(reference_report),
                "verification_sha256": sha256(verification_report),
                "script_sha256": sha256(Path(__file__)),
                "baseline_sha256": sha256(base_path),
                "lockfile_sha256": sha256(ROOT / "uv.lock"),
                "params": params,
                "rounds": setting["iterations"],
                "features": features,
                "zone_categories": zones,
                "frozen_top20": baseline["top20_training_zones"],
                "validation_selection": reference["selected_for_final_evaluation"],
                "test_start": TEST.isoformat(),
                "test_end_exclusive": END.isoformat(),
                "refit_start": FIRST_TARGET.isoformat(),
                "refit_end_exclusive": (TEST-HOUR).isoformat(),
                "gain_required": 0.05, "maximum_zone_mae_increase": 0.10,
                "fallback": baseline["selected_baseline"],
                "baseline_lags": BASELINES,
                "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "platform": platform.platform(), "python": platform.python_version(), "lightgbm": lgb.__version__
            }
    if reproduce_report is not None:
        original_report_path = project_path(reproduce_report)
        original_report = json.loads(original_report_path.read_text())
        original_protocol_path = original_report_path.with_name("protocol.json")

        if (original_report["status"] != "EVALUATED" or sha256(original_protocol_path) != original_report["protocol_sha256"]):
            raise ValueError("Original evaluation evidence failed verification")

        original_protocol = json.loads(original_protocol_path.read_text())
        check_frozen_protocol(protocol, original_protocol)
        original_metrics_path = original_report_path.with_name("metrics.csv")
        expected_metrics = pd.read_csv(original_metrics_path)
        protocol["reproduction_reference"] = {
            "report": os.path.relpath(original_report_path, ROOT),
            "report_sha256": sha256(original_report_path),
            "metrics_sha256": sha256(original_metrics_path),
            "metric_tolerance": 0.000001,
        }
    run_name = ("historical-final-reproduction" if reproduce_report is not None else "frozen-final-test")
    evaluation_purpose = ("historical-reproduction" if reproduce_report is not None else "final-test")
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5050"))
    mlflow.set_experiment("urban-mobility-demand")
    with mlflow.start_run(run_name=run_name) as experiment, TemporaryDirectory() as temporary:
        folder = ROOT / "reports/final_evaluation" / experiment.info.run_id
        folder.mkdir(parents=True, exist_ok=False)
        # Publish the fixed protocol before reading the final test partition.
        (folder / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
        mlflow.log_dict(protocol, "protocol.json")
        mlflow.set_tag("stage", evaluation_purpose)
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
        child = dedent("""
            import sys, json, pandas as pd, numpy as np, lightgbm as lgb
            frame = pd.read_parquet(sys.argv[2])
            schema = json.loads(sys.argv[4])
            frame.pickup_zone_id = pd.Categorical(
                frame.pickup_zone_id,
                categories=schema["zone_categories"],
            )
            model = lgb.Booster(model_file=sys.argv[1])
            np.save(
                sys.argv[3],
                model.predict(frame[schema["features"]], num_threads=4),
            )
        """)
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
        if reproduce_report is not None:
            reproduction_difference = check_reproduction_metrics(scores, expected_metrics)
            if (recommend != original_report["recommendation"] or int(top.passed.sum()) != original_report["top20_passed"]):
                raise ValueError("Historical recommendation or zone checks differ")
        for name, table in [("metrics.csv", scores), ("error_slices.csv", slices), ("top20_guardrail.csv", top.reset_index())]:
            table.to_csv(folder / name, index=False, na_rep="N/A")
            mlflow.log_artifact(str(folder / name), "evaluation")
        forecasts.to_parquet(work / "test_predictions.parquet", index=False)
        mlflow.log_artifact(str(work / "test_predictions.parquet"))
        for row in scores.itertuples():
            mlflow.log_metrics({f"{row.method}_mae": row.mae, f"{row.method}_wmape_pct": row.wmape_pct})
        result = {
            "run_id": experiment.info.run_id,
            "status": "EVALUATED",
            "refit_rows": len(train),
            "test_rows": len(test),
            "relative_gain_pct": 100*gain,
            "top20_passed": int(top.passed.sum()),
            "recommendation": recommend,
            "lightgbm_passed_final_guardrails": qualifies,
            "protocol_sha256": sha256(folder / "protocol.json"),
            "model_uri": f"runs:/{experiment.info.run_id}/model/model.txt",
            "model_sha256": sha256(model_path),
            "predictions_sha256": sha256(work / "test_predictions.parquet"),
            "reload_max_difference": float(np.max(np.abs(prediction-np.load(work / "reload.npy"))))
        }
        mlflow.log_dict(result, "result.json")
        result["evaluation_purpose"] = evaluation_purpose
        if reproduce_report is not None:
            result.update({
                "reproduction_status": "VERIFIED",
                "reproduced_report": os.path.relpath(original_report_path, ROOT),
                "metric_tolerance": 0.000001,
                "maximum_metric_difference": reproduction_difference,
            })
    (folder / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(scores[["method", "mae", "wmape_pct"]].to_string(index=False))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-report", type=project_path, default=SOURCE, help="Forecast-feature validation report.")
    parser.add_argument("--reference-report", type=project_path, default=REFERENCE, help="Validation-selected model report.")
    parser.add_argument("--verification-report", type=project_path, default=VERIFICATION, help="Successful validation-model reproduction report.")
    parser.add_argument("--reproduce-report", type=project_path, help="Original final-evaluation report for historical reproduction.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    lock_path = ROOT / "artifacts/final_evaluation.lock"
    lock_path.parent.mkdir(exist_ok=True)

    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        existing = list((ROOT / "reports/final_evaluation").glob("*/report.json"))
        if existing and args.reproduce_report is None:
            print(f"Final evaluation already exists: {existing[0]}")
        else:
            run(
                source_report=args.source_report,
                reference_report=args.reference_report,
                verification_report=args.verification_report,
                reproduce_report=args.reproduce_report)