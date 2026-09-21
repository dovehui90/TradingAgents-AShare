"""
超买超卖位置指标（Position Index）

基于34日价格区间的百分位位置，用于判断超买超卖状态。
公式来源：通达信风险控制指标
"""

from typing import Optional

import pandas as pd
import numpy as np


def calculate_position_index(
    df: pd.DataFrame,
    period: int = 14,
    smooth: int = 5,
) -> pd.DataFrame:
    """
    计算超买超卖位置指标（滚动窗口，无漂移不钝化）

    公式来源：通达信滚动位置强弱指标
    基于滚动高低点计算当前位置百分位，
    价格涨跌会自动更新高低点，避免全历史的钝化问题。

    Args:
        df: 包含 open, high, low, close 列的 DataFrame
        period: 滚动周期，默认90
        smooth: EMA平滑周期，默认3

    Returns:
        DataFrame with columns: position_index, zone
    """
    result = df.copy()

    # 滚动高低点
    hhv = result['high'].rolling(window=period).max()
    llv = result['low'].rolling(window=period).min()

    # 计算当前位置百分比 (0-100)
    position = (result['close'] - llv) / (hhv - llv) * 100

    # EMA平滑
    result['position_index'] = position.ewm(span=smooth, adjust=False).mean()

    # 判断区域
    def get_zone(val):
        if pd.isna(val):
            return 'unknown'
        if val >= 80:
            return 'overbought'  # 超买区
        elif val >= 60:
            return 'high'        # 偏高区
        elif val >= 40:
            return 'neutral'     # 中性区
        elif val >= 20:
            return 'low'         # 偏低区
        else:
            return 'oversold'    # 超卖区

    result['zone'] = result['position_index'].apply(get_zone)

    return result


def get_position_transition(prev_zone: Optional[str], cur_zone: Optional[str]) -> Optional[str]:
    """
    判断位置指标单日档位转变（前一日 → 当日）。

    与 calculate_position_index 的 zone 定义联动：
    - 偏低转超卖：前一日 low(20~40) → 当日 oversold(<20)，跌破 20 线继续走弱
    - 超卖转偏低：前一日 oversold(<20) → 当日 low(20~40)，上穿 20 线超卖反弹

    Args:
        prev_zone: 前一日档位
        cur_zone: 当日档位

    Returns:
        'low_to_oversold' / 'oversold_to_low'，无该转变返回 None
    """
    if cur_zone == 'oversold' and prev_zone == 'low':
        return 'low_to_oversold'
    if cur_zone == 'low' and prev_zone == 'oversold':
        return 'oversold_to_low'
    return None


def get_position_signal(df: pd.DataFrame) -> dict:
    """
    获取位置指标信号

    Args:
        df: 包含 position_index 和 zone 列的 DataFrame

    Returns:
        dict: 信号信息
    """
    if len(df) == 0:
        return {"value": None, "zone": "unknown", "signal": "无数据"}

    latest = df.iloc[-1]
    value = latest.get('position_index')
    zone = latest.get('zone', 'unknown')

    if pd.isna(value):
        return {"value": None, "zone": "unknown", "signal": "数据不足"}

    # 生成信号
    if zone == 'overbought':
        signal = "极度超买，风险极高，考虑减仓"
    elif zone == 'high':
        signal = "偏高，警惕回调"
    elif zone == 'neutral':
        signal = "中性，正常持有"
    elif zone == 'low':
        signal = "偏低，关注机会"
    elif zone == 'oversold':
        signal = "极度超卖，可能见底"
    else:
        signal = "未知"

    return {
        "value": round(float(value), 2),
        "zone": zone,
        "signal": signal,
    }


def extract_position_history(pos: pd.DataFrame, symbol: str) -> list:
    """
    从 calculate_position_index 的结果中抽取逐日位置历史（供选股神器历史回看）。

    calculate_position_index 本就返回全序列（每根 K 线一个 zone），本函数把相邻
    两天的 zone 转成 position_transition，逐日产出。首日无前一日，跳过。

    Args:
        pos: calculate_position_index 返回的 DataFrame，需含 zone 列；
            日期取自 "date" 列，无该列时回退用 index。
        symbol: 股票代码，原样写入每行。

    Returns:
        [{date, symbol, position_zone, position_transition}, ...]，每日一行。
    """
    # 日期：优先 "date" 列（缓存命中路径），否则回退 index（实时抓取路径）
    if "date" in pos.columns:
        dates = pd.to_datetime(pos["date"]).dt.strftime("%Y-%m-%d").tolist()
    else:
        dates = pd.to_datetime(pos.index).strftime("%Y-%m-%d").tolist()

    zones = pos["zone"].astype(str).tolist()
    rows = []
    for i in range(1, len(pos)):
        transition = get_position_transition(zones[i - 1], zones[i])
        rows.append({
            "date": dates[i],
            "symbol": symbol,
            "position_zone": zones[i],
            "position_transition": transition,
        })
    return rows
