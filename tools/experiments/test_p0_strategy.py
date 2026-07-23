"""
P0 策略独立测试 — SEPA 四阶段 + 趋势模板 + 量价确认 + 仓位管理

不修改任何项目文件，独立运行验证。
用法: python test_p0_strategy.py [股票代码]
示例: python test_p0_strategy.py 600519
"""

import sys
import numpy as np
import pandas as pd
from dataclasses import dataclass


# ═══════════════════════════════════════════════════════
# 数据获取（复用项目 Tushare 源）
# ═══════════════════════════════════════════════════════

def fetch_data(symbol: str, days: int = 500) -> pd.DataFrame:
    """获取历史K线数据（前复权，多源回退）"""
    import akshare as ak
    from datetime import datetime, timedelta

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days + 150)).strftime("%Y%m%d")

    is_index = symbol in {"000001", "399001", "399006", "000300"}
    prefix = "sh" if symbol.startswith(("5", "6", "9")) else "sz"
    vendor = f"{prefix}{symbol}"

    df = None
    last_exc = None

    # 多源回退: Sina → Tencent → Eastmoney
    sources = []
    if is_index:
        sources.append(("tencent_index", lambda: ak.stock_zh_index_daily_em(symbol=vendor, start_date=start, end_date=end)))
    else:
        sources += [
            ("sina", lambda: ak.stock_zh_a_daily(symbol=vendor, start_date=start, end_date=end, adjust="qfq")),
            ("tencent", lambda: ak.stock_zh_a_hist_tx(symbol=vendor, start_date=start, end_date=end, adjust="qfq")),
            ("eastmoney", lambda: ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start, end_date=end, adjust="qfq")),
        ]

    for name, fetcher in sources:
        try:
            df = fetcher()
            if df is not None and not df.empty:
                break
        except Exception as e:
            last_exc = e
            continue

    if df is None or df.empty:
        raise ValueError(f"未获取到 {symbol} 数据: {last_exc}")

    col_map = {"日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume",
                "成交额": "amount", "换手率": "turnover_rate"}
    df = df.rename(columns=col_map)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df.tail(days)


# ═══════════════════════════════════════════════════════
# P0-1: 四阶段分析 + 8项趋势模板
# ═══════════════════════════════════════════════════════

@dataclass
class TrendTemplateResult:
    """8项趋势模板检测结果"""
    condition_1: bool  # Price > 150MA AND Price > 200MA
    condition_2: bool  # 150MA > 200MA
    condition_3: bool  # 200MA 上升 ≥1个月
    condition_4: bool  # 50MA > 150MA AND 50MA > 200MA
    condition_5: bool  # Price > 50MA
    condition_6: bool  # Price ≥ 30% above 52-week low
    condition_7: bool  # Price within 25% of 52-week high
    condition_8: bool  # 相对强度 > 70th percentile (简化: 近12月涨幅)
    pass_count: int
    all_pass: bool
    details: dict


def detect_stage(df: pd.DataFrame) -> tuple[int, str]:
    """
    四阶段分析（基于 Weinstein 阶段理论）

    Stage 1: 筑底 — 价格在200MA附近横盘，200MA走平/下降
    Stage 2: 上涨 — 价格>50MA>150MA>200MA，200MA上升
    Stage 3: 见顶 — 高位大幅震荡，假突破频繁
    Stage 4: 下跌 — 价格跌破所有均线

    Returns: (stage_number, stage_name)
    """
    close = df["close"]
    ma50 = close.rolling(50).mean()
    ma150 = close.rolling(150).mean()
    ma200 = close.rolling(200).mean()

    if len(df) < 200:
        return (0, "数据不足")

    latest = close.iloc[-1]
    ma50_val = ma50.iloc[-1]
    ma150_val = ma150.iloc[-1]
    ma200_val = ma200.iloc[-1]

    # 200MA 斜率（最近20日 vs 40日前）
    ma200_recent = ma200.iloc[-20:].mean()
    ma200_prev = ma200.iloc[-60:-40].mean() if len(ma200) > 60 else ma200.iloc[0]
    ma200_rising = ma200_recent > ma200_prev

    # MA 排列
    bullish_alignment = latest > ma50_val > ma150_val > ma200_val
    bearish_alignment = latest < ma50_val < ma150_val < ma200_val

    # 52周高低点
    high_52w = close.iloc[-252:].max() if len(close) >= 252 else close.max()
    low_52w = close.iloc[-252:].min() if len(close) >= 252 else close.min()

    # 阶段判断
    if bullish_alignment and ma200_rising:
        return (2, "Stage 2 上涨")
    elif bearish_alignment and not ma200_rising:
        return (4, "Stage 4 下跌")
    elif ma200_rising and latest > ma200_val and not bullish_alignment:
        # 价格在200MA上方但MA未完全排列 → 可能Stage 1→2过渡
        return (1.5, "Stage 1→2 过渡")
    elif not ma200_rising and latest < ma200_val and not bearish_alignment:
        return (3.5, "Stage 3→4 过渡")
    elif abs(latest - ma200_val) / ma200_val < 0.05 and not ma200_rising:
        return (1, "Stage 1 筑底")
    else:
        # 根据价格位置推断
        if latest > ma200_val:
            return (2.5, "Stage 2 中期（MA未完全排列）")
        else:
            return (3, "Stage 3 见顶/震荡")


