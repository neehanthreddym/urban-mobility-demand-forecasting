"""Reproduce the selected validation fit and verify an MLflow model in a fresh process."""

import argparse
import ast
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

from utils import ROOT, project_path, sha256
from validate_lightgbm import BASE, load_validation_inputs
from score_validation_baselines import SOURCE

REFERENCE = ROOT / "reports/lightgbm_validation/20261111T055534905760Z/report.json"
TOLERANCE = 0.000001
LOGGER = logging.getLogger(__name__)


def audit_original_script():
    """Recover the exact original training script from its known formatting edit.

    Output:
        Original script text, current hash and a verified formatting-only comparison.
        Raises ValueError if the recovered source differs from the recorded hash.
    """
    path = ROOT / "scripts/validate_lightgbm.py"
    # The committed starting point is captured separately before shared-loader extraction.
    snapshot = ROOT / "reports/reproducibility/validation_script_before_tracking.py"
    text = snapshot.read_text()
    start = text.index("    model = lgb.train(")
    stop = text.index("    predictions =", start)
    original = text[:start] + (
        "    model = lgb.train(params, training, num_boost_round=500, valid_sets=[validation],\n"
        "                      callbacks=[lgb.early_stopping(50, verbose=False)])\n"
    ) + text[stop:]
    reference = json.loads(REFERENCE.read_text())
    import hashlib
    if (hashlib.sha256(original.encode()).hexdigest() != reference["script_sha256"]
            or ast.dump(ast.parse(original)) != ast.dump(ast.parse(text))):
        raise ValueError("Original script fingerprint/formatting audit failed")
    return original, {"original_sha256": reference["script_sha256"],
                      "before_tracking_sha256": sha256(snapshot),
                      "current_validation_script_sha256": sha256(path),
                      "formatting_only_original_difference": True}


def main():
    """Train the frozen setting, log its artifacts and verify model reload parity.

    Output:
        MLflow run with model, curves, schema, validation predictions and verification.
        A versionable report is written only after every comparison succeeds.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracking-uri", default=os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5050"))
    parser.add_argument("--source-report", default=str(SOURCE), help="Forecast-feature validation report.")
    parser.add_argument("--baseline-report", default=str(BASE), help="Baseline results for the selected feature report.")
    parser.add_argument("--reference-report", default=str(REFERENCE), help="LightGBM validation report to reproduce.")
    args = parser.parse_args()
    source_path = project_path(args.source_report)
    baseline_path = project_path(args.baseline_report)
    reference_path = project_path(args.reference_report)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    original, audit = audit_original_script()
    reference = json.loads(reference_path.read_text())
    source, base, train, valid = load_validation_inputs(source_path, baseline_path)
    if reference["source_sha256"] != source["dataset_sha256"] or sha256(baseline_path) != reference["baseline_report_sha256"]:
        raise ValueError("Reference experiment uses different inputs")
    features = reference["features"]
    if features != source["predictors"]:
        raise ValueError("Predictor order differs from reference")
    settings = reference["best_candidate"]
    params = dict(reference["params"], num_leaves=settings["num_leaves"],
                  min_child_samples=settings["min_child_samples"])
    mlflow.set_tracking_uri(args.tracking_uri)
    mlflow.set_experiment("urban-mobility-demand")
    with mlflow.start_run(run_name="reproduce-selected-validation") as run, TemporaryDirectory() as temporary:
        work = Path(temporary)
        mlflow.set_tags({"stage": "validation-reproduction",
                         "reference_experiment": reference["experiment_id"]})
        mlflow.log_params(dict(params, num_boost_round=reference["max_rounds"],
                               early_stopping_rounds=reference["early_stopping_rounds"]))
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        provenance = dict(audit,
                          git_revision=revision,
                          source_sha256=source["dataset_sha256"],
                          source_report=os.path.relpath(source_path, ROOT),
                          source_report_sha256=sha256(source_path),
                          baseline_report=os.path.relpath(baseline_path, ROOT),
                          baseline_report_sha256=sha256(baseline_path),
                          lockfile_sha256=sha256(ROOT / "uv.lock"),
                          reference_report=os.path.relpath(reference_path, ROOT),
                          reference_report_sha256=sha256(reference_path),
                          historical_script_reference_report=os.path.relpath(REFERENCE, ROOT),
                          platform=platform.platform(),
                          python=sys.version, lightgbm=lgb.__version__, mlflow=mlflow.__version__,
                          training_rows=len(train), validation_rows=len(valid),
                          validation_start=reference["validation_start"],
                          validation_end_exclusive=reference["validation_end_exclusive"],
                          training_start=str(train.hour_start.min()),
                          training_last_hour=str(train.hour_start.max()),
                          reproduction_script_sha256=sha256(Path(__file__)))
        mlflow.log_dict(provenance, "provenance.json")
        mlflow.log_text(original, "source/original_training_script.py")
        for file in (Path(__file__), ROOT / "scripts/validate_lightgbm.py", ROOT / "scripts/utils.py",
                     ROOT / "scripts/prepare_forecast_features.py", ROOT / "uv.lock", ROOT / "pyproject.toml"):
            mlflow.log_artifact(str(file), artifact_path="source")
        schema = {"features": features, "dtypes": {c: str(train[c].dtype) for c in features},
                  "zone_categories": [int(z) for z in train.pickup_zone_id.cat.categories]}
        mlflow.log_dict(schema, "feature_schema.json")
        history = {}
        LOGGER.info("Fitting frozen configuration on %s training rows", len(train))
        training = lgb.Dataset(train[features], label=train.pickup_count, categorical_feature=["pickup_zone_id"])
        validation = lgb.Dataset(valid[features], label=valid.pickup_count, reference=training)
        model = lgb.train(params, training, num_boost_round=reference["max_rounds"],
                          valid_sets=[validation], valid_names=["validation"],
                          callbacks=[lgb.early_stopping(reference["early_stopping_rounds"], verbose=False),
                                     lgb.record_evaluation(history)])
        prediction = model.predict(valid[features], num_iteration=model.best_iteration, num_threads=4)
        if not np.isfinite(prediction).all() or (prediction < 0).any():
            raise ValueError("Invalid predictions")
        error = np.abs(valid.pickup_count.to_numpy() - prediction)
        metrics = {"mae": float(error.mean()), "wmape_pct": float(100 * error.sum() / valid.pickup_count.sum())}
        mlflow.log_metrics(metrics)
        mlflow.log_param("best_iteration", model.best_iteration)
        for step, mae in enumerate(history["validation"]["l1"], start=1):
            mlflow.log_metric("validation_mae_history", mae, step=step)
        mlflow.log_dict(history, "training_history.json")
        if model.best_iteration != settings["iterations"] or any(
                abs(metrics[k] - settings[k]) > TOLERANCE for k in metrics):
            raise ValueError(f"Reference metrics did not reproduce within {TOLERANCE}: {metrics}")
        model.save_model(str(work / "model.txt"), num_iteration=model.best_iteration)
        mlflow.log_artifact(str(work / "model.txt"), artifact_path="model")
        model_uri = f"runs:/{run.info.run_id}/model/model.txt"
        forecasts = valid[["pickup_zone_id", "hour_start", "pickup_count"]].copy()
        forecasts["forecast"] = prediction
        forecasts.to_parquet(work / "validation_predictions.parquet", index=False)
        valid[features].to_parquet(work / "reload_inputs.parquet", index=False)
        mlflow.log_artifact(str(work / "validation_predictions.parquet"))
        # The child downloads and loads the logged model using a new Python interpreter.
        child = """
