"""Report helpers and the single-feature signal table."""

import numpy as np
import pandas as pd

from explore import feature_signal
from report import top_importance


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
