"""Build complete monthly zone-hour pickup counts with Spark."""

from pyspark.sql import DataFrame, SparkSession, functions as F
from pyspark.sql.types import TimestampNTZType
from utils import (
    ROOT,
    TZ,
    month_bounds,
    project_path,
    read_lookup,
    sha256,
    verify_input,
)
import argparse
import json
import platform
from datetime import datetime, timezone
from importlib.metadata import version


def build_counts(spark: SparkSession, trips: DataFrame, zone_ids: set[int], month: str) -> DataFrame:
    """Aggregate accepted pickups and retain zero-count zone-hours.

    zone_ids must come from the project's validated NYC lookup.
    Source timestamps retain recorded clock values and are interpreted
    under the project's explicit New York timezone assumption.
    """
    start, end = month_bounds(month)

    if spark.conf.get("spark.sql.session.timeZone") != TZ:
        raise ValueError(f"Spark session timezone must be {TZ}")

    if not isinstance(trips.schema["tpep_pickup_datetime"].dataType, TimestampNTZType):
        raise ValueError("Raw pickup timestamps must be timestamp_ntz")

    if not zone_ids:
        raise ValueError("The validated NYC zone set is empty")

    zones = spark.createDataFrame([(zone_id,) for zone_id in sorted(zone_ids)], schema="pickup_zone_id long")

    pickup = F.col("tpep_pickup_datetime")
    start_clock = F.lit(start.isoformat()).cast("timestamp_ntz")
    end_clock = F.lit(end.isoformat()).cast("timestamp_ntz")

    accepted = (
        trips.select("tpep_pickup_datetime", "PULocationID")
        .filter((pickup >= start_clock) & (pickup < end_clock))
        .join(
            F.broadcast(zones),
            F.col("PULocationID") == F.col("pickup_zone_id"),
            "inner",
        )
    )

    counts = (
        accepted.withColumn(
            "hour_start",
            F.date_trunc("hour", pickup.cast("timestamp_ltz")),
        )
        .groupBy("pickup_zone_id", "hour_start")
        .agg(F.count("*").alias("pickup_count"))
    )

    hours = spark.range(1).select(
        F.explode(
            F.sequence(
                F.lit(start.isoformat()).cast("timestamp_ltz"),
                F.lit(end.isoformat()).cast("timestamp_ltz")
                - F.expr("INTERVAL 1 HOUR"),
                F.expr("INTERVAL 1 HOUR"),
            )
        ).alias("hour_start")
    )

    return (
        zones.crossJoin(hours)
        .join(counts, ["pickup_zone_id", "hour_start"], "left")
        .fillna({"pickup_count": 0})
        .select("pickup_zone_id", "hour_start", "pickup_count")
    )

