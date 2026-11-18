import pandas as pd
import json
from pathlib import Path
import pytest
from evaluate_final_test import check_frozen_protocol, check_guardrails, check_reproduction_metrics


def test_zero_baseline_retains_baseline():
    gain, _, qualified = check_guardrails(0, 0, pd.DataFrame({"mae": [0], "baseline_mae": [0]}))
    assert gain == 0 and not qualified

def test_busy_zone_with_zero_error_requires_zero_candidate_error():
    _, passed, qualified = check_guardrails(9, 10, pd.DataFrame({"mae": [0.1], "baseline_mae": [0.]}))
    assert not passed.iloc[0] and not qualified

def test_one_failing_zone_blocks_overall_improvement():
    _, passed, qualified = check_guardrails(8, 10, pd.DataFrame({"mae": [0, 12], "baseline_mae": [0, 10]}))
    assert passed.tolist() == [True, False] and not qualified

@pytest.fixture
def frozen_protocol():
    """Load the committed June benchmark protocol for replay checks."""
    project_root = Path(__file__).resolve().parents[1]
    report_path = (project_root / "reports/final_evaluation" / "71dcb809d5c0409484d8b55b21751f17" / "protocol.json")
    return json.loads(report_path.read_text())

def test_historical_replay_accepts_matching_protocol(frozen_protocol):
    assert check_frozen_protocol(
        frozen_protocol.copy(), frozen_protocol
    ) is None

@pytest.mark.parametrize(
    "field, changed_value",
    [
        ("rounds", 501),
        ("params", {"objective": "regression"}),
        ("source_sha256", "0" * 64),
        ("test_start", "2025-06-16T00:00:00-04:00"),
    ],
)
def test_historical_replay_rejects_changed_protocol(frozen_protocol, field, changed_value):
    current = frozen_protocol.copy()
    current[field] = changed_value
    with pytest.raises(ValueError, match=field):
        check_frozen_protocol(current, frozen_protocol)

def test_historical_replay_rejects_missing_field(frozen_protocol):
    current = frozen_protocol.copy()
    del current["features"]
    with pytest.raises(ValueError, match="features"):
        check_frozen_protocol(current, frozen_protocol)

@pytest.fixture
def historical_metrics():
    return pd.DataFrame({
        "method": ["lightgbm", "weekly"],
        "mae": [4.0, 5.0],
        "wmape_pct": [20.0, 25.0],
    })

def test_reproduction_matches_by_method(historical_metrics):
    reordered = historical_metrics.iloc[::-1].copy()
    difference = check_reproduction_metrics(reordered, historical_metrics)
    assert difference == 0.0

def test_reproduction_rejects_changed_scores(historical_metrics):
    changed = historical_metrics.copy()
    changed.loc[0, "wmape_pct"] += 0.01
    with pytest.raises(ValueError, match="tolerance"):
        check_reproduction_metrics(changed, historical_metrics)

def test_reproduction_rejects_missing_method(historical_metrics):
    incomplete = historical_metrics.iloc[:1].copy()
    with pytest.raises(ValueError, match="methods"):
        check_reproduction_metrics(incomplete, historical_metrics)