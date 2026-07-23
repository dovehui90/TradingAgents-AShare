"""Tests for tradingagents/strategy/fact_engine.py — pure computation, no I/O."""

import numpy as np
import pandas as pd
import pytest

from tradingagents.strategy.fact_engine import compute_facts, evaluate_rules, format_fact_text


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 60, seed: int = 42, trend: float = 0.0) -> pd.DataFrame:
    """Generate synthetic OHLCV DataFrame with n rows.

    Args:
        n: number of bars
        seed: random seed for reproducibility
        trend: daily drift (e.g. 0.01 = 1% per day)
    """
    rng = np.random.default_rng(seed)
    base = 10.0
    closes = base + np.cumsum(rng.normal(trend, 0.2, n))
    closes = np.maximum(closes, 0.5)
    highs = closes + np.abs(rng.normal(0, 0.15, n))
    lows = closes - np.abs(rng.normal(0, 0.15, n))
    opens = closes - rng.normal(0, 0.05, n)
    volumes = rng.integers(50_000, 500_000, n)

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=pd.date_range("2026-01-02", periods=n, freq="B"),
    )


# ---------------------------------------------------------------------------
# compute_facts
# ---------------------------------------------------------------------------

class TestComputeFacts:
    """compute_facts(df) → DataFrame with fact columns added."""

    def test_returns_dataframe(self):
        df = _make_ohlcv(30)
        result = compute_facts(df)
        assert isinstance(result, pd.DataFrame)

    def test_preserves_original_columns(self):
        df = _make_ohlcv(30)
        result = compute_facts(df)
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in result.columns

    def test_preserves_row_count(self):
        df = _make_ohlcv(30)
        result = compute_facts(df)
        assert len(result) == len(df)

    def test_adds_fact_columns(self):
        df = _make_ohlcv(60)
        result = compute_facts(df)
        # Key fact columns from the function
        expected_cols = [
            "is_high_volume",  # 规则1
            "amplitude_pct",
            "body_ratio",
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_handles_small_dataframe(self):
        df = _make_ohlcv(3)
        result = compute_facts(df)
        assert len(result) == 3
        assert isinstance(result, pd.DataFrame)

    def test_handles_flat_prices(self):
        """All prices equal → should not divide by zero."""
        df = pd.DataFrame({
            "open": [10.0] * 20,
            "high": [10.0] * 20,
            "low": [10.0] * 20,
            "close": [10.0] * 20,
            "volume": [100_000] * 20,
        })
        result = compute_facts(df)
        assert not result.isnull().all(axis=None)

    def test_market_state_defaults(self):
        df = _make_ohlcv(30)
        r1 = compute_facts(df)
        r2 = compute_facts(df, market_state=None)
        pd.testing.assert_frame_equal(r1, r2)

    def test_market_state_bull(self):
        df = _make_ohlcv(30, trend=0.02)
        result = compute_facts(df, market_state="牛市")
        assert "market_state" in result.columns


# ---------------------------------------------------------------------------
# evaluate_rules
# ---------------------------------------------------------------------------

class TestEvaluateRules:
    """evaluate_rules(facts_df) → list[dict] of triggered rules."""

    def test_returns_list(self):
        df = _make_ohlcv(60)
        facts = compute_facts(df)
        triggered = evaluate_rules(facts)
        assert isinstance(triggered, list)

    def test_each_rule_has_required_keys(self):
        df = _make_ohlcv(60)
        facts = compute_facts(df)
        triggered = evaluate_rules(facts)
        for rule in triggered:
            assert "id" in rule
            assert "name" in rule
            assert "decision" in rule

    def test_too_few_rows_returns_empty(self):
        df = _make_ohlcv(2)
        facts = compute_facts(df)
        triggered = evaluate_rules(facts)
        assert triggered == []

    def test_deterministic(self):
        df = _make_ohlcv(60, seed=42)
        facts1 = compute_facts(df)
        facts2 = compute_facts(df)
        r1 = evaluate_rules(facts1)
        r2 = evaluate_rules(facts2)
        assert r1 == r2

    def test_no_duplicate_rule_ids(self):
        df = _make_ohlcv(60)
        facts = compute_facts(df)
        triggered = evaluate_rules(facts)
        ids = [r["id"] for r in triggered]
        assert len(ids) == len(set(ids)), f"Duplicate rule IDs: {ids}"


# ---------------------------------------------------------------------------
# format_fact_text
# ---------------------------------------------------------------------------

class TestFormatFactText:
    """format_fact_text(facts_df) → str."""

    def test_returns_string(self):
        df = _make_ohlcv(60)
        facts = compute_facts(df)
        text = format_fact_text(facts)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_lookback_param(self):
        df = _make_ohlcv(60)
        facts = compute_facts(df)
        t10 = format_fact_text(facts, lookback=10)
        t30 = format_fact_text(facts, lookback=30)
        assert isinstance(t10, str)
        assert isinstance(t30, str)