def check_trend_template(df: pd.DataFrame) -> TrendTemplateResult:
    """
    SEPA 8项趋势模板（全部满足才通过）

    条件 1-5: MA阶梯 Price > 50MA > 150MA > 200MA, 200MA上升
    条件 6-7: 价格位置（距低点≥30%, 距高点≤25%）
    条件 8: 相对强度（简化为12月涨幅排名）
    """
    close = df["close"]
    ma50 = close.rolling(50).mean()
    ma150 = close.rolling(150).mean()
    ma200 = close.rolling(200).mean()

    if len(df) < 252:
        # 数据不足252日，跳过部分条件
        latest = close.iloc[-1]
        return TrendTemplateResult(
            condition_1=False, condition_2=False, condition_3=False,
            condition_4=False, condition_5=False, condition_6=False,
            condition_7=False, condition_8=False,
            pass_count=0, all_pass=False,
            details={"error": f"数据不足: 仅{len(df)}日, 需要至少252日"}
        )

    latest = close.iloc[-1]
    ma50_val = ma50.iloc[-1]
    ma150_val = ma150.iloc[-1]
    ma200_val = ma200.iloc[-1]

    # 条件3: 200MA上升 ≥1个月
    ma200_now = ma200.iloc[-1]
    ma200_1m_ago = ma200.iloc[-22] if len(ma200) > 22 else ma200.iloc[0]
    cond3 = ma200_now > ma200_1m_ago

    # 条件6: 距52周低点 ≥ 30%
    low_52w = close.iloc[-252:].min()
    pct_above_low = (latest / low_52w - 1) * 100
    cond6 = pct_above_low >= 30

    # 条件7: 距52周高点 ≤ 25%
    high_52w = close.iloc[-252:].max()
    pct_from_high = (1 - latest / high_52w) * 100
    cond7 = pct_from_high <= 25

    # 条件8: 相对强度（简化: 12月涨幅，阈值50%作为粗略过滤）
    ret_12m = (latest / close.iloc[-252] - 1) * 100 if len(close) >= 252 else 0
    # A股没有相对标普的RS，用绝对涨幅代替，≥30%算通过
    cond8 = ret_12m >= 30

    conditions = [
        latest > ma150_val and latest > ma200_val,   # 1
        ma150_val > ma200_val,                         # 2
        cond3,                                          # 3
        ma50_val > ma150_val and ma50_val > ma200_val, # 4
        latest > ma50_val,                              # 5
        cond6,                                          # 6
        cond7,                                          # 7
        cond8,                                          # 8
    ]

    pass_count = sum(conditions)

    details = {
        "Price": f"{latest:.2f}",
        "50MA": f"{ma50_val:.2f}",
        "150MA": f"{ma150_val:.2f}",
        "200MA": f"{ma200_val:.2f}",
        "200MA上升": "是" if cond3 else "否",
        "距52周低": f"+{pct_above_low:.1f}%",
        "距52周高": f"-{pct_from_high:.1f}%",
        "12月涨幅": f"{ret_12m:.1f}%",
    }

    labels = [
        "Price>150MA&200MA",
        "150MA>200MA",
        "200MA上升",
        "50MA>150MA&200MA",
        "Price>50MA",
        "距低点≥30%",
        "距高点≤25%",
        "12月涨幅≥30%",
    ]

    for i, (c, label) in enumerate(zip(conditions, labels)):
        details[f"#{i+1} {label}"] = "PASS" if c else "FAIL"

    return TrendTemplateResult(
        condition_1=conditions[0],
        condition_2=conditions[1],
        condition_3=conditions[2],
        condition_4=conditions[3],
        condition_5=conditions[4],
        condition_6=conditions[5],
        condition_7=conditions[6],
        condition_8=conditions[7],
        pass_count=pass_count,
        all_pass=all(conditions),
        details=details,
    )


