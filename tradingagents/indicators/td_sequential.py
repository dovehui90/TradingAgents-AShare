"""
神奇九转（TD Sequential Setup）

源自 Tom DeMark 的 TD Sequential 指标。
连续N根K线收盘价对比4天前收盘价，同方向累加计数，数到9为完整信号。
"""

import pandas as pd
import numpy as np


def calculate_td_sequential(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算顶部计数和底部计数。

    规则：
    - 收盘价 < 4天前收盘价 → 底部计数+1（否则清零）
    - 收盘价 > 4天前收盘价 → 顶部计数+1（否则清零）
    - 相等 → 双方清零
    - 数到9后条件仍满足 → 从1重新开始

    Returns:
        DataFrame 附加 td_buy_count, td_sell_count, td_buy_display, td_sell_display
    """
    result = df.copy()
    n = len(result)
    closes = result["close"].values

    buy_count = np.zeros(n, dtype=int)
    sell_count = np.zeros(n, dtype=int)

    for i in range(4, n):
        if closes[i] < closes[i - 4]:
            prev = buy_count[i - 1]
            if prev == 9:
                buy_count[i] = 1
            elif prev > 0:
                buy_count[i] = prev + 1
            else:
                buy_count[i] = 1
            sell_count[i] = 0
        elif closes[i] > closes[i - 4]:
            prev = sell_count[i - 1]
            if prev == 9:
                sell_count[i] = 1
            elif prev > 0:
                sell_count[i] = prev + 1
            else:
                sell_count[i] = 1
            buy_count[i] = 0
        else:
            buy_count[i] = 0
            sell_count[i] = 0

    result["td_buy_count"] = buy_count
    result["td_sell_count"] = sell_count
    result["td_buy_display"] = _filter_completed_only(buy_count)
    result["td_sell_display"] = _filter_completed_only(sell_count)

    return result


def _filter_completed_only(count_array):
    """过滤显示逻辑：
    - 数满9的完整序列 → 显示全部1-9
    - 进行中且未被打断 → count>=4时显示全部1到当前数
    - 中途被打断且未满9 → 不显示
    """
    n = len(count_array)
    display = np.zeros(n, dtype=int)
    i = 0
    while i < n:
        if count_array[i] == 0:
            i += 1
            continue
        start = i
        i += 1
        while i < n and count_array[i] > 0 and not (count_array[i - 1] == 9 and count_array[i] == 1):
            i += 1
        end = i
        segment_max = int(count_array[start:end].max())
        interrupted = (end < n) and (count_array[end] == 0)
        if segment_max >= 9:
            display[start:end] = count_array[start:end]
        elif not interrupted and segment_max >= 4:
            display[start:end] = count_array[start:end]
    return display


def get_td_sequential_signal(df: pd.DataFrame) -> dict:
    """获取最新九转信号状态"""
    if len(df) == 0:
        return {"buy_count": 0, "sell_count": 0, "signal": "无数据"}

    latest = df.iloc[-1]
    bc = int(latest.get("td_buy_display", 0))
    sc = int(latest.get("td_sell_display", 0))

    if bc == 9:
        signal = "底部数满9，见底反弹信号"
    elif sc == 9:
        signal = "顶部数满9，见顶风险信号"
    elif bc > 0:
        signal = f"底部计数中（{bc}/9）"
    elif sc > 0:
        signal = f"顶部计数中（{sc}/9）"
    else:
        signal = "无计数"

    return {"buy_count": bc, "sell_count": sc, "signal": signal}
