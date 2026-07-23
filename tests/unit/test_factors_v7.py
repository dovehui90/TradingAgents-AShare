"""Tests for tradingagents/yang_yin/factors_v7.py — factor computation.

Tests the two code paths:
  - _compute_factors_from_features (pre-computed feature panel)
  - _compute_factors_raw (raw OHLCV panel)
"""

import numpy as np
import pandas as pd
import pytest

from tradingagents.yang_yin.factors_v7 import (
    FACTOR_NAMES,
    compute_factors,
    _compute_factors_from_features,
    _compute_factors_raw,
)


def _make_feature_panel(n_stocks: int = 20, n_days: int = 30) -> pd.DataFrame:
    """Synthetic feature panel matching DataCollector output format."""
    rng = np.random.default_rng(42)
    rows = []
    for day in range(n_days):
        trade_date = f"2026{str(6 + day // 30).zfill(2)}{str(1 + day % 30).zfill(2)}"
        for s in range(n_stocks):
            close = 10.0 + rng.normal(0, 0.5)
            pct = rng.normal(0, 2.0)
            vol = rng.integers(50_000, 500_000)
            rows.append({
                "ts_code": f"00000{s}.SZ",
                "trade_date": trade_date,
                "close": close,
                "pct_chg": pct,
                "vol": vol,
                "ma5": close + rng.normal(0, 0.1),
                "close_5d": close + rng.normal(0, 0.3),
                "vol_5d": vol + rng.integers(-5000, 5000),
                "prev_vol": vol + rng.integers(-3000, 3000),
                "vol_ma20": vol + rng.integers(-2000, 2000),
                "rsi14": 30.0 + rng.uniform(0, 40),
            })
    df = pd.DataFrame(rows)
    df["trade_date"] = df["trade_date"].astype(str)
    return df


def _make_raw_panel(n_stocks: int = 10, n_days: int = 30) -> pd.DataFrame:
    """Synthetic raw OHLCV panel (no pre-computed features)."""
    rng = np.random.default_rng(99)
    rows = []
    for day in range(n_days):
        trade_date = f"2026{str(6 + day // 30).zfill(2)}{str(1 + day % 30).zfill(2)}"
        for s in range(n_stocks):
            close = 10.0 + rng.normal(0, 0.3)
            pct = rng.normal(0, 1.5)
            vol = rng.integers(50_000, 300_000)
            rows.append({
                "ts_code": f"00000{s}.SZ",
                "trade_date": trade_date,
                "close": close,
                "vol": vol,
                "pct_chg": pct,
            })
    df = pd.DataFrame(rows)
    df["trade_date"] = df["trade_date"].astype(str)
    return df


