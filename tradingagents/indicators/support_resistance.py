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


def _build_swing_support(n, lows, is_swing_low, lookback=250):
    """
    动态支撑位计算

    支持多时间框架：
    - lookback=20: 短线支撑
    - lookback=60: 中线支撑
    - lookback=250: 长线支撑（1年）
    """
    support = np.full(n, np.nan)

    for i in range(n):
        start_idx = max(0, i - lookback)
        recent_lows = lows[start_idx:i + 1]
        if len(recent_lows) > 0:
            support[i] = np.min(recent_lows)

    return support


def find_high_volume_levels(df, lookback=60):
    """
    基于高量柱的支撑压力位（PDF定义）

    PDF规则4：以当天高量实体低点为支撑位
    PDF规则5：以过往高量实体高低点为压力位

    Args:
        df: 包含 open, high, low, close, volume 列的 DataFrame
        lookback: 回看天数

    Returns:
        dict: {'support': 支撑位列表, 'resistance': 压力位列表}
    """
    if len(df) < 4:
        return {'support': [], 'resistance': []}

    volume = df['volume'].values
    opens = df['open'].values
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values

    support_levels = []
    resistance_levels = []

    # 找出高量柱（当天量 > 前3天量）
    for i in range(3, len(df)):
        if volume[i] > max(volume[i-3:i]):
            # 高量柱出现
            body_low = min(opens[i], closes[i])  # 实体低点
            body_high = max(opens[i], closes[i])  # 实体高点

            # 支撑位：高量实体低点
            support_levels.append({
                'date': df.index[i],
                'level': body_low,
                'type': 'high_volume_support'
            })

            # 压力位：高量实体高点
            resistance_levels.append({
                'date': df.index[i],
                'level': body_high,
                'type': 'high_volume_resistance'
            })

    return {'support': support_levels, 'resistance': resistance_levels}


def get_high_volume_support_resistance(high_vol_levels, current_price):
    """
    根据高量柱获取当前的支撑压力位

    规则：
    - 支撑位：当前价格下方最近的高量实体低点
    - 压力位：当前价格上方最近的高量实体高点
    """
    support = None
    resistance = None

    # 找支撑位：当前价格下方最近的高量实体低点
    below_supports = [s for s in high_vol_levels['support'] if s['level'] < current_price]
    if below_supports:
        support = max(below_supports, key=lambda x: x['level'])['level']

    # 找压力位：当前价格上方最近的高量实体高点
    above_resistances = [r for r in high_vol_levels['resistance'] if r['level'] > current_price]
    if above_resistances:
        resistance = min(above_resistances, key=lambda x: x['level'])['level']

    return {'support': support, 'resistance': resistance}


def find_gaps(df):
    """
    识别缺口（Gap）

    缺口类型：
    - 向上跳空缺口：今天最低价 > 昨天最高价（缺口区域成为支撑）
    - 向下跳空缺口：今天最高价 < 昨天最低价（缺口区域成为压力）

    Args:
        df: 包含 open, high, low, close 列的 DataFrame

    Returns:
        list: 缺口列表，每个元素为 (日期, 缺口类型, 缺口上沿, 缺口下沿)
    """
    gaps = []
    highs = df['high'].values
    lows = df['low'].values
    dates = df.index

    for i in range(1, len(df)):
        prev_high = highs[i-1]
        prev_low = lows[i-1]
        curr_low = lows[i]
        curr_high = highs[i]

        # 向上跳空缺口：今天最低价 > 昨天最高价
        if curr_low > prev_high:
            gaps.append({
                'date': dates[i],
                'type': 'up_gap',
                'upper': curr_low,  # 缺口上沿（支撑位）
                'lower': prev_high,  # 缺口下沿
            })

        # 向下跳空缺口：今天最高价 < 昨天最低价
        if curr_high < prev_low:
            gaps.append({
                'date': dates[i],
                'type': 'down_gap',
                'upper': prev_low,  # 缺口上沿（压力位）
                'lower': curr_high,  # 缺口下沿
            })

    return gaps


