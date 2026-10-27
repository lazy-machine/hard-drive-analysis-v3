"""Report helpers and the single-feature signal table."""

import numpy as np
import pandas as pd

from explore import feature_signal
from report import _drift_sentence, _main_alert, est, side, table, top_importance


def test_top_importance_orders_by_gain_not_name():
    # alphabetical key order, as write_json(sort_keys=True) leaves it
    gain = {"a_small": 1.0, "b_big": 50.0, "c_mid": 9.0, "d_tiny": 0.5, "e_large": 39.5}
    top = top_importance(gain, n=3)
    assert list(top.index) == ["b_big", "e_large", "c_mid"]
    # shares of the total over all features (100), not of the top 3 (98.5)
    assert np.allclose(top.to_numpy(), [0.50, 0.395, 0.09])


def test_top_importance_n_larger_than_features():
    top = top_importance({"x": 3.0, "y": 1.0}, n=20)
    assert list(top.index) == ["x", "y"]
    assert np.isclose(top.sum(), 1.0)


def test_feature_signal_uses_filled_rows_only():
    # group A reports the attribute and it separates perfectly (failing = high);
    # group B never reports it (a vendor with the attribute NULL) and fails just as often
    event = np.array([1, 1, 0, 0, 1, 1, 0, 0])
    meta = pd.DataFrame({"duration_days": np.where(event == 1, 5, 100),
                         "event": event, "weight": np.ones(8)})
    nan = np.nan
    X = np.array([
        # vendor_null, all_missing, filled_only_on_healthy
        [10.0, nan, nan],
        [11.0, nan, nan],
        [1.0, nan, 3.0],
        [2.0, nan, 4.0],
        [nan, nan, nan],
        [nan, nan, nan],
        [nan, nan, 5.0],
        [nan, nan, 6.0],
    ])
    out = feature_signal(meta, X, ["vendor_null", "all_missing", "one_class"], horizon=30)
    out = out.set_index("feature")

    r = out.loc["vendor_null"]
    assert np.isclose(r["fill_rate"], 0.5)
    assert np.isclose(r["auc"], 1.0)
    # missing ranked lowest: A-positives beat all 4 negatives (8 pairs), B-positives tie
    # with B-negatives (4 pairs at 1/2) and lose to A-negatives -> 10/16
    assert np.isclose(r["auc_missing_low"], 10 / 16)
    assert np.isclose(r["separation"], 1.0)
    assert r["higher_means_risk"]

    for f in ("all_missing", "one_class"):
        assert np.isnan(out.loc[f, "auc"])
        assert out.loc[f, "separation"] == 0.0
    assert np.isclose(out.loc["one_class", "auc_missing_low"], 0.0)
    assert out.index[0] == "vendor_null"


def test_est_handles_missing_and_nan_intervals():
    assert est(0.8571, [0.8372, 0.8811]) == "0.857 [0.837, 0.881]"
    assert est(0.8571) == "0.857"                       # metric without an interval
    assert est(0.8571, [None, None]) == "0.857 [n/a]"   # interval not estimable
    assert est(0.8571, [float("nan"), 0.9]) == "0.857 [n/a]"
    assert est(None, [0.1, 0.2]) == "n/a [0.100, 0.200]"
    assert est(float("nan"), None) == "n/a"
    assert est(0.0123, [0.01, 0.015], 2, pct=True) == "1.23% [1.00%, 1.50%]"
    assert est(0.05, [-0.01, 0.1], sign=True) == "+0.050 [-0.010, 0.100]"
    assert est(-0.05, None, sign=True) == "-0.050"


def test_side_of_interval():
    assert side([0.01, 0.2]) == 1
    assert side([-0.2, -0.01]) == -1
    assert side([-0.01, 0.2]) == 0
    assert side([None, None]) == 0 and side(None) == 0
    assert side([0.51, 0.7], at=0.5) == 1


def test_table_formats_none_cells():
    assert table(["a", "b"], [[1, None]]) == ["| a | b |", "|---|---|", "| 1 | n/a |"]


def test_main_alert_uses_main_budget_not_first_row():
    rows = [{"model": "m", "budget": b, "horizon": 30} for b in (0.001, 0.003, 0.01)]
    metrics = {"alerting": rows, "alert_false_alarm_rate": 0.01}
    assert _main_alert(metrics, "m")["budget"] == 0.01


def test_drift_sentence_names_outside_years():
    row = {"val_band": [0.9, 1.1], "last_val_year": 2023, "last_val_ratio": 1.3,
           "last_val_year_outside_earlier_band": True,
           "test_years": [{"year": 2024, "outside_band": True},
                          {"year": 2025, "outside_band": False}]}
    s = _drift_sentence(row, "ref")
    assert "0.90 to 1.10" in s and "(2023, ratio 1.30) is outside" in s
    assert "Test years outside the band: 2024." in s
    row["test_years"] = [{"year": 2024, "outside_band": False}]
    row["last_val_year_outside_earlier_band"] = False
    assert "No test year falls outside" in _drift_sentence(row, "ref")