class TestComputeFactorsFromFeatures:
    """Tests for the fast path: _compute_factors_from_features()."""

    def test_returns_none_for_empty_day(self):
        feat = _make_feature_panel(n_stocks=5, n_days=5)
        result = _compute_factors_from_features(feat, "2099-01-01")
        assert result is None

    def test_output_contains_all_factor_keys(self):
        feat = _make_feature_panel(n_stocks=20, n_days=5)
        trade_date = feat["trade_date"].iloc[-1]
        result = _compute_factors_from_features(feat, trade_date)
        assert result is not None
        for name in FACTOR_NAMES:
            assert name in result, f"Missing factor: {name}"
        assert "prev_yangpu" in result

    def test_factors_in_valid_ranges(self):
        feat = _make_feature_panel(n_stocks=20, n_days=5)
        trade_date = feat["trade_date"].iloc[-1]
        result = _compute_factors_from_features(feat, trade_date)
        assert result is not None
        # Proportion-based factors
        assert 0.0 <= result["trend_mean"] <= 1.0, f"trend_mean={result['trend_mean']}"
        assert 0.0 <= result["trend_yang"] <= 1.0
        assert 0.0 <= result["rsi_yang"] <= 1.0
        # RSI should be in [0, 100]
        assert 0.0 <= result["rsi_mean"] <= 100.0

    def test_prev_yangpu_defaults_to_50(self):
        feat = _make_feature_panel(n_stocks=5, n_days=5)
        trade_date = feat["trade_date"].iloc[-1]
        result = _compute_factors_from_features(feat, trade_date)
        assert result is not None
        assert result["prev_yangpu"] == 50.0

    def test_prev_yangpu_custom_value(self):
        feat = _make_feature_panel(n_stocks=5, n_days=5)
        trade_date = feat["trade_date"].iloc[-1]
        result = _compute_factors_from_features(feat, trade_date, prev_yangpu=72.5)
        assert result is not None
        assert result["prev_yangpu"] == 72.5

    def test_moneyflow_overrides_defaults(self):
        feat = _make_feature_panel(n_stocks=3, n_days=5)
        trade_date = feat["trade_date"].iloc[-1]
        codes = feat[feat["trade_date"] == trade_date]["ts_code"].tolist()
        moneyflow = {codes[0]: 500.0, codes[1]: -200.0, codes[2]: 0.0}
        result = _compute_factors_from_features(feat, trade_date, moneyflow=moneyflow)
        assert result is not None
        assert result["money_mean"] != 0.0
        assert result["money_yang"] != 0.0

    def test_moneyflow_empty_when_none(self):
        feat = _make_feature_panel(n_stocks=5, n_days=5)
        trade_date = feat["trade_date"].iloc[-1]
        result = _compute_factors_from_features(feat, trade_date, moneyflow=None)
        assert result is not None
        assert result["money_mean"] == 0.0
        assert result["money_yang"] == 0.0

    def test_deterministic_output(self):
        feat = _make_feature_panel(n_stocks=10, n_days=5)
        trade_date = feat["trade_date"].iloc[-1]
        result1 = _compute_factors_from_features(feat.copy(), trade_date)
        result2 = _compute_factors_from_features(feat.copy(), trade_date)
        assert result1 == result2


class TestComputeFactorsRaw:
    """Tests for the slow path: _compute_factors_raw()."""

    def test_returns_none_for_missing_date(self):
        panel = _make_raw_panel(n_stocks=5, n_days=5)
        result = _compute_factors_raw(panel, "2099-01-01")
        assert result is None

    def test_output_contains_all_factor_keys(self):
        panel = _make_raw_panel(n_stocks=10, n_days=25)
        trade_date = panel["trade_date"].iloc[-1]
        result = _compute_factors_raw(panel, trade_date)
        assert result is not None
        for name in FACTOR_NAMES:
            assert name in result, f"Missing factor: {name}"
        assert "prev_yangpu" in result

    def test_empty_panel_returns_none(self):
        """Panel with no rows but correct columns → returns None."""
        panel = pd.DataFrame(columns=["ts_code", "trade_date", "close", "vol", "pct_chg"])
        result = _compute_factors_raw(panel, "2026-06-01")
        assert result is None

    def test_single_stock_works(self):
        """One stock with 25 days should compute factors without error."""
        rng = np.random.default_rng(7)
        rows = []
        for day in range(25):
            trade_date = f"2026{str(6 + day // 30).zfill(2)}{str(1 + day % 30).zfill(2)}"
            rows.append({
                "ts_code": "000001.SZ",
                "trade_date": trade_date,
                "close": 10.0 + rng.normal(0, 0.2),
                "vol": 100000 + rng.integers(-10000, 10000),
                "pct_chg": rng.normal(0, 1.0),
            })
        panel = pd.DataFrame(rows)
        panel["trade_date"] = panel["trade_date"].astype(str)
        trade_date = panel["trade_date"].iloc[-1]
        result = _compute_factors_raw(panel, trade_date)
        assert result is not None
        assert 0.0 <= result["rsi_mean"] <= 100.0


class TestComputeFactorsRouter:
    """Test the compute_factors() router function."""

    def test_routes_to_features_path(self):
        """When panel has 'rsi14' column, should use features path."""
        feat = _make_feature_panel(n_stocks=10, n_days=5)
        trade_date = feat["trade_date"].iloc[-1]
        result = compute_factors(feat, trade_date)
        assert result is not None
        assert "rsi_mean" in result

    def test_routes_to_raw_path(self):
        """When panel lacks 'rsi14', should use raw path."""
        panel = _make_raw_panel(n_stocks=10, n_days=25)
        trade_date = panel["trade_date"].iloc[-1]
        result = compute_factors(panel, trade_date)
        assert result is not None
        assert "rsi_mean" in result
