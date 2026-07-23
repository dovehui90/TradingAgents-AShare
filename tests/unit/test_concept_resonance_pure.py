"""Tests for tradingagents/dataflows/concept_resonance.py — pure functions.

Tests _pearson_corr, format_resonance_for_prompt, and extract_returns_from_df.
These are pure computation; no network calls needed.
"""

import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.concept_resonance import (
    ConceptResonanceResult,
    BoardInfo,
    _pearson_corr,
    extract_returns_from_df,
    format_resonance_for_prompt,
)


class TestPearsonCorr:
    """_pearson_corr() — pure math function."""

    def test_perfect_positive(self):
        a = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0] * 10)  # 50 points
        b = pd.Series([2.0, 4.0, 6.0, 8.0, 10.0] * 10)
        result = _pearson_corr(a, b)
        assert result == pytest.approx(1.0, abs=0.0001)

    def test_perfect_negative(self):
        a = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0] * 10)
        b = pd.Series([5.0, 4.0, 3.0, 2.0, 1.0] * 10)
        result = _pearson_corr(a, b)
        assert result == pytest.approx(-1.0, abs=0.0001)

    def test_uncorrelated_random(self):
        """Two independent random series should have correlation near 0."""
        rng = np.random.default_rng(123)
        a = pd.Series(rng.normal(0, 1, 100))
        b = pd.Series(rng.normal(0, 1, 100))
        result = _pearson_corr(a, b)
        assert -0.3 < result < 0.3

    def test_short_series_returns_zero(self):
        """Fewer than MIN_VALID_DAYS (36) → returns 0.0."""
        a = pd.Series(np.random.randn(20))
        b = pd.Series(np.random.randn(20))
        result = _pearson_corr(a, b)
        assert result == 0.0

    def test_different_lengths_aligns_to_shorter(self):
        """Should align to the shorter series length."""
        rng = np.random.default_rng(42)
        a = pd.Series(rng.normal(0, 1, 60))
        # b is perfectly correlated with a but shorter
        b = a.tail(50) * 2.0
        result = _pearson_corr(a, b)
        # Should still compute correlation on 50 points → near 1.0
        assert result == pytest.approx(1.0, abs=0.0001)

    def test_nan_result_returns_zero(self):
        """Constant series (zero variance) would give NaN correlation → 0.0."""
        a = pd.Series([3.0] * 50)
        b = pd.Series(np.random.randn(50))
        result = _pearson_corr(a, b)
        assert result == 0.0


class TestExtractReturnsFromDF:
    """extract_returns_from_df() tests."""

    def test_valid_ohlcv_dataframe(self):
        rng = np.random.default_rng(7)
        n = 100
        closes = 10.0 + np.cumsum(rng.normal(0, 0.2, n))
        closes = np.maximum(closes, 0.5)
        df = pd.DataFrame({
            "date": pd.date_range("2026-01-02", periods=n, freq="B"),
            "close": closes,
            "volume": rng.integers(50000, 500000, n),
        })
        result = extract_returns_from_df(df)
        assert result is not None
        assert isinstance(result, pd.Series)
        assert len(result) > 0

    def test_returns_none_for_empty_dataframe(self):
        result = extract_returns_from_df(pd.DataFrame())
        assert result is None

    def test_returns_none_when_no_close_column(self):
        df = pd.DataFrame({"date": ["2026-01-01"], "open": [10.0]})
        result = extract_returns_from_df(df)
        assert result is None

    def test_returns_none_for_too_few_rows(self):
        """Less than MIN_VALID_DAYS (36) valid rows → None."""
        df = pd.DataFrame({
            "close": [10.0 + i * 0.1 for i in range(20)],
            "date": pd.date_range("2026-01-02", periods=20, freq="B"),
        })
        result = extract_returns_from_df(df)
        assert result is None

    def test_filters_extreme_returns(self):
        """Returns >15% should be filtered out."""
        rng = np.random.default_rng(42)
        n = 80
        closes = 10.0 + np.cumsum(rng.normal(0, 0.2, n))
        closes = np.maximum(closes, 0.5)
        # Insert an extreme jump
        closes[40] = closes[39] * 1.30  # 30% jump
        df = pd.DataFrame({
            "close": closes,
            "date": pd.date_range("2026-01-02", periods=n, freq="B"),
        })
        result = extract_returns_from_df(df)
        assert result is not None
        # All returns should be ≤ 15%
        assert (result.abs() <= 0.15).all()


class TestFormatResonanceForPrompt:
    """format_resonance_for_prompt() — pure text formatting."""

    def test_insufficient_data_message(self):
        result = ConceptResonanceResult(
            resonance_score=0.0,
            insufficient_data=True,
        )
        text = format_resonance_for_prompt(result)
        assert "数据不足" in text

    def test_flat_market_message(self):
        result = ConceptResonanceResult(
            resonance_score=0.0,
            is_flat=True,
        )
        text = format_resonance_for_prompt(result)
        assert "横盘" in text

    def test_divergence_alert_message(self):
        result = ConceptResonanceResult(
            resonance_score=0.0,
            divergence_alert=True,
        )
        text = format_resonance_for_prompt(result)
        assert "独立行情" in text

    def test_normal_resonance_with_boards(self):
        boards = [
            BoardInfo(name="PCB概念", correlation=0.72, direction="涨", strength=3.5),
            BoardInfo(name="5G概念", correlation=0.58, direction="涨", strength=2.8),
        ]
        result = ConceptResonanceResult(
            resonance_score=0.65,
            leading_boards=boards,
            board_trend_summary="主导概念：PCB概念、5G概念。共振评分：0.65（跟涨）",
        )
        text = format_resonance_for_prompt(result)
        assert "共振评分" in text
        assert "PCB概念" in text
        assert "相关系数 +0.72" in text

    def test_board_disagreement_visible(self):
        boards = [
            BoardInfo(name="白酒", correlation=0.60, direction="涨", strength=2.0),
            BoardInfo(name="医药", correlation=-0.55, direction="跌", strength=3.0),
        ]
        result = ConceptResonanceResult(
            resonance_score=0.15,
            leading_boards=boards,
            board_disagreement=True,
            board_trend_summary="test",
        )
        text = format_resonance_for_prompt(result)
        assert "方向分裂" in text

    def test_warnings_included_when_no_early_return(self):
        """Warnings appear in output when no divergence/insufficient-data early-return fires."""
        boards = [
            BoardInfo(name="PCB概念", correlation=0.72, direction="涨", strength=3.5),
        ]
        result = ConceptResonanceResult(
            resonance_score=0.65,
            leading_boards=boards,
            board_trend_summary="test",
            warnings=["疑似停牌：连续3日以上零涨幅"],
        )
        text = format_resonance_for_prompt(result)
        assert "疑似停牌" in text

    def test_returns_string(self):
        result = ConceptResonanceResult(
            resonance_score=0.0,
            insufficient_data=True,
        )
        text = format_resonance_for_prompt(result)
        assert isinstance(text, str)
        assert len(text) > 0
