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

    # gs 最近信号跟踪（bar 0 不产出，但影响 bar 1 的 zone）
    last_sig = None
    last_sig_age = 1_000_000
    if n > 0:
        if bool(gs_buy[0]):
            last_sig, last_sig_age = "G", 0
        elif bool(gs_sell[0]):
            last_sig, last_sig_age = "S", 0

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
        if bool(gs_buy[i]):
            gs_status = "G"
            last_sig, last_sig_age = "G", 0
        elif bool(gs_sell[i]):
            gs_status = "S"
            last_sig, last_sig_age = "S", 0
        else:
            last_sig_age += 1
            gs_status = (last_sig + "_zone") if (last_sig is not None and last_sig_age <= 60) else None

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
