import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
pytest.importorskip("pyspark")

from pyspark.sql import SparkSession, functions as F
from build_spark_zone_hour import build_counts


@pytest.fixture(scope="module")
def spark():
    os.environ["PYSPARK_PYTHON"] = sys.executable
    session = (
        SparkSession.builder
        .master("local[2]")
        .appName("zone-hour-transformation-tests")
        .config("spark.sql.session.timeZone", "America/New_York")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate()
    )
    session.sparkContext.setLogLevel("ERROR")

    try:
        yield session
    finally:
        session.stop()


def test_monthly_counts_preserve_records_and_complete_grid(spark):
    trips = spark.createDataFrame(
        [
            (datetime(2025, 4, 1), 2),
            (datetime(2025, 4, 1), 2),
            (datetime(2025, 4, 30, 23, 59, 59), 2),
            (datetime(2025, 3, 31, 23, 59, 59), 2),
            (datetime(2025, 5, 1), 3),
            (datetime(2025, 4, 1), 264),
            (datetime(2025, 4, 1), None),
            (None, 2),
        ],
        schema="tpep_pickup_datetime timestamp_ntz, PULocationID int",
    )

    result = build_counts(spark, trips, {2, 3}, "2025-04")

    rows = result.select(
        "pickup_zone_id",
        F.date_format(
            "hour_start", "yyyy-MM-dd HH:mm:ss"
        ).alias("local_hour"),
        F.unix_micros("hour_start").alias("epoch_us"),
        "pickup_count",
    ).collect()

    expected = {
        (
            zone,
            (datetime(2025, 4, 1) + timedelta(hours=hour))
            .strftime("%Y-%m-%d %H:%M:%S"),
        ): 0
        for zone in (2, 3)
        for hour in range(720)
    }
    expected[(2, "2025-04-01 00:00:00")] = 2
    expected[(2, "2025-04-30 23:00:00")] = 1

    actual = {
        (row["pickup_zone_id"], row["local_hour"]): row["pickup_count"]
        for row in rows
    }

    assert len(rows) == 1_440
    assert actual == expected

    first_hour = next(
        row for row in rows
        if row["pickup_zone_id"] == 2
        and row["local_hour"] == "2025-04-01 00:00:00"
    )
    expected_epoch = int(datetime(2025, 4, 1, 4, tzinfo=timezone.utc).timestamp()) * 1_000_000

    assert first_hour["epoch_us"] == expected_epoch


def test_rejects_timezone_aware_source_type(spark):
    trips = spark.createDataFrame(
        [(datetime(2025, 4, 1, tzinfo=timezone.utc), 2)],
        schema="tpep_pickup_datetime timestamp, PULocationID int",
    )
    with pytest.raises(ValueError, match="timestamp_ntz"):
        build_counts(spark, trips, {2}, "2025-04")