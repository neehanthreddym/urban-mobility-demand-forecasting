import pandas as pd
import pytest

from create_planning_outputs import planning_table
from prepare_forecast_features import FIRST_TARGET, VALIDATION


def test_strict_flags_competition_ranks_and_training_reference():
    train = pd.DataFrame({"pickup_zone_id": [1]*10+[2]*10,
                          "hour_start": [FIRST_TARGET]*20, "pickup_count": [10]*10+[0]*10})
    predictions = pd.DataFrame({"pickup_zone_id": [1, 2], "hour_start": [VALIDATION]*2,
                                "lightgbm": [10., 10.]})
    result = planning_table(predictions, train)
    assert result.training_p90.tolist() == [10, 0]
    assert result.high_demand_flag.tolist() == [False, True]
    assert result.forecast_rank.tolist() == [1, 1]


def test_validation_targets_cannot_enter_training_reference():
    train = pd.DataFrame({"pickup_zone_id": [1], "hour_start": [VALIDATION], "pickup_count": [9999]})
    with pytest.raises(ValueError, match="outside initial training"):
        planning_table(pd.DataFrame(), train)