# ═══════════════════════════════════════════════════════
# P0-2: 量价确认规则
# ═══════════════════════════════════════════════════════

@dataclass
class VolumeConfirmation:
    """量价确认结果"""
    volume_ratio: float        # 当日量 / 20日均量
    vdu: bool                  # 成交量干涸（缩量到多周低点）
    breakout_volume_ok: bool   # 突破量 ≥ 1.5x
    volume_trend: str          # "放量" / "缩量" / "平量"
    signal_quality: str        # "强" / "中" / "弱" / "无效"


def check_volume_confirmation(df: pd.DataFrame) -> VolumeConfirmation:
    """
    量价确认规则

    1. 突破量 ≥ 1.5x 20日均量（标准确认）
    2. VDU: 成交量干涸 — 当日量 < 20日均量的60%，且是近10日最低
    3. 量价配合: 上涨+放量=健康, 上涨+缩量=可疑
    """
    volume = df["volume"]
    close = df["close"]

    vol_20ma = volume.rolling(20).mean()
    vol_today = volume.iloc[-1]
    vol_ma20 = vol_20ma.iloc[-1]

    # 量比
    vol_ratio = vol_today / vol_ma20 if vol_ma20 > 0 else 0

    # VDU（成交量干涸）
    vol_10min = volume.iloc[-10:].min()
    vol_dry_up = vol_today <= vol_ma20 * 0.6 and vol_today <= vol_10min * 1.1

    # 突破量确认
    breakout_ok = vol_ratio >= 1.5

    # 量趋势
    if vol_ratio >= 1.5:
        vol_trend = "放量"
    elif vol_ratio <= 0.6:
        vol_trend = "缩量"
    else:
        vol_trend = "平量"

    # 信号质量综合判断
    price_up = close.iloc[-1] > close.iloc[-2]
    if breakout_ok and price_up:
        quality = "强"
    elif breakout_ok and not price_up:
        quality = "中（放量下跌，需警惕）"
    elif vol_dry_up and price_up:
        quality = "中（缩量上涨，等待放量确认）"
    elif vol_dry_up:
        quality = "弱（缩量，观望）"
    else:
        quality = "中"

    return VolumeConfirmation(
        volume_ratio=round(vol_ratio, 2),
        vdu=vol_dry_up,
        breakout_volume_ok=breakout_ok,
        volume_trend=vol_trend,
        signal_quality=quality,
    )


# ═══════════════════════════════════════════════════════
# P0-3: 仓位管理 + 三阶段止损
# ═══════════════════════════════════════════════════════

@dataclass
class PositionSizing:
    """仓位计算结果"""
    entry_price: float
    stop_price: float
    stop_pct: float
    shares: int
    position_value: float
    position_pct: float
    risk_amount: float
    target_1: float
    target_2: float
    reward_risk_1: float
    reward_risk_2: float


