"""主力游资大户散户线 — Capital Flow Indicator.

基于换手率多周期MA，模拟不同类型资金的活跃度：
- 主力线 MA(换手率, 4)  — 短期高频资金
- 游资线 MA(换手率, 9)  — 短线热钱
- 大户线 MA(换手率, 17) — 中线资金
- 散户线 MA(换手率, 34) — 长线散户
- 关注线 MA(换手率, 180)— 长期均值基准
"""

import numpy as np
import pandas as pd


def _moving_average(series: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average; first (period-1) values are NaN."""
    out = np.full_like(series, np.nan, dtype=float)
    if len(series) < period:
        return out
    # Use convolution for efficiency
    kernel = np.ones(period) / period
    valid = np.convolve(series, kernel, mode="valid")
    out[period - 1:] = valid
    return out


def calculate_capital_flow(
    df: pd.DataFrame,
    turnover_col: str = "turnover_rate",
) -> pd.DataFrame:
    """Calculate capital flow lines from a DataFrame containing turnover rate.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain a turnover rate column (pct values, e.g. 0.5 = 0.5%).
    turnover_col : str
        Name of the turnover rate column (default: turnover_rate).

    Returns
    -------
    pd.DataFrame
        Original df with extra columns:
        - capital_main      (主力, 4d MA)
        - capital_hot       (游资, 9d MA)
        - capital_large     (大户, 17d MA)
        - capital_retail    (散户, 34d MA)
        - capital_attention (关注线, 180d MA)
    """
    if turnover_col not in df.columns:
        raise ValueError(f"Column '{turnover_col}' not found. Available: {list(df.columns)}")

    result = df.copy()
    t = result[turnover_col].values.astype(float)

    result["capital_main"] = _moving_average(t, 4)
    result["capital_hot"] = _moving_average(t, 9)
    result["capital_large"] = _moving_average(t, 17)
    result["capital_retail"] = _moving_average(t, 34)
    result["capital_attention"] = _moving_average(t, 180)

    return result


def get_capital_flow_signal(row: pd.Series) -> dict:
    """Generate trading signal based on capital flow lines at the latest bar.

    Returns a dict with:
    - signal: "主力活跃" / "游资主导" / "散户主导" / "地量观望"
    - strength: 1-5 (higher = stronger bullish bias)
    - details: list of human-readable signal descriptions
    """
    main = row.get("capital_main", np.nan)
    hot = row.get("capital_hot", np.nan)
    large = row.get("capital_large", np.nan)
    retail = row.get("capital_retail", np.nan)
    attention = row.get("capital_attention", np.nan)

    details = []
    bullish_score = 0

    # 1. 主力 vs 游资
    if not (np.isnan(main) or np.isnan(hot)):
        if main > hot:
            bullish_score += 1
            details.append("主力线上穿游资线，短期资金活跃")
        else:
            details.append("主力线低于游资线，热钱主导")

    # 2. 主力 vs 大户
    if not (np.isnan(main) or np.isnan(large)):
        if main > large:
            bullish_score += 1
            details.append("主力线高于大户线，控盘度增强")

    # 3. 主力 vs 散户
    if not (np.isnan(main) or np.isnan(retail)):
        if main > retail:
            bullish_score += 1
            details.append("主力线高于散户线，资金结构偏多")
        else:
            details.append("散户线高于主力线，散户主导，谨慎")

    # 4. 主力 vs 关注线 (长期均值)
    if not (np.isnan(main) or np.isnan(attention)):
        if main > attention:
            bullish_score += 1
            details.append("换手率高于长期均值，市场关注度高")
        else:
            bullish_score -= 1
            details.append("换手率低于长期均值，交投清淡")

    # 5. 换手率绝对值
    if not np.isnan(main):
        if main > 3:
            bullish_score += 1
            details.append(f"换手率MA4={main:.2f}%，属高换手活跃区")
        elif main < 0.5:
            bullish_score -= 1
            details.append(f"换手率MA4={main:.2f}%，地量区，变盘前兆")

    # Signal
    if bullish_score >= 3:
        signal = "主力活跃"
        strength = 5
    elif bullish_score >= 1:
        signal = "游资主导"
        strength = 3
    elif bullish_score >= -1:
        signal = "散户主导"
        strength = 2
    else:
        signal = "地量观望"
        strength = 1

    return {"signal": signal, "strength": strength, "details": details}
