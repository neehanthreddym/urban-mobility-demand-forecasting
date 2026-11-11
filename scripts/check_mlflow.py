"""Log a tracking check, or verify its metadata and artifact after restarting MLflow."""

import argparse
import os

import mlflow

EXPERIMENT = "urban-mobility-demand"
ARTIFACT = "tracking-check.txt"
MESSAGE = "Urban mobility tracking check\n"


def main():
    """Print a new check run ID or verify the run supplied with --verify."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", metavar="RUN_ID")
    args = parser.parse_args()
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5050"))
    if args.verify:
        client = mlflow.MlflowClient()
        run = client.get_run(args.verify)
        experiment = client.get_experiment(run.info.experiment_id)
        content = mlflow.artifacts.load_text(f"runs:/{args.verify}/{ARTIFACT}")
        if (experiment.name != EXPERIMENT or run.info.status != "FINISHED"
                or run.data.params.get("purpose") != "tracking-check" or content != MESSAGE):
            raise ValueError("Stored run metadata or artifact differs from the tracking check")
        print(f"PASS: retrieved run {args.verify} and verified {ARTIFACT}")
        return
    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name="tracking-check") as run:
        mlflow.log_param("purpose", "tracking-check")
        mlflow.log_text(MESSAGE, ARTIFACT)
        print(run.info.run_id)


if __name__ == "__main__":
    main()
