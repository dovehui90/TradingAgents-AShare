"""选股神器历史回看：从各指标的全序列中逐日抽取所有维度的信号。

所有指标函数（niuxiong_line、position_index、gs_strategy、trend_strength、
radar_indicator）本就返回完整时间序列，本模块把「每天一行」的信号抽取出来，
供按交易日分文件存储与历史回看。
"""

import math

from .position_index import get_position_transition


def _missing(v) -> bool:
    """判断指标值是否缺失（None 或 NaN）。"""
    if v is None:
        return True
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return False


# 周线 GS 的 zone 回溯周数（日线用 60 根交易日，周线对应半年约 26 周）
WEEKLY_GS_ZONE_LOOKBACK = 26


def derive_gs_states(gs_buy, gs_sell, zone_lookback: int = 60) -> list:
    """逐 bar 计算 GS 状态（G/S/G_zone/S_zone/None）。

    与 derive_daily_signals 原先内联的 GS 判定逻辑一致，抽出供日线(60)/周线(26)共用。

    Args:
        gs_buy/gs_sell: 等长布尔序列（须已 fillna，不含 NaN）。
        zone_lookback: 距最近一次 G/S 信号超过该 bar 数后，zone 归 None。

    Returns:
        等长的状态列表，bar i 的 GS 状态（G/S/G_zone/S_zone/None）。
    """
    states: list = []
    last_sig = None
    last_sig_age = 1_000_000
    for i in range(len(gs_buy)):
        if bool(gs_buy[i]):
            states.append("G")
            last_sig, last_sig_age = "G", 0
        elif bool(gs_sell[i]):
            states.append("S")
            last_sig, last_sig_age = "S", 0
        else:
            last_sig_age += 1
            states.append(
                (last_sig + "_zone")
                if (last_sig is not None and last_sig_age <= zone_lookback)
                else None
            )
    return states


def derive_daily_signals(
    dates,
    close,
    decision_line,
    bull_line,
    orbit_line,
    zones,
    gs_buy,
    gs_sell,
    trend_strength,
    radar_wave,
    symbol,
) -> list:
    """从各指标全序列中逐日抽取所有维度信号。

    与 _compute_screener_signals 的判定逻辑保持一致，但作用于每一根 K 线。
    首日（index 0）无前一日，跳过不产出。

    Args:
        dates: 等长序列，日期（YYYY-MM-DD 字符串或可 str 化）。
        close/decision_line/bull_line/orbit_line/zones/gs_buy/gs_sell/
        trend_strength/radar_wave: 等长序列，各指标逐日值。
        symbol: 股票代码。

    Returns:
        [{date, symbol, price, change_pct, position_zone, position_transition,
          decision_status, bull_status, orbit_status, gs_status, trend_status,
          radar_wave}, ...]
    """
    n = len(dates)
    rows: list = []

    # GS 状态机（日线 60 根回溯）：逐 bar 预计算，bar 0 不产出但影响后续 zone
    gs_states = derive_gs_states(gs_buy, gs_sell, zone_lookback=60)

    for i in range(1, n):
        c = close[i]
        prev_c = close[i - 1]

        price = round(float(c), 2) if not _missing(c) else None
        change_pct = None
        if not _missing(c) and not _missing(prev_c) and prev_c != 0:
            change_pct = round(float((c - prev_c) / prev_c * 100), 2)

        # 决策线 / 牛熊线
        decision_status = None
        if not _missing(decision_line[i]):
            decision_status = "above" if c > decision_line[i] else "below"
        bull_status = None
        if not _missing(bull_line[i]):
            bull_status = "above" if c > bull_line[i] else "below"

        # 轨道线（跨日 crossover + 持续）
        orbit_status = None
        o = orbit_line[i]
        if not _missing(o):
            po = orbit_line[i - 1]
            if not _missing(po) and not _missing(prev_c):
                if prev_c <= po and c > o:
                    orbit_status = "cross_up"
                elif prev_c >= po and c < o:
                    orbit_status = "cross_down"
                elif c > o:
                    orbit_status = "above2"
                elif c < o:
                    orbit_status = "below2"
            else:
                orbit_status = "above2" if c > o else ("below2" if c < o else None)

        # 位置指标（含单日转变）
        zone = str(zones[i]) if zones[i] is not None else None
        prev_zone = str(zones[i - 1]) if zones[i - 1] is not None else None
        transition = get_position_transition(prev_zone, zone)

        # GS 信号（G/S/G_zone/S_zone）
        gs_status = gs_states[i]

        # 中线趋势（翻红/翻绿/持红/持绿）
        prev_trend = [v for v in trend_strength[max(0, i - 5):i] if not _missing(v)]
        had_red = any(float(v) > 0 for v in prev_trend)
        cur_trend = float(trend_strength[i]) if not _missing(trend_strength[i]) else 0.0
        if cur_trend > 0:
            trend_status = "red_hold" if had_red else "to_red"
        else:
            trend_status = "to_green" if had_red else "green_hold"

        # 主力雷达
        rw = round(float(radar_wave[i]), 2) if not _missing(radar_wave[i]) else None

        rows.append({
            "date": str(dates[i]),
            "symbol": symbol,
            "price": price,
            "change_pct": change_pct,
            "position_zone": zone,
            "position_transition": transition,
            "decision_status": decision_status,
            "bull_status": bull_status,
            "orbit_status": orbit_status,
            "gs_status": gs_status,
            "trend_status": trend_status,
            "radar_wave": rw,
        })
    return rows


def derive_weekly_gs_status(week_keys, gs_buy, gs_sell,
                            zone_lookback: int = WEEKLY_GS_ZONE_LOOKBACK) -> dict:
    """周线 GS 状态按 ISO 周键返回 {week_key: status}。

    供选股神器历史回看使用：先算周线 GS 状态机，再按 ISO 周键映射，让同周各日共享该周状态。

    Args:
        week_keys: 每个周 bar 的 ISO 周键（"YYYY-WNN"，与 _aggregate_daily_df 同口径），等长。
        gs_buy/gs_sell: 等长布尔序列（周线 gs_buy/gs_sell，须已 fillna）。
        zone_lookback: 周线 zone 回溯周数（默认 26）。

    Returns:
        {week_key: gs_status} 映射。
    """
    states = derive_gs_states(gs_buy, gs_sell, zone_lookback)
    return {k: s for k, s in zip(week_keys, states)}
