"""
支撑压力位 + 止盈止损 + 买卖信号

基于局部高低点识别支撑压力位，生成止盈止损线和买卖信号。
"""

import pandas as pd
import numpy as np


def calculate_support_resistance(
    df: pd.DataFrame,
    swing_window: int = 5,
    buffer_pct: float = 0.02,
    rebound_pct: float = 0.015,
) -> pd.DataFrame:
    """
    计算支撑压力位、止盈止损线和买卖信号

    Args:
        df: 包含 open, high, low, close 列的 DataFrame
        swing_window: 局部高低点窗口（左右各N天），默认5
        buffer_pct: 止损/止盈缓冲比例，默认2%
        rebound_pct: 触及判定范围，默认1.5%

    Returns:
        DataFrame 附加 support, resistance, stop_loss, take_profit, buy_signal, sell_signal
    """
    result = df.copy()
    n = len(result)
    lows = result["low"].values
    highs = result["high"].values

    # 识别局部高低点
    is_swing_low = np.zeros(n, dtype=bool)
    is_swing_high = np.zeros(n, dtype=bool)
    for i in range(swing_window, n - swing_window):
        local_lows = lows[i - swing_window:i + swing_window + 1]
        local_highs = highs[i - swing_window:i + swing_window + 1]
        if lows[i] == local_lows.min():
            is_swing_low[i] = True
        if highs[i] == local_highs.max():
            is_swing_high[i] = True

    # 构建跟随K线的支撑压力位（台阶状更新）
    support = np.full(n, np.nan)
    resistance = np.full(n, np.nan)
    current_support = np.nan
    current_resistance = np.nan
    for i in range(n):
        if is_swing_low[i]:
            current_support = lows[i]
        if is_swing_high[i]:
            current_resistance = highs[i]
        support[i] = current_support
        resistance[i] = current_resistance

    result["support"] = support
    result["resistance"] = resistance
    result["stop_loss"] = support * (1 - buffer_pct)
    result["take_profit"] = resistance * (1 - buffer_pct)

    # 买卖信号
    opens = result["open"].values
    closes = result["close"].values
    buy_signal = np.zeros(n, dtype=bool)
    sell_signal = np.zeros(n, dtype=bool)
    for i in range(n):
        s = support[i]
        r = resistance[i]
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
        return {"support": None, "resistance": None, "stop_loss": None, "take_profit": None, "signal": "无数据"}

    latest = df.iloc[-1]
    support = round(float(latest["support"]), 2) if pd.notna(latest["support"]) else None
    resistance = round(float(latest["resistance"]), 2) if pd.notna(latest["resistance"]) else None
    stop_loss = round(float(latest["stop_loss"]), 2) if pd.notna(latest["stop_loss"]) else None
    take_profit = round(float(latest["take_profit"]), 2) if pd.notna(latest["take_profit"]) else None

    close = latest["close"]
    if support and close <= support * 1.01:
        signal = "价格接近支撑位"
    elif resistance and close >= resistance * 0.99:
        signal = "价格接近压力位"
    else:
        signal = "价格在支撑压力之间"

    return {
        "support": support,
        "resistance": resistance,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "signal": signal,
    }
