import pandas as pd
import pytest

from score_validation_baselines import summarize


def test_pooled_denominator_and_zero_volume_zone():
    rows = pd.DataFrame({"actual": [0, 2, 8], "forecast": [2, 3, 4], "zone": [1, 2, 2]})
    rows["error"] = (rows.actual - rows.forecast).abs()
    rows["zero"] = rows.actual.eq(0)
    result = summarize(rows, "zone").set_index("zone")
    assert pd.isna(result.loc[1, "wmape_pct"])
    assert result.loc[1, "mae"] == 2
    pooled = summarize(rows.assign(period="pooled"), "period").iloc[0]
    assert pooled.wmape_pct == 70
    assert pooled.mae == pytest.approx(7 / 3)