def main():
    parser = argparse.ArgumentParser(description="Verify inputs for monthly Spark zone-hour preparation.")
    parser.add_argument("--month", required=True, choices=[f"2025-{month:02d}" for month in range(4, 10)])
    parser.add_argument("--reference-report", required=True, type=project_path, help="Validated monthly preparation report to reproduce.")
    args = parser.parse_args()

    start, end = month_bounds(args.month)
    manifest_path = ROOT / "data/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    trips_path = ROOT / f"data/raw/yellow_tripdata_{args.month}.parquet"
    lookup_path = ROOT / "data/reference/taxi_zone_lookup.csv"

    inputs = [verify_input(path, manifest["files"]) for path in (trips_path, lookup_path)]

    reference = json.loads(args.reference_report.read_text(encoding="utf-8"))
    if reference.get("status") != "VALIDATED":
        raise ValueError("The reference report must be VALIDATED")

    configuration = reference["configuration"]
    expected_configuration = {
        "start_inclusive": start.tz_localize(TZ).isoformat(),
        "end_exclusive": end.tz_localize(TZ).isoformat(),
        "timezone_assumption": TZ,
    }
    for field, expected in expected_configuration.items():
        if configuration.get(field) != expected:
            raise ValueError(f"Reference configuration differs: {field}")

    current_inputs = sorted((item["sha256"], item["size_bytes"]) for item in inputs)
    reference_inputs = sorted((item["sha256"], item["size_bytes"]) for item in reference["inputs"])
    if current_inputs != reference_inputs:
        raise ValueError("Reference input fingerprints differ")

    reference_path = project_path(reference["dataset_path"])
    if sha256(reference_path) != reference["dataset_sha256"]:
        raise ValueError("Reference dataset fingerprint differs")

    _, zone_ids = read_lookup(lookup_path)
    if len(zone_ids) != 262:
        raise ValueError("Expected exactly 262 validated NYC zones")

    hours = int((end - start).total_seconds() / 3600)
    expected_shape = {
        "zones": len(zone_ids),
        "hours_per_zone": hours,
        "rows": len(zone_ids) * hours,
    }
    for field, expected in expected_shape.items():
        if reference.get(field) != expected:
            raise ValueError(f"Reference dimensions differ: {field}")

    print(f"Month: {args.month}")
    print("Source and lookup fingerprints: PASS")
    print("Reference dataset fingerprint: PASS")
    print(f"Expected zone-hours: {reference['rows']:,}")
    print("Input verification: PASS")

    run_at = datetime.now(timezone.utc)
    run_id = run_at.strftime("%Y%m%dT%H%M%S%fZ")
    report = {
        "status": "STARTED",
        "purpose": "Reproduce monthly pickup counts with Spark",
        "month": args.month,
        "run_at_utc": run_at.isoformat(),
        "inputs": inputs,
        "manifest_sha256": sha256(manifest_path),
        "reference_report": str(args.reference_report.relative_to(ROOT)),
        "reference_report_sha256": sha256(args.reference_report),
        "reference_dataset_path": reference["dataset_path"],
        "reference_dataset_sha256": reference["dataset_sha256"],
        "script_sha256": sha256(ROOT / "scripts/build_spark_zone_hour.py"),
        "shared_validation_script_sha256": sha256(ROOT / "scripts/utils.py"),
        "lockfile_sha256": sha256(ROOT / "uv.lock"),
        "configuration": expected_configuration,
    }
    events = ROOT / "artifacts/spark/events"
    events.mkdir(parents=True, exist_ok=True)
    spark = (
        SparkSession.builder
        .master("local[2]")
        .appName(f"zone-hours-{args.month}")
        .config("spark.sql.session.timeZone", TZ)
        .config("spark.sql.parquet.inferTimestampNTZ.enabled", "true")
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.eventLog.enabled", "true")
        .config("spark.eventLog.dir", str(events))
        .getOrCreate()
    )
    try:
        spark.sparkContext.setLogLevel("ERROR")
        spark.sparkContext.setJobGroup(
            f"prepare-{args.month}",
            f"Build and verify complete zone-hours for {args.month}",
        )
        trips = spark.read.parquet(str(trips_path))
        actual = build_counts(spark, trips, zone_ids, args.month).cache()
        columns = ["pickup_zone_id", "hour_start", "pickup_count"]
        expected = spark.read.parquet(str(reference_path)).select(*columns)
        summary = actual.agg(
            F.count("*").alias("rows"),
            F.sum("pickup_count").alias("accepted_pickups"),
            F.sum(F.when(F.col("pickup_count") == 0, 1).otherwise(0)).alias("zero_observed_zone_hours"),
        ).first().asDict()
        for field, observed in summary.items():
            if observed != reference[field]:
                raise ValueError(f"{field} differs: Spark={observed}, reference={reference[field]}")

        if actual.exceptAll(expected).limit(1).count():
            raise ValueError("Spark result contains different or extra rows")

        if expected.exceptAll(actual).limit(1).count():
            raise ValueError("Spark result is missing reference rows")

        application_id = spark.sparkContext.applicationId
        report.update({
            "status": "VERIFIED",
            **expected_shape,
            **summary,
            "exact_comparison_passed": True,
            "application_id": application_id,
            "history_url": (f"http://localhost:18080/history/{application_id}/jobs/"),
            "event_log_directory": str(events.relative_to(ROOT)),
            "environment": {
                "python": platform.python_version(),
                "spark": spark.version,
                "pyspark": version("pyspark"),
                "pandas": version("pandas"),
                "pyarrow": version("pyarrow"),
                "java": (spark.sparkContext._jvm.java.lang.System.getProperty("java.version")),
            },
            "limitations": [
                "Source timezone semantics remain a D05 assumption.",
                "Full-row trip duplicates and unrelated anomalies "
                "have not been profiled.",
                "Observed counts do not prove source completeness.",
                "Spark pandas integration has not been validated.",
            ],
        })
    finally:
        spark.stop()

    report_dir = (ROOT / "reports/data_preparation/spark/monthly" / args.month / run_id)
    report_dir.mkdir(parents=True, exist_ok=False)
    report_path = report_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"Zone-hours: {summary['rows']:,}")
    print(f"Accepted pickups: {summary['accepted_pickups']:,}")
    print("Exact table comparison: PASS")
    print(f"Report: {report_path}")
    print(f"History: {report['history_url']}")


if __name__ == "__main__":
    main()