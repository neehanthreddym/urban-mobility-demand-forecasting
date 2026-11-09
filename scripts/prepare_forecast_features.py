"""Prepare the charter's fixed time splits and as-of features for hourly replay."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from utils import ROOT, TZ, sha256

SOURCE = ROOT / "reports/data_preparation/april_june_2025/20261108T062052975430Z/report.json"
KEY = ["pickup_zone_id", "hour_start"]
LAGS = (2, 3, 24, 48, 168)
WINDOWS = (3, 24, 168)
START = pd.Timestamp("2025-04-01", tz=TZ)
END = pd.Timestamp("2025-07-01", tz=TZ)
FIRST_TARGET = START + pd.Timedelta(hours=169)
VALIDATION = pd.Timestamp("2025-06-01", tz=TZ)
TEST = pd.Timestamp("2025-06-15", tz=TZ)
HOUR = pd.Timedelta(hours=1)


def prepare(panel):
    """Build features using only own-zone observations available at each origin.

    Args:
        panel: Complete April–June zone-hour grid with recorded pickup counts.

    Output:
        Sorted panel with calendar features, lags, trailing means, split roles,
        and an overlapping eligibility flag for the June 15 refit.
    """
    frame = panel.sort_values(KEY, ignore_index=True).copy()
    t = frame["hour_start"]
    zones = frame["pickup_zone_id"]
    y = frame["pickup_count"]
    if (frame.empty or frame[KEY + ["pickup_count"]].isna().any().any()
            or str(t.dt.tz) != TZ or not pd.api.types.is_integer_dtype(y) or y.lt(0).any()):
        raise ValueError("Expected complete NYC-local keys and nonnegative integer counts")
    calendar = pd.date_range(START, END, freq="h", inclusive="left")
    expected = pd.MultiIndex.from_product([zones.unique(), calendar], names=KEY)
    if not pd.MultiIndex.from_frame(frame[KEY]).equals(expected):
        raise ValueError("Each zone needs exactly one row per study hour before shifting")

    frame["hour"] = t.dt.hour
    frame["day_of_week"] = t.dt.day_of_week
    frame["is_weekend"] = frame["day_of_week"].ge(5)
    frame["pickup_zone_id"] = zones.astype("category")
    by_zone = y.groupby(zones, sort=False)
    history = []
    for lag in LAGS:
        col = f"lag_{lag}"
        frame[col] = by_zone.shift(lag)
        history.append(col)
    available = frame["lag_2"].groupby(zones, sort=False)
    for width in WINDOWS:
        col = f"mean_{width}_ending_lag_2"
        frame[col] = available.rolling(width, min_periods=width).mean().droplevel(0)
        history.append(col)

    frame["split"] = "warmup"
    frame.loc[t.between(FIRST_TARGET, VALIDATION - HOUR, inclusive="left"), "split"] = "train"
    frame.loc[t.between(VALIDATION, TEST - HOUR, inclusive="left"), "split"] = "validation"
    frame.loc[t.isin([VALIDATION - HOUR, TEST - HOUR]), "split"] = "embargo"
    frame.loc[t.ge(TEST), "split"] = "test"
    frame["refit_eligible"] = t.between(FIRST_TARGET, TEST - HOUR, inclusive="left")
    if frame.loc[t.ge(FIRST_TARGET), history].isna().any().any():
        raise ValueError("Missing lagged history for eligible forecast origins")
    return frame


def main():
    """Verify the combined snapshot and save the feature table and provenance.

    Output:
        Timestamped local Parquet table and aggregate JSON validation report.
    """
    source = json.loads(SOURCE.read_text())
    dataset = ROOT / source["dataset_path"]
    if source["status"] != "VALIDATED" or sha256(dataset) != source["dataset_sha256"]:
        raise ValueError("Combined snapshot differs from the validated input")
    frame = prepare(pd.read_parquet(dataset))
    if len(frame) != source["rows"] or frame["pickup_zone_id"].nunique() != source["zones"]:
        raise ValueError("Feature grid differs from the combined report")
    folder = Path("forecast_features") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "data/processed" / folder / "features.parquet"
    report_path = ROOT / "reports/data_preparation" / folder / "report.json"
    output.parent.mkdir(parents=True, exist_ok=False)
    frame.to_parquet(output, index=False, compression="zstd")
    restored = pd.read_parquet(output)
    # Arrow may restore integer-valued dictionary columns as their integer values.
    restored["pickup_zone_id"] = restored["pickup_zone_id"].astype("category")
    pd.testing.assert_frame_equal(frame, restored)
    report = {"status": "VALIDATED", "rows": len(frame),
              "source_report": str(SOURCE.relative_to(ROOT)), "source_report_sha256": sha256(SOURCE),
              "source_sha256": source["dataset_sha256"], "script_sha256": sha256(Path(__file__)),
              "dataset_path": str(output.relative_to(ROOT)), "dataset_sha256": sha256(output),
              "categorical_features": ["pickup_zone_id"],
              "predictors": ["pickup_zone_id", "hour", "day_of_week", "is_weekend"]
                            + [f"lag_{lag}" for lag in LAGS]
                            + [f"mean_{w}_ending_lag_2" for w in WINDOWS],
              "split_rows": frame["split"].value_counts().to_dict(),
              "refit_eligible_rows": int(frame["refit_eligible"].sum()),
              "timezone_assumption": TZ, "reporting_delay_after_close_hours": 1}
    report_path.parent.mkdir(parents=True, exist_ok=False)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["split_rows"], indent=2))
    print(f"VALIDATED: {report_path}")


if __name__ == "__main__":
    main()
