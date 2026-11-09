import pandas as pd
import pytest

from prepare_forecast_features import END, FIRST_TARGET, HOUR, START, TEST, TZ, VALIDATION, prepare


def panel():
    hours = pd.date_range(START, END, freq="h", inclusive="left")
    return pd.concat([pd.DataFrame({"hour_start": hours, "pickup_zone_id": z,
                                    "pickup_count": range(z * 10000, z * 10000 + len(hours))})
                      for z in (1, 2)], ignore_index=True)


def test_split_edges_and_refit_availability():
    rows = prepare(panel()).query("pickup_zone_id == 1").set_index("hour_start")
    for hour, role in [(FIRST_TARGET - HOUR, "warmup"), (FIRST_TARGET, "train"),
                       (VALIDATION - 2 * HOUR, "train"), (VALIDATION - HOUR, "embargo"),
                       (VALIDATION, "validation"), (TEST - 2 * HOUR, "validation"),
                       (TEST - HOUR, "embargo"), (TEST, "test"), (END - HOUR, "test")]:
        assert rows.loc[hour, "split"] == role
    assert rows.loc[VALIDATION - HOUR, "refit_eligible"]
    assert rows.index[rows.refit_eligible].max() == TEST - 2 * HOUR
    assert rows.index[rows.refit_eligible].min() == FIRST_TARGET


def test_lags_and_means_at_first_target_and_month_boundaries():
    rows = prepare(panel().sample(frac=1, random_state=42)).set_index(["pickup_zone_id", "hour_start"])
    for zone in (1, 2):
        zone_rows = rows.loc[zone]
        assert pd.isna(zone_rows.loc[FIRST_TARGET - HOUR, "mean_168_ending_lag_2"])
        for t in (FIRST_TARGET, pd.Timestamp("2025-05-01", tz=TZ), VALIDATION, TEST + HOUR):
            for lag in (2, 3, 24, 48, 168):
                assert zone_rows.loc[t, f"lag_{lag}"] == zone_rows.loc[t - lag * HOUR, "pickup_count"]
            for width in (3, 24, 168):
                values = zone_rows.loc[t - (width + 1) * HOUR:t - 2 * HOUR, "pickup_count"]
                assert zone_rows.loc[t, f"mean_{width}_ending_lag_2"] == values.mean()


def test_unavailable_observations_cannot_change_origin_features():
    data = panel()
    original = prepare(data)
    data.loc[data.hour_start.ge(TEST - HOUR), "pickup_count"] += 999
    changed = prepare(data)
    mask = original.hour_start.eq(TEST)
    cols = original.filter(regex="^(lag_|mean_)").columns
    pd.testing.assert_frame_equal(original.loc[mask, cols], changed.loc[mask, cols])


def test_gap_with_offsetting_duplicate_rejected():
    data = panel()
    data.loc[1, "hour_start"] = data.loc[0, "hour_start"]
    with pytest.raises(ValueError, match="one row"):
        prepare(data)
