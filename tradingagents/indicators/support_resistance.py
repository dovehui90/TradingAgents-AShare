"""
支撑压力位 + 买卖信号

支持四种通道模式：
- hybrid（默认）：支撑位用 swing 惯性法，压力位用 rolling 衰减法，实测最准
- rolling：滚动窗口通道，实时更新
- rolling_filtered：rolling + 噪音过滤
- swing：局部高低点确认法，需等右侧确认
"""

import pandas as pd
import numpy as np


def _find_swing_points(df, window=5):
    """识别局部高低点"""
    n = len(df)
    lows = df["low"].values
    highs = df["high"].values
    is_swing_low = np.zeros(n, dtype=bool)
    is_swing_high = np.zeros(n, dtype=bool)
    for i in range(window, n - window):
        if lows[i] == lows[i - window:i + window + 1].min():
            is_swing_low[i] = True
        if highs[i] == highs[i - window:i + window + 1].max():
            is_swing_high[i] = True
    return is_swing_low, is_swing_high


def _build_swing_support(n, lows, is_swing_low):
    """Swing point 确认法 — 支撑位（有惯性，不会跟着新低立刻下移）"""
    support = np.full(n, np.nan)
    current = np.nan
    for i in range(n):
        if is_swing_low[i]:
            current = lows[i]
        support[i] = current
    return support


def calculate_support_resistance(
    df: pd.DataFrame,
    channel_mode: str = "hybrid",
    swing_window: int = 5,
    rolling_window: int = 20,
    resistance_window: int = 6,
    noise_threshold_pct: float = 0.03,
    rebound_pct: float = 0.015,
) -> pd.DataFrame:
    """
    计算支撑压力位和买卖信号

    Args:
        df: 包含 open, high, low, close 列的 DataFrame
        channel_mode: "hybrid"(默认) / "rolling" / "rolling_filtered" / "swing"
        swing_window: swing 窗口，默认5
        rolling_window: rolling 窗口，默认20
        resistance_window: hybrid 模式压力位专用窗口，默认6
        noise_threshold_pct: rolling_filtered 噪音过滤阈值，默认3%
        rebound_pct: 触及判定范围，默认1.5%

    Returns:
        DataFrame 附加 support, resistance, buy_signal, sell_signal
    """
    result = df.copy()
    n = len(result)
    highs = result["high"].values
    lows = result["low"].values

    if channel_mode == "swing":
        is_low, is_high = _find_swing_points(result, swing_window)
        support = _build_swing_support(n, lows, is_low)
        resistance = np.full(n, np.nan)
        cur = np.nan
        for i in range(n):
            if is_high[i]:
                cur = highs[i]
            resistance[i] = cur

    elif channel_mode == "rolling":
        # shift(1) 排除今天，避免K线贴着线走
        resistance = result["high"].shift(1).rolling(window=rolling_window, min_periods=1).max().values
        support = result["low"].shift(1).rolling(window=rolling_window, min_periods=1).min().values

    elif channel_mode == "rolling_filtered":
        cand_res = result["high"].shift(1).rolling(window=rolling_window, min_periods=1).max()
        cand_sup = result["low"].shift(1).rolling(window=rolling_window, min_periods=1).min()
        resistance = np.full(n, np.nan)
        support = np.full(n, np.nan)
        cur_r = cand_res.iloc[0] if not pd.isna(cand_res.iloc[0]) else highs[0]
        cur_s = cand_sup.iloc[0] if not pd.isna(cand_sup.iloc[0]) else lows[0]
        for i in range(n):
            cr, cs = cand_res.iloc[i], cand_sup.iloc[i]
            if not pd.isna(cr) and cr > cur_r * (1 + noise_threshold_pct):
                cur_r = cr
            if not pd.isna(cs) and cs < cur_s * (1 - noise_threshold_pct):
                cur_s = cs
            resistance[i] = cur_r
            support[i] = cur_s

    else:  # hybrid（默认）
        # 支撑位和压力位都用 swing 确认法（惯性强，不随新低/新高轻易移动）
        is_low, is_high = _find_swing_points(result, swing_window)
        support = _build_swing_support(n, lows, is_low)
        resistance = np.full(n, np.nan)
        cur = np.nan
        for i in range(n):
            if is_high[i]:
                cur = highs[i]
            resistance[i] = cur

    result["support"] = support
    result["resistance"] = resistance

    # 买卖信号
    buy_signal = np.zeros(n, dtype=bool)
    sell_signal = np.zeros(n, dtype=bool)
    opens = result["open"].values
    closes = result["close"].values
    for i in range(n):
        s, r = support[i], resistance[i]
        if not np.isnan(s) and lows[i] <= s * (1 + rebound_pct) and closes[i] > opens[i]:
            buy_signal[i] = True
        if not np.isnan(r) and highs[i] >= r * (1 - rebound_pct) and closes[i] < opens[i]:
            sell_signal[i] = True

    result["buy_signal"] = buy_signal
    result["sell_signal"] = sell_signal

    return result


def get_support_resistance_signal(df: pd.DataFrame) -> dict:
    """获取最新支撑压力信号"""
    if len(df) == 0:
        return {"support": None, "resistance": None, "signal": "无数据"}

    latest = df.iloc[-1]
    support = round(float(latest["support"]), 2) if pd.notna(latest["support"]) else None
    resistance = round(float(latest["resistance"]), 2) if pd.notna(latest["resistance"]) else None
    close = latest["close"]

    if support and close <= support * 1.01:
        signal = "价格接近支撑位"
    elif resistance and close >= resistance * 0.99:
        signal = "价格接近压力位"
    else:
        signal = "价格在支撑压力之间"

    return {"support": support, "resistance": resistance, "signal": signal}