def get_gap_levels(gaps, current_price):
    """
    根据缺口获取支撑压力位

    规则：
    - 向上跳空缺口：缺口区域成为支撑
    - 向下跳空缺口：缺口区域成为压力

    Args:
        gaps: 缺口列表
        current_price: 当前价格

    Returns:
        dict: {'support': 支撑位, 'resistance': 压力位}
    """
    support_levels = []
    resistance_levels = []

    for gap in gaps:
        if gap['type'] == 'up_gap':
            # 向上跳空缺口：缺口区域成为支撑
            if gap['lower'] < current_price:
                support_levels.append(gap['lower'])
        elif gap['type'] == 'down_gap':
            # 向下跳空缺口：缺口区域成为压力
            if gap['upper'] > current_price:
                resistance_levels.append(gap['upper'])

    # 取最近的支撑和压力
    support = max(support_levels) if support_levels else None
    resistance = min(resistance_levels) if resistance_levels else None

    return {'support': support, 'resistance': resistance}


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
        # 三合一：Swing确认法 + 高量柱法 + 缺口法
        # 使用1年（250个交易日）数据计算
        lookback = min(250, n)

        # 1. Swing确认法
        swing_window = 5
        is_low, is_high = _find_swing_points(df, swing_window)
        swing_lows = [(i, lows[i]) for i in range(n) if is_low[i]]
        swing_highs = [(i, highs[i]) for i in range(n) if is_high[i]]

        # 2. 高量柱法（PDF定义）
        high_vol_levels = find_high_volume_levels(df, lookback)

        support = np.full(n, np.nan)
        resistance = np.full(n, np.nan)

        for i in range(n):
            current_price = lows[i]

            # ======== Swing支撑压力位 ========
            valid_swing_lows = [(idx, val) for idx, val in swing_lows if idx <= i]
            valid_swing_highs = [(idx, val) for idx, val in swing_highs if idx <= i]

            swing_support = None
            swing_resistance = None

            if valid_swing_lows:
                # 找当前价格下方最近的swing low
                below_supports = [(idx, val) for idx, val in valid_swing_lows if val <= current_price]
                if below_supports:
                    swing_support = below_supports[-1][1]
                else:
                    # 如果没有低于当前价的swing low，使用最近的swing low
                    swing_support = valid_swing_lows[-1][1]

            if valid_swing_highs:
                # 找当前价格上方最近的swing high
                above_resistances = [(idx, val) for idx, val in valid_swing_highs if val >= current_price]
                if above_resistances:
                    swing_resistance = above_resistances[0][1]
                else:
                    # 如果没有高于当前价的swing high，使用最近的swing high
                    swing_resistance = valid_swing_highs[-1][1]

            # ======== 高量柱支撑压力位（PDF定义）========
            hv_levels = get_high_volume_support_resistance(high_vol_levels, current_price)
            hv_support = hv_levels['support']
            hv_resistance = hv_levels['resistance']

            # ======== 综合支撑压力位 ========
            # 支撑位：取更高的值（更接近当前价的支撑）
            support_candidates = [s for s in [swing_support, hv_support] if s is not None]
            if support_candidates:
                support[i] = max(support_candidates)

            # 压力位：取更低的值（更接近当前价的压力）
            resistance_candidates = [r for r in [swing_resistance, hv_resistance] if r is not None]
            if resistance_candidates:
                resistance[i] = min(resistance_candidates)

    result["support"] = support
    result["resistance"] = resistance

    # ======== 缺口分析（补充支撑压力位）========
    gaps = find_gaps(result)
    for i in range(n):
        current_price = result["close"].iloc[i]
        gap_levels = get_gap_levels(gaps, current_price)

        # 如果缺口支撑位更高，更新支撑位
        if gap_levels['support'] is not None:
            if pd.isna(support[i]) or gap_levels['support'] > support[i]:
                support[i] = gap_levels['support']

        # 如果缺口压力位更低，更新压力位
        if gap_levels['resistance'] is not None:
            if pd.isna(resistance[i]) or gap_levels['resistance'] < resistance[i]:
                resistance[i] = gap_levels['resistance']

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
