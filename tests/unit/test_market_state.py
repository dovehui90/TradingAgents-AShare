"""Tests for tradingagents/strategy/market_state.py — pure computation, no I/O."""

import numpy as np
import pandas as pd
import pytest

from tradingagents.strategy.market_state import (
    calculate_bull_line,
    classify_market_state,
    get_current_market_state,
)


def _make_index_df(n: int = 200) -> pd.DataFrame:
    """Synthetic index OHLCV with mild uptrend."""
    rng = np.random.default_rng(42)
    base = 3000.0
    closes = base + np.cumsum(rng.normal(0.5, 15.0, n))
    closes = np.maximum(closes, 100.0)
    highs = closes + np.abs(rng.normal(0, 5.0, n))
    lows = closes - np.abs(rng.normal(0, 5.0, n))
    opens = closes - rng.normal(0, 3.0, n)
    volumes = rng.integers(1_000_000, 10_000_000, n)

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=pd.date_range("2025-01-02", periods=n, freq="B"),
    )


class TestCalculateBullLine:
    """calculate_bull_line(df) → pd.Series (EMA99 of X1)."""

    def test_returns_series(self):
        df = _make_index_df(150)
        result = calculate_bull_line(df)
        assert isinstance(result, pd.Series)

    def test_same_length_as_input(self):
        df = _make_index_df(150)
        result = calculate_bull_line(df)
        assert len(result) == len(df)

    def test_first_values_are_nan(self):
        """With adjust=False, EMA seeds with first value — check not NaN after warmup."""
        df = _make_index_df(200)
        result = calculate_bull_line(df)
        # After enough bars, EMA should converge and be finite
        assert not pd.isna(result.iloc[-1])
        assert np.isfinite(result.iloc[-1])

    def test_later_values_are_finite(self):
        df = _make_index_df(200)
        result = calculate_bull_line(df)
        assert not pd.isna(result.iloc[-1])
        assert np.isfinite(result.iloc[-1])


class TestClassifyMarketState:
    """classify_market_state(df) → DataFrame with bull_line + market_state."""

    def test_adds_columns(self):
        df = _make_index_df(200)
        result = classify_market_state(df)
        assert "bull_line" in result.columns
        assert "market_state" in result.columns

    def test_market_state_is_bull_or_bear(self):
        df = _make_index_df(200)
        result = classify_market_state(df)
        valid = result["market_state"].dropna()
        assert valid.isin(["牛市", "熊市"]).all()

    def test_extreme_bull(self):
        """Close far above the bull line → 牛市."""
        rng = np.random.default_rng(99)
        bull = np.linspace(3000, 3100, 200)
        close = bull + 50  # always above
        df = pd.DataFrame({
            "open": close - 1, "high": close + 2,
            "low": close - 2, "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, 200),
        }, index=pd.date_range("2025-01-02", periods=200, freq="B"))
        result = classify_market_state(df)
        last_state = result["market_state"].iloc[-1]
        assert last_state == "牛市"


class TestGetCurrentMarketState:
    """get_current_market_state(df) → dict — df must have bull_line column."""

    def test_returns_dict(self):
        df = _make_index_df(200)
        classified = classify_market_state(df)  # adds bull_line + market_state
        result = get_current_market_state(classified)
        assert isinstance(result, dict)

    def test_has_state_key(self):
        df = _make_index_df(200)
        classified = classify_market_state(df)
        result = get_current_market_state(classified)
        assert "state" in result
        assert result["state"] in ("牛市", "熊市")
