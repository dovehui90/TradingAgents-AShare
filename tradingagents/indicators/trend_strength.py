"""
趋势强度指数（Trend Strength Index）

基于SMA20乖离率的标准化趋势强度，与同花顺中线趋势指标对齐。
公式：0.392 * (收盘价-SMA20) / SMA20 * 100
"""

import pandas as pd
import numpy as np


def calculate_trend_strength(
    df: pd.DataFrame,
    ma_window: int = 20,
    scale: float = 0.392,
) -> pd.DataFrame:
    """
    计算趋势强度指数（与同花顺对齐）

    公式：trend_strength = scale * (close - SMA20) / SMA20 * 100

    Args:
        df: 包含 high, low, close 列的 DataFrame
        ma_window: 均线周期，默认20（SMA20）
        scale: 缩放系数，默认0.392（线性回归拟合值）

    Returns:
        DataFrame 附加 trend_strength, zone 列
    """
    result = df.copy()

    # SMA均线
    result["ma"] = result["close"].rolling(window=ma_window).mean()

    # 乖离率
    result["bias"] = (result["close"] - result["ma"]) / result["ma"] * 100

    # 趋势强度 = 缩放后的乖离率
    result["trend_strength"] = result["bias"] * scale

    # 区域判断（基于缩放后的值域）
    def get_zone(val):
        if pd.isna(val):
            return "unknown"
        if val >= 1.5:
            return "strong"
        elif val <= -1.5:
            return "weak"
        else:
            return "neutral"

    result["zone"] = result["trend_strength"].apply(get_zone)

    # 清理中间列
    result.drop(columns=["ma", "bias"], inplace=True)

    return result


def get_trend_strength_signal(df: pd.DataFrame, buy_th: float = 1.5, sell_th: float = -1.5) -> dict:
    """
    获取趋势强度信号

    Args:
        df: 包含 trend_strength 和 zone 列的 DataFrame
        buy_th: 买入阈值，默认1.5
        sell_th: 卖出阈值，默认-1.5

    Returns:
        dict: 信号信息
    """
    if len(df) == 0:
        return {"value": None, "zone": "unknown", "signal": "无数据", "direction": "neutral"}

    latest = df.iloc[-1]
    value = latest.get("trend_strength")
    zone = latest.get("zone", "unknown")

    if pd.isna(value):
        return {"value": None, "zone": "unknown", "signal": "数据不足", "direction": "neutral"}

    value = round(float(value), 2)

    if value >= buy_th:
        direction = "bullish"
        signal = "趋势偏强，中线看多"
    elif value <= sell_th:
        direction = "bearish"
        signal = "趋势偏弱，中线看空"
    else:
        direction = "neutral"
        signal = "趋势中性，观望为主"

    return {
        "value": value,
        "zone": zone,
        "signal": signal,
        "direction": direction,
    }