def calculate_position(
    entry_price: float,
    account_value: float = 100_000,
    risk_pct: float = 0.01,
    stop_pct: float = 0.07,
) -> PositionSizing:
    """
    仓位管理公式（SEPA）

    股数 = (账户 × 风险%) ÷ (入场价 - 止损价)
    止损: 入场价 - 7%
    目标1: 入场价 + 8%（卖半仓，移保本）
    目标2: 入场价 + 15%（卖25%，移20MA追踪）
    """
    stop_price = entry_price * (1 - stop_pct)
    stop_distance = entry_price - stop_price

    risk_amount = account_value * risk_pct
    shares = int(risk_amount / stop_distance) if stop_distance > 0 else 0
    position_value = shares * entry_price
    position_pct = position_value / account_value * 100

    target_1 = entry_price * 1.08
    target_2 = entry_price * 1.15

    rr_1 = (target_1 - entry_price) / stop_distance if stop_distance > 0 else 0
    rr_2 = (target_2 - entry_price) / stop_distance if stop_distance > 0 else 0

    return PositionSizing(
        entry_price=entry_price,
        stop_price=round(stop_price, 2),
        stop_pct=stop_pct * 100,
        shares=shares,
        position_value=round(position_value, 2),
        position_pct=round(position_pct, 2),
        risk_amount=round(risk_amount, 2),
        target_1=round(target_1, 2),
        target_2=round(target_2, 2),
        reward_risk_1=round(rr_1, 2),
        reward_risk_2=round(rr_2, 2),
    )


# ═══════════════════════════════════════════════════════
# 市场环境判断
# ═══════════════════════════════════════════════════════

def assess_market_env(index_df: pd.DataFrame) -> dict:
    """
    市场环境判断（大盘指数）

    牛市: 指数 > 200MA, 宽度扩张
    震荡: 指数在200MA附近震荡
    熊市: 指数 < 200MA
    """
    if len(index_df) < 200:
        return {"env": "数据不足", "risk_pct": 0.01, "max_positions": 6}

    close = index_df["close"]
    ma200 = close.rolling(200).mean()
    ma50 = close.rolling(50).mean()

    latest = close.iloc[-1]
    ma200_val = ma200.iloc[-1]
    ma50_val = ma50.iloc[-1]

    pct_above_200 = (latest / ma200_val - 1) * 100

    if latest > ma200_val and ma50_val > ma200_val and pct_above_200 > 3:
        return {"env": "牛市", "risk_pct": 0.015, "max_positions": 8}
    elif latest < ma200_val and pct_above_200 < -3:
        return {"env": "熊市", "risk_pct": 0.0, "max_positions": 0}
    else:
        return {"env": "震荡", "risk_pct": 0.008, "max_positions": 3}


# ═══════════════════════════════════════════════════════
# 综合分析
# ═══════════════════════════════════════════════════════

