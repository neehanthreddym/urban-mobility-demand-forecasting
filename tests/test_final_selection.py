import pandas as pd

from evaluate_final_test import check_guardrails


def test_zero_baseline_retains_baseline():
    gain, _, qualified = check_guardrails(0, 0, pd.DataFrame({"mae": [0], "baseline_mae": [0]}))
    assert gain == 0 and not qualified


def test_busy_zone_with_zero_error_requires_zero_candidate_error():
    _, passed, qualified = check_guardrails(9, 10, pd.DataFrame({"mae": [0.1], "baseline_mae": [0.]}))
    assert not passed.iloc[0] and not qualified


def test_one_failing_zone_blocks_overall_improvement():
    _, passed, qualified = check_guardrails(8, 10, pd.DataFrame({"mae": [0, 12], "baseline_mae": [0, 10]}))
    assert passed.tolist() == [True, False] and not qualified