import sys, mlflow.artifacts, lightgbm as lgb, pandas as pd, numpy as np
path = mlflow.artifacts.download_artifacts(artifact_uri=sys.argv[1])
model = lgb.Booster(model_file=path)
inputs = pd.read_parquet(sys.argv[2])
schema = __import__('json').loads(sys.argv[4])
inputs['pickup_zone_id'] = pd.Categorical(inputs.pickup_zone_id, categories=schema['zone_categories'])
np.save(sys.argv[3], model.predict(inputs[schema['features']], num_threads=4))
"""
        env = dict(os.environ, MLFLOW_TRACKING_URI=args.tracking_uri)
        subprocess.run([sys.executable, "-c", child, model_uri, str(work / "reload_inputs.parquet"),
                        str(work / "reloaded.npy"), json.dumps(schema)], env=env, check=True, cwd=ROOT)
        delta = float(np.max(np.abs(prediction - np.load(work / "reloaded.npy"))))
        if delta > TOLERANCE:
            raise ValueError(f"Reloaded model prediction difference exceeds tolerance: {delta}")
        result = dict(provenance, run_id=run.info.run_id, model_uri=model_uri,
                      metrics=metrics, iterations=model.best_iteration, feature_schema=schema,
                      metric_tolerance=TOLERANCE, reload_max_absolute_difference=delta,
                      status="VERIFIED", tracking_uri=args.tracking_uri)
        mlflow.log_metric("reload_max_absolute_difference", delta)
        mlflow.log_dict(result, "verification.json")
        # Store the evidence locally after the MLflow run closes successfully.
    folder = ROOT / "reports/reproducibility" / result["run_id"]
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    LOGGER.info("VERIFIED run %s; MAE %.9f, WMAPE %.9f%%; reload difference %.9f",
                result["run_id"], metrics["mae"], metrics["wmape_pct"], delta)


if __name__ == "__main__":
    main()