def full_analysis(symbol: str, index_code: str = "000300") -> str:
    """完整 P0 策略分析"""
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"  P0 策略分析: {symbol}")
    lines.append(f"{'='*60}")

    # 获取个股数据
    try:
        df = fetch_data(symbol, days=500)
    except Exception as e:
        return f"数据获取失败: {e}"

    # 获取大盘数据
    try:
        index_df = fetch_data(index_code, days=300)
    except Exception:
        index_df = None

    # === P0-1: 阶段分析 ===
    lines.append("\n【P0-1】四阶段分析")
    lines.append("-" * 40)
    stage_num, stage_name = detect_stage(df)
    lines.append(f"  当前阶段: {stage_name}")
    if stage_num == 2:
        lines.append("  → 处于上涨阶段，可寻找买点")
    elif stage_num < 2:
        lines.append("  → 尚未进入上涨阶段，观望")
    else:
        lines.append("  → 已过上涨阶段，回避")

    # === P0-1: 趋势模板 ===
    lines.append(f"\n【P0-1】8项趋势模板")
    lines.append("-" * 40)
    template = check_trend_template(df)
    for key, val in template.details.items():
        if key.startswith("#"):
            lines.append(f"  {key}: {val}")
    lines.append(f"  通过: {template.pass_count}/8")
    lines.append(f"  结论: {'全部通过 [OK]' if template.all_pass else '未完全通过 [X]'}")

    # === P0-2: 量价确认 ===
    lines.append(f"\n【P0-2】量价确认")
    lines.append("-" * 40)
    vol = check_volume_confirmation(df)
    lines.append(f"  量比(今日/20MA): {vol.volume_ratio}x")
    lines.append(f"  VDU(缩量干涸): {'是' if vol.vdu else '否'}")
    lines.append(f"  突破量≥1.5x: {'是' if vol.breakout_volume_ok else '否'}")
    lines.append(f"  量趋势: {vol.volume_trend}")
    lines.append(f"  信号质量: {vol.signal_quality}")

    # === P0-3: 仓位管理 ===
    lines.append(f"\n【P0-3】仓位管理")
    lines.append("-" * 40)
    latest_price = float(df["close"].iloc[-1])
    pos = calculate_position(latest_price, account_value=100_000)
    lines.append(f"  入场价: {pos.entry_price:.2f}")
    lines.append(f"  止损价: {pos.stop_price} (-{pos.stop_pct:.2f}%)")
    lines.append(f"  仓位: {pos.shares}股 ≈ CNY{pos.position_value} ({pos.position_pct}%)")
    lines.append(f"  风险金额: CNY{pos.risk_amount}")
    lines.append(f"  目标1(+8%): {pos.target_1} (R/R={pos.reward_risk_1}:1)")
    lines.append(f"  目标2(+15%): {pos.target_2} (R/R={pos.reward_risk_2}:1)")
    if pos.reward_risk_1 < 2:
        lines.append(f"  [!] 风险回报比不足2:1，建议观望")

    # === 市场环境 ===
    if index_df is not None:
        lines.append(f"\n【市场环境】(沪深300)")
        lines.append("-" * 40)
        env = assess_market_env(index_df)
        lines.append(f"  环境: {env['env']}")
        lines.append(f"  单笔风险: {env['risk_pct']*100}%")
        lines.append(f"  最大持仓数: {env['max_positions']}")

    # === 综合结论 ===
    lines.append(f"\n{'='*60}")
    lines.append("  综合结论")
    lines.append(f"{'='*60}")

    score = 0
    reasons_buy = []
    reasons_wait = []

    # 阶段评分 (满分3)
    if stage_num == 2:
        score += 3
        reasons_buy.append("阶段2上涨")
    elif stage_num in (1.5, 2.5):  # 过渡阶段
        score += 1
        reasons_wait.append(f"阶段过渡({stage_name})")
    elif stage_num < 2:
        reasons_wait.append("未达阶段2")
    else:
        reasons_wait.append("已过阶段2")

    # 趋势模板评分 (满分3)
    if template.all_pass:
        score += 3
        reasons_buy.append(f"趋势模板全过({template.pass_count}/8)")
    elif template.pass_count >= 7:
        score += 2
        reasons_wait.append(f"趋势模板接近全过({template.pass_count}/8)")
    elif template.pass_count >= 5:
        score += 1
        reasons_wait.append(f"趋势模板部分通过({template.pass_count}/8)")
    else:
        reasons_wait.append(f"趋势模板不足({template.pass_count}/8)")

    # 量价评分 (满分2)
    if vol.breakout_volume_ok:
        score += 2
        reasons_buy.append("量价配合良好")
    elif vol.vdu:
        score += 1
        reasons_wait.append("缩量中，等待放量")
    else:
        reasons_wait.append(f"量比偏低({vol.volume_ratio}x)")

    # 风险回报比评分 (满分1)
    if pos.reward_risk_1 >= 2:
        score += 1
        reasons_buy.append(f"风险回报比达标({pos.reward_risk_1}:1)")

    # 综合判定
    if score >= 7:
        verdict = "强烈买入"
        verdict_detail = "各条件高度满足，可考虑建仓"
    elif score >= 5:
        verdict = "买入/轻仓"
        verdict_detail = "条件较好，可轻仓试探"
    elif score >= 3:
        verdict = "观望"
        verdict_detail = "部分条件满足，等待更好时机"
    else:
        verdict = "回避"
        verdict_detail = "条件不满足，不建议操作"

    lines.append(f"  评分: {score}/9")
    lines.append(f"  判定: {verdict}")
    lines.append(f"  {verdict_detail}")

    if reasons_buy:
        lines.append(f"  看多: {', '.join(reasons_buy)}")
    if reasons_wait:
        lines.append(f"  观望: {', '.join(reasons_wait)}")

    lines.append(f"\n{'='*60}")
    lines.append("  [!] 仅供研究参考，不构成投资建议")
    lines.append(f"{'='*60}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["600519", "000001", "300750"]

    for sym in symbols:
        print(full_analysis(sym))
        print()
