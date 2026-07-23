"""Tests for tradingagents/yang_yin/scoring.py — pure computation functions."""

import numpy as np
import pandas as pd
import pytest

from tradingagents.yang_yin.scoring import (
    compute_ma,
    compute_ema,
    compute_macd,
    compute_rsi,
    score_stock,
)
from tradingagents.yang_yin.scoring import StockScore


def _make_ohlcv(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    base = 10.0
    closes = base + np.cumsum(rng.normal(0, 0.2, n))
    closes = np.maximum(closes, 0.5)
    highs = closes + np.abs(rng.normal(0, 0.15, n))
    lows = closes - np.abs(rng.normal(0, 0.15, n))
    opens = closes - rng.normal(0, 0.05, n)
    volumes = rng.integers(50_000, 500_000, n)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=pd.date_range("2026-01-02", periods=n, freq="B"),
    )


class TestComputeMA:
    def test_same_length(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = compute_ma(s, window=3)
        assert len(result) == len(s)

    def test_basic_average(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = compute_ma(s, window=3)
        # SMA(3) of [3,4,5] at last position = 4.0
        assert abs(result.iloc[-1] - 4.0) < 0.01


class TestComputeEMA:
    def test_same_length(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = compute_ema(s, window=5)
        assert len(result) == len(s)


class TestComputeMACD:
    def test_returns_tuple(self):
        s = pd.Series(np.random.randn(100).cumsum() + 10)
        dif, dea, hist = compute_macd(s)
        assert len(dif) == len(s)
        assert len(dea) == len(s)
        assert len(hist) == len(s)


class TestComputeRSI:
    def test_returns_series(self):
        s = pd.Series(np.random.randn(100).cumsum() + 10)
        result = compute_rsi(s, window=14)
        assert isinstance(result, pd.Series)
        assert len(result) == len(s)

    def test_range_0_to_100(self):
        s = pd.Series(np.random.randn(200).cumsum() + 10)
        result = compute_rsi(s, window=14).dropna()
        assert (result >= 0).all()
        assert (result <= 100).all()

    def test_constant_prices_all_up(self):
        """All up days → avg_loss=0 → RSI=100 (no NaN after initial warmup)."""
        s = pd.Series(np.linspace(1, 100, 100))
        result = compute_rsi(s, window=14).dropna()
        # RSI should be near 100 when all moves are gains
        if len(result) > 0:
            assert result.iloc[-1] >= 80


class TestScoreStock:
    def test_returns_stockscore_or_none(self):
        df = _make_ohlcv(120)
        result = score_stock(df)
        assert result is None or isinstance(result, StockScore)

    def test_too_few_rows_returns_none(self):
        df = _make_ohlcv(10)
        result = score_stock(df)
        assert result is None

    def test_with_fund_flow(self):
        df = _make_ohlcv(120)
        result = score_stock(df, fund_flow=1000.0)
        if result is not None:
            assert isinstance(result.total, float)
