"""Regression tests for tradingagents/yang_yin/model_v7.py — predict_yangpu().

These tests protect the ML model coefficients from silent corruption.
If any of these tests fail after editing model_v7.py, the model parameters
(INTERCEPT, COEF, X_MEAN, X_STD) have changed — verify the change is intentional.
"""

import numpy as np
import pytest

from tradingagents.yang_yin.model_v7 import (
    COEF,
    FEATURE_COLS,
    INTERCEPT,
    X_MEAN,
    X_STD,
    predict_yangpu,
)


def _mean_factors() -> dict[str, float]:
    """Return factor dict using X_MEAN values + prev_yangpu=50."""
    factors = {f: X_MEAN.get(f, 0.0) for f in FEATURE_COLS}
    factors["prev_yangpu"] = X_MEAN.get("prev_yangpu", 50.0)
    return factors


class TestPredictYangpu:
    """predict_yangpu is pure math: dict in, float out. No mocking needed."""

    def test_returns_float_in_range(self):
        """Valid inputs always produce output in [0, 100]."""
        factors = _mean_factors()
        result = predict_yangpu(factors)
        assert isinstance(result, float)
        assert 0.0 <= result <= 100.0

    def test_regression_known_values_approximate(self):
        """At mean values, prediction should be near INTERCEPT (± a few points).

        This is a smoke test: if the model is totally broken it will fail.
        For exact regression, use test_exact_regression_snapshot below.
        """
        factors = _mean_factors()
        result = predict_yangpu(factors)
        # At mean values, scaled vector ≈ 0, so result ≈ INTERCEPT
        assert abs(result - INTERCEPT) < 15.0, (
            f"Expected near {INTERCEPT}, got {result} — coefficients may have changed"
        )

    def test_exact_regression_snapshot(self):
        """Exact regression: known input → exact known output.

        If this fails, COEF / INTERCEPT / X_MEAN / X_STD have been modified.
        Verify the change is intentional before updating this test.
        """
        factors = {
            "trend_mean": 0.5, "trend_yang": 0.55,
            "momentum_mean": 0.02, "momentum_yang": 0.55,
            "supply_demand_mean": -0.05, "supply_demand_yang": 0.55,
            "divergence_mean": 0.18, "divergence_yang": 0.35,
            "obv_mean": 0.08, "obv_yang": 0.26,
            "vol_extreme_mean": 1.05,
            "volprice_new_mean": 0.04, "volprice_new_yang": 0.07,
            "rsi_mean": 50.0, "rsi_yang": 0.5,
            "strength_mean": 0.0, "strength_yang": 0.12,
            "money_mean": 0.0, "money_yang": 0.0,
            "prev_yangpu": 46.0,
        }
        result = predict_yangpu(factors)
        # Value computed from current model_v7.py coefficients.
        # Tolerance ±0.02 handles float rounding differences across platforms.
        assert result == pytest.approx(48.3159, abs=0.02)

    def test_missing_factor_does_not_crash(self):
        """Missing keys are treated as 0.0, no KeyError."""
        result = predict_yangpu({"prev_yangpu": 50.0})
        assert 0.0 <= result <= 100.0

    def test_none_factor_treated_as_zero(self):
        """None values should not cause TypeError."""
        factors = {f: None for f in FEATURE_COLS}
        factors["prev_yangpu"] = 50.0
        result = predict_yangpu(factors)
        assert isinstance(result, float)

    def test_non_finite_returns_fallback_50(self):
        """NaN/inf in raw values should return 50.0 fallback."""
        factors = {f: np.inf for f in FEATURE_COLS}
        result = predict_yangpu(factors)
        assert result == 50.0

        factors_nan = {f: np.nan for f in FEATURE_COLS}
        result_nan = predict_yangpu(factors_nan)
        assert result_nan == 50.0

    def test_all_zeros_produces_valid_output(self):
        """Edge case: all factors zero."""
        factors = {f: 0.0 for f in FEATURE_COLS}
        result = predict_yangpu(factors)
        assert 0.0 <= result <= 100.0
        assert isinstance(result, float)

    def test_extreme_values_clamp_to_range(self):
        """Very large factor values should still produce output in [0, 100]."""
        factors = {f: 1e6 for f in FEATURE_COLS}
        result = predict_yangpu(factors)
        assert 0.0 <= result <= 100.0

    def test_feature_order_independent(self):
        """Result depends only on factor values, not dict insertion order."""
        keys = list(FEATURE_COLS)
        rng = np.random.default_rng(42)
        vals = {k: float(rng.uniform(0, 1)) for k in keys}
        # Shuffle keys but same values
        shuffled_keys = list(keys)
        rng.shuffle(shuffled_keys)
        ordered_factors = {k: vals[k] for k in keys}
        shuffled_factors = {k: vals[k] for k in shuffled_keys}
        assert predict_yangpu(ordered_factors) == predict_yangpu(shuffled_factors)


class TestFeatureColsAlignment:
    """FEATURE_COLS, COEF, X_MEAN, X_STD must use the same feature set."""

    def test_same_keys_in_all_dicts(self):
        assert set(FEATURE_COLS) == set(COEF.keys())
        assert set(FEATURE_COLS) == set(X_MEAN.keys())
        assert set(FEATURE_COLS) == set(X_STD.keys())

    def test_exactly_20_features(self):
        assert len(FEATURE_COLS) == 20
        assert len(COEF) == 20
        assert len(X_MEAN) == 20
        assert len(X_STD) == 20

    def test_no_zero_std_values(self):
        """X_STD=0 would cause division by zero in z-score normalization."""
        for f in FEATURE_COLS:
            assert X_STD[f] > 0, f"X_STD['{f}'] is zero — would cause division by zero"

    def test_money_coefficients_are_zero(self):
        """money_mean and money_yang coefficients are intentionally 0."""
        assert COEF["money_mean"] == 0.0
        assert COEF["money_yang"] == 0.0
