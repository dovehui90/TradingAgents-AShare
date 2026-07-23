"""
趋势回调入场系统回测

核心思路: Stage 2 上涨趋势中，等回调到支撑位再入场
测试多种回调入场信号的胜率
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════
# 数据获取
# ═══════════════════════════════════════════════════════

def fetch_data(symbol: str, days: int = 1000) -> pd.DataFrame:
    """获取历史K线数据（多源回退）"""
    import akshare as ak
    from datetime import datetime, timedelta

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days + 150)).strftime("%Y%m%d")

    prefix = "sh" if symbol.startswith(("5", "6", "9")) else "sz"
    vendor = f"{prefix}{symbol}"

    df = None
    sources = [
        ("sina", lambda: ak.stock_zh_a_daily(symbol=vendor, start_date=start, end_date=end, adjust="qfq")),
        ("tencent", lambda: ak.stock_zh_a_hist_tx(symbol=vendor, start_date=start, end_date=end, adjust="qfq")),
        ("eastmoney", lambda: ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start, end_date=end, adjust="qfq")),
    ]

    for name, fetcher in sources:
        try:
            df = fetcher()
            if df is not None and not df.empty:
                break
        except Exception:
            continue

    if df is None or df.empty:
        raise ValueError(f"未获取到 {symbol} 数据")

    col_map = {"日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume"}
    df = df.rename(columns=col_map)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df.tail(days)


# ═══════════════════════════════════════════════════════
# 指标计算
# ═══════════════════════════════════════════════════════

def calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """计算所有需要的指标"""
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]

    # 均线
    df["ma5"] = c.rolling(5).mean()
    df["ma10"] = c.rolling(10).mean()
    df["ma20"] = c.rolling(20).mean()
    df["ma50"] = c.rolling(50).mean()
    df["ma150"] = c.rolling(150).mean()
    df["ma200"] = c.rolling(200).mean()

    # 成交量均线
    df["vol_ma5"] = v.rolling(5).mean()
    df["vol_ma20"] = v.rolling(20).mean()

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd_dif"] = ema12 - ema26
    df["macd_dea"] = df["macd_dif"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = (df["macd_dif"] - df["macd_dea"]) * 2

    # RSI
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # KDJ
    low_9 = l.rolling(9).min()
    high_9 = h.rolling(9).max()
    rsv = (c - low_9) / (high_9 - low_9) * 100
    df["k"] = rsv.ewm(com=2, adjust=False).mean()
    df["d"] = df["k"].ewm(com=2, adjust=False).mean()
    df["j"] = 3 * df["k"] - 2 * df["d"]

    # ATR (14日)
    tr = pd.concat([
        h - l,
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs()
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    df["atr_pct"] = df["atr"] / c * 100  # ATR百分比

    # 布林带
    df["bb_mid"] = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + 2 * bb_std
    df["bb_lower"] = df["bb_mid"] - 2 * bb_std

    # 最近N日高低点
    df["high_10"] = h.rolling(10).max()
    df["low_10"] = l.rolling(10).min()
    df["high_20"] = h.rolling(20).max()
    df["low_20"] = l.rolling(20).min()

    return df


# ═══════════════════════════════════════════════════════
# Stage 判断
# ═══════════════════════════════════════════════════════

def detect_stage_at(df: pd.DataFrame, idx: int) -> int:
    """在指定位置判断阶段"""
    if idx < 200:
        return 0

    close = df["close"]
    ma50 = close.iloc[max(0, idx-49):idx+1].mean()
    ma150 = close.iloc[max(0, idx-149):idx+1].mean()
    ma200 = close.iloc[max(0, idx-199):idx+1].mean()
    latest = close.iloc[idx]

    # 200MA 斜率
    if idx >= 60:
        ma200_recent = close.iloc[max(0, idx-19):idx+1].mean()
        ma200_prev = close.iloc[max(0, idx-59):idx-19].mean()
        ma200_rising = ma200_recent > ma200_prev
    else:
        ma200_rising = False

    bullish = latest > ma50 > ma150 > ma200

    if bullish and ma200_rising:
        return 2
    elif latest > ma200 and ma200_rising:
        return 1
    elif latest < ma200 and not ma200_rising:
        return 4
    else:
        return 3


# ═══════════════════════════════════════════════════════
# 信号策略定义
# ═══════════════════════════════════════════════════════

@dataclass
class Signal:
    """信号记录"""
    date: str
    price: float
    strategy: str
    reason: str
    # 回测用
    entry_price: float = 0.0
    exit_price: float = 0.0
    exit_date: str = ""
    exit_reason: str = ""
    pnl_pct: float = 0.0
    hold_days: int = 0
    win: bool = False


def strategy_ma_pullback(df: pd.DataFrame, idx: int) -> Optional[Signal]:
    """
    策略1: 均线回调买入
    条件:
    - Stage 2 (上涨趋势)
    - 价格回调到 MA20 附近 (±2%)
    - 当日收阳 (收盘 > 开盘)
    - 成交量萎缩 (量比 < 0.8, 说明抛压减弱)
    """
    if idx < 50:
        return None

    stage = detect_stage_at(df, idx)
    if stage != 2:
        return None

    close = df["close"].iloc[idx]
    open_ = df["open"].iloc[idx]
    ma20 = df["ma20"].iloc[idx]
    vol = df["volume"].iloc[idx]
    vol_ma20 = df["vol_ma20"].iloc[idx]

    if pd.isna(ma20) or pd.isna(vol_ma20) or vol_ma20 == 0:
        return None

    # 回调到 MA20 附近
    dist_to_ma20 = (close - ma20) / ma20
    near_ma20 = -0.02 <= dist_to_ma20 <= 0.02

    # 收阳
    is_yang = close > open_

    # 缩量
    vol_ratio = vol / vol_ma20
    vol_shrink = vol_ratio < 0.8

    if near_ma20 and is_yang and vol_shrink:
        return Signal(
            date=str(df.index[idx].date()),
            price=close,
            strategy="MA20回调",
            reason=f"Stage2+MA20附近({dist_to_ma20*100:.1f}%)+收阳+缩量({vol_ratio:.2f}x)",
        )
    return None


def strategy_macd_golden(df: pd.DataFrame, idx: int) -> Optional[Signal]:
    """
    策略2: MACD金叉买入
    条件:
    - Stage 2
    - MACD DIF 上穿 DEA (金叉)
    - 金叉位置在零轴附近或上方 (DIF > -0.5)
    - 金叉前DIF连续下降至少3天 (确认回调充分)
    """
    if idx < 60:
        return None

    stage = detect_stage_at(df, idx)
    if stage != 2:
        return None

    dif = df["macd_dif"].iloc[idx]
    dea = df["macd_dea"].iloc[idx]
    dif_prev = df["macd_dif"].iloc[idx-1]
    dea_prev = df["macd_dea"].iloc[idx-1]

    if pd.isna(dif) or pd.isna(dea) or pd.isna(dif_prev) or pd.isna(dea_prev):
        return None

    # 金叉: DIF从下穿上DEA
    golden_cross = dif_prev < dea_prev and dif > dea

    # 零轴附近或上方
    near_zero = dif > -0.5

    # DIF之前连续下降至少3天
    declining = 0
    for k in range(1, min(8, idx)):
        if df["macd_dif"].iloc[idx-k] < df["macd_dif"].iloc[idx-k-1]:
            declining += 1
        else:
            break
    enough_decline = declining >= 3

    if golden_cross and near_zero and enough_decline:
        return Signal(
            date=str(df.index[idx].date()),
            price=float(df["close"].iloc[idx]),
            strategy="MACD金叉",
            reason=f"Stage2+DIF上穿DEA+零轴附近(DIF={dif:.3f})+回调{declining}天",
        )
    return None


def strategy_rsi_oversold_bounce(df: pd.DataFrame, idx: int) -> Optional[Signal]:
    """
    策略3: RSI超卖反弹
    条件:
    - Stage 2
    - RSI 从下方回升到40以上 (前一日RSI<35, 当日RSI>40)
    - 收阳线
    """
    if idx < 50:
        return None

    stage = detect_stage_at(df, idx)
    if stage != 2:
        return None

    rsi = df["rsi"].iloc[idx]
    rsi_prev = df["rsi"].iloc[idx-1]
    close = df["close"].iloc[idx]
    open_ = df["open"].iloc[idx]

    if pd.isna(rsi) or pd.isna(rsi_prev):
        return None

    # RSI从超卖区回升
    bounced = rsi_prev < 35 and rsi > 40
    is_yang = close > open_

    if bounced and is_yang:
        return Signal(
            date=str(df.index[idx].date()),
            price=close,
            strategy="RSI超卖反弹",
            reason=f"Stage2+RSI回升({rsi_prev:.1f}->{rsi:.1f})+收阳",
        )
    return None


def strategy_bullish_engulfing(df: pd.DataFrame, idx: int) -> Optional[Signal]:
    """
    策略4: 阳包阴
    条件:
    - Stage 2
    - 前一日阴线, 当日阳线
    - 当日实体完全包住前一日实体
    - 成交量放大 (量比 > 1.2)
    """
    if idx < 50:
        return None

    stage = detect_stage_at(df, idx)
    if stage != 2:
        return None

    close_today = df["close"].iloc[idx]
    open_today = df["open"].iloc[idx]
    close_prev = df["close"].iloc[idx-1]
    open_prev = df["open"].iloc[idx-1]
    vol = df["volume"].iloc[idx]
    vol_ma20 = df["vol_ma20"].iloc[idx]

    if pd.isna(vol_ma20) or vol_ma20 == 0:
        return None

    # 前一日阴线
    prev_yin = close_prev < open_prev
    # 当日阳线
    today_yang = close_today > open_today
    # 实体包住
    engulfs = today_yang and prev_yin and close_today > open_prev and open_today < close_prev
    # 放量
    vol_ratio = vol / vol_ma20
    vol_up = vol_ratio > 1.2

    if engulfs and vol_up:
        return Signal(
            date=str(df.index[idx].date()),
            price=close_today,
            strategy="阳包阴",
            reason=f"Stage2+阳包阴+放量({vol_ratio:.2f}x)",
        )
    return None


def strategy_breakout_pullback(df: pd.DataFrame, idx: int) -> Optional[Signal]:
    """
    策略5: 突破回踩
    条件:
    - Stage 2
    - 前5-10日曾突破20日新高
    - 当日回踩到突破位附近 (±3%)
    - 缩量回踩 (量比 < 0.7)
    - RSI 不超买 (< 70)
    """
    if idx < 50:
        return None

    stage = detect_stage_at(df, idx)
    if stage != 2:
        return None

    close = df["close"].iloc[idx]
    vol = df["volume"].iloc[idx]
    vol_ma20 = df["vol_ma20"].iloc[idx]
    rsi = df["rsi"].iloc[idx]

    if pd.isna(vol_ma20) or vol_ma20 == 0 or pd.isna(rsi):
        return None

    # 前5-10日的最高点
    lookback_high = df["high"].iloc[idx-10:idx-4].max()
    # 当日是否回踩到突破位附近
    pullback = (close - lookback_high) / lookback_high
    near_breakout = -0.03 <= pullback <= 0.03

    # 缩量
    vol_ratio = vol / vol_ma20
    vol_shrink = vol_ratio < 0.7

    # RSI不超买
    not_overbought = rsi < 70

    if near_breakout and vol_shrink and not_overbought:
        return Signal(
            date=str(df.index[idx].date()),
            price=close,
            strategy="突破回踩",
            reason=f"Stage2+回踩突破位({pullback*100:.1f}%)+缩量({vol_ratio:.2f}x)+RSI={rsi:.0f}",
        )
    return None


def strategy_kdj_cross(df: pd.DataFrame, idx: int) -> Optional[Signal]:
    """
    策略6: KDJ金叉 + 趋势确认
    条件:
    - Stage 2
    - K上穿D (金叉)
    - J值从低位回升 (前一日J<20, 当日J>30)
    - 收盘在MA20上方
    """
    if idx < 50:
        return None

    stage = detect_stage_at(df, idx)
    if stage != 2:
        return None

    k = df["k"].iloc[idx]
    d = df["d"].iloc[idx]
    j = df["j"].iloc[idx]
    k_prev = df["k"].iloc[idx-1]
    d_prev = df["d"].iloc[idx-1]
    j_prev = df["j"].iloc[idx-1]
    close = df["close"].iloc[idx]
    ma20 = df["ma20"].iloc[idx]

    if any(pd.isna(x) for x in [k, d, j, k_prev, d_prev, j_prev, ma20]):
        return None

    golden = k_prev < d_prev and k > d
    j_bounce = j_prev < 20 and j > 30
    above_ma20 = close > ma20

    if golden and j_bounce and above_ma20:
        return Signal(
            date=str(df.index[idx].date()),
            price=close,
            strategy="KDJ金叉",
            reason=f"Stage2+KDJ金叉+J回升({j_prev:.0f}->{j:.0f})+站上MA20",
        )
    return None


# ═══════════════════════════════════════════════════════
# 回测引擎
# ═══════════════════════════════════════════════════════

@dataclass
class BacktestResult:
    """回测结果"""
    symbol: str
    strategy: str
    total_signals: int
    total_trades: int = 0
    win_trades: int = 0
    lose_trades: int = 0
    win_rate: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_factor: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_hold_days: float = 0.0
    trades: list = field(default_factory=list)
    signals: list = field(default_factory=list)


def run_backtest(
    symbol: str,
    strategy_fn,
    strategy_name: str,
    hold_days_limit: int = 15,
    stop_loss_pct: float = 0.07,
    take_profit_pct: float = 0.10,
) -> BacktestResult:
    """回测单个策略"""
    df = fetch_data(symbol, days=1000)
    df = calc_indicators(df)

    signals = []
    trades = []
    i = 252

    while i < len(df) - hold_days_limit:
        sig = strategy_fn(df, i)
        if sig is not None:
            signals.append(sig)

            # 模拟持仓
            entry_price = float(df["close"].iloc[i])
            exit_price = entry_price
            exit_date = sig.date
            exit_reason = "到期"
            hold_days = 0

            for j in range(1, hold_days_limit + 1):
                if i + j >= len(df):
                    break

                day_high = float(df["high"].iloc[i+j])
                day_low = float(df["low"].iloc[i+j])
                day_close = float(df["close"].iloc[i+j])
                hold_days = j

                if day_low <= entry_price * (1 - stop_loss_pct):
                    exit_price = entry_price * (1 - stop_loss_pct)
                    exit_date = str(df.index[i+j].date())
                    exit_reason = "止损"
                    break

                if day_high >= entry_price * (1 + take_profit_pct):
                    exit_price = entry_price * (1 + take_profit_pct)
                    exit_date = str(df.index[i+j].date())
                    exit_reason = "止盈"
                    break

                exit_price = day_close
                exit_date = str(df.index[i+j].date())

            pnl_pct = (exit_price / entry_price - 1) * 100

            trade = Signal(
                date=sig.date,
                price=sig.price,
                strategy=strategy_name,
                reason=sig.reason,
                entry_price=entry_price,
                exit_price=round(exit_price, 2),
                exit_date=exit_date,
                exit_reason=exit_reason,
                hold_days=hold_days,
                pnl_pct=round(pnl_pct, 2),
                win=pnl_pct > 0,
            )
            trades.append(trade)
            i += max(hold_days, 1) + 5
        else:
            i += 1

    result = BacktestResult(
        symbol=symbol,
        strategy=strategy_name,
        total_signals=len(signals),
        total_trades=len(trades),
        win_trades=sum(1 for t in trades if t.win),
        lose_trades=sum(1 for t in trades if not t.win),
        trades=trades,
        signals=signals,
    )

    if result.total_trades > 0:
        result.win_rate = result.win_trades / result.total_trades * 100
        wins = [t.pnl_pct for t in trades if t.win]
        losses = [t.pnl_pct for t in trades if not t.win]
        result.avg_win_pct = round(np.mean(wins), 2) if wins else 0
        result.avg_loss_pct = round(np.mean(losses), 2) if losses else 0
        result.avg_hold_days = round(np.mean([t.hold_days for t in trades]), 1)
        total_win = sum(wins)
        total_loss = abs(sum(losses))
        result.profit_factor = round(total_win / total_loss, 2) if total_loss > 0 else float("inf")

        cum = 1.0
        peak = 1.0
        max_dd = 0
        for t in trades:
            cum *= (1 + t.pnl_pct / 100)
            peak = max(peak, cum)
            dd = (peak - cum) / peak * 100
            max_dd = max(max_dd, dd)
        result.total_return_pct = round((cum - 1) * 100, 2)
        result.max_drawdown_pct = round(max_dd, 2)

    return result


# ═══════════════════════════════════════════════════════
# 报告
# ═══════════════════════════════════════════════════════

def format_result(r: BacktestResult) -> str:
    """格式化单个策略结果"""
    lines = []
    lines.append(f"  [{r.strategy}]")
    lines.append(f"    信号数: {r.total_signals}  交易数: {r.total_trades}")
    lines.append(f"    胜率: {r.win_rate:.1f}%  盈亏比: {r.profit_factor}:1")
    lines.append(f"    平均盈利: +{r.avg_win_pct:.2f}%  平均亏损: {r.avg_loss_pct:.2f}%")
    lines.append(f"    累计收益: {r.total_return_pct:+.2f}%  最大回撤: {r.max_drawdown_pct:.2f}%")
    lines.append(f"    平均持仓: {r.avg_hold_days:.1f}天")

    if r.trades:
        lines.append(f"    交易明细:")
        for t in r.trades:
            marker = "+" if t.pnl_pct > 0 else ""
            lines.append(
                f"      {t.date} -> {t.exit_date} | "
                f"{t.entry_price:.2f}->{t.exit_price:.2f} | "
                f"{marker}{t.pnl_pct:.2f}% | {t.exit_reason} | {t.reason}"
            )
    return "\n".join(lines)


def run_all_strategies(symbol: str, label: str = ""):
    """运行所有策略并汇总"""
    strategies = [
        (strategy_ma_pullback, "MA20回调"),
        (strategy_macd_golden, "MACD金叉"),
        (strategy_rsi_oversold_bounce, "RSI超卖反弹"),
        (strategy_bullish_engulfing, "阳包阴"),
        (strategy_breakout_pullback, "突破回踩"),
        (strategy_kdj_cross, "KDJ金叉"),
    ]

    title = f"{symbol} {label}".strip()
    print(f"\n{'='*70}")
    print(f"  趋势回调入场系统回测: {title}")
    print(f"{'='*70}")
    print(f"  参数: 止损-7% | 止盈+10% | 最大持仓15天")
    print(f"  前提: 仅在Stage 2(上涨阶段)中寻找买点")
    print(f"{'='*70}")

    all_results = []
    for fn, name in strategies:
        try:
            r = run_backtest(symbol, fn, name)
            print(format_result(r))
            all_results.append(r)
        except Exception as e:
            print(f"  [{name}] 回测失败: {e}")

    # 汇总对比
    print(f"\n{'='*70}")
    print(f"  策略对比汇总")
    print(f"{'='*70}")
    print(f"  {'策略':<14} {'信号':>5} {'交易':>5} {'胜率':>7} {'盈亏比':>8} {'累计收益':>10} {'最大回撤':>10}")
    print(f"  {'-'*62}")
    for r in all_results:
        print(
            f"  {r.strategy:<14} {r.total_signals:>5} {r.total_trades:>5} "
            f"{r.win_rate:>6.1f}% {r.profit_factor:>7.2f}:1 "
            f"{r.total_return_pct:>+9.2f}% {r.max_drawdown_pct:>9.2f}%"
        )

    # 最佳策略
    best = max(all_results, key=lambda x: x.profit_factor if x.total_trades > 0 else 0)
    if best.total_trades > 0:
        print(f"\n  最佳策略: {best.strategy} (盈亏比 {best.profit_factor}:1, 胜率 {best.win_rate:.1f}%)")

    print(f"\n{'='*70}")
    print(f"  [!] 仅供研究参考，不构成投资建议")
    print(f"{'='*70}")
    return all_results


# ═══════════════════════════════════════════════════════
# 参数扫描
# ═══════════════════════════════════════════════════════

def param_scan(symbol: str, strategy_fn, strategy_name: str):
    """扫描不同止损/止盈参数"""
    configs = [
        {"sl": 0.05, "tp": 0.08, "label": "SL5%_TP8%"},
        {"sl": 0.07, "tp": 0.08, "label": "SL7%_TP8%"},
        {"sl": 0.07, "tp": 0.10, "label": "SL7%_TP10%"},
        {"sl": 0.07, "tp": 0.15, "label": "SL7%_TP15%"},
        {"sl": 0.10, "tp": 0.15, "label": "SL10%_TP15%"},
        {"sl": 0.10, "tp": 0.20, "label": "SL10%_TP20%"},
    ]

    print(f"\n{'='*70}")
    print(f"  参数扫描: {symbol} - {strategy_name}")
    print(f"{'='*70}")
    print(f"  {'参数':<16} {'交易':>5} {'胜率':>7} {'盈亏比':>8} {'累计收益':>10} {'最大回撤':>10}")
    print(f"  {'-'*60}")

    for cfg in configs:
        try:
            r = run_backtest(symbol, strategy_fn, strategy_name,
                           stop_loss_pct=cfg["sl"], take_profit_pct=cfg["tp"])
            print(
                f"  {cfg['label']:<16} {r.total_trades:>5} "
                f"{r.win_rate:>6.1f}% {r.profit_factor:>7.2f}:1 "
                f"{r.total_return_pct:>+9.2f}% {r.max_drawdown_pct:>9.2f}%"
            )
        except Exception as e:
            print(f"  {cfg['label']:<16} 失败: {e}")

    print(f"{'='*70}")


# ═══════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    symbols = ["001203", "600519", "002475", "300750"]

    for sym in symbols:
        results = run_all_strategies(sym)
        print()

    # 对最佳策略做参数扫描
    print("\n>>> 对最优策略做参数扫描 <<<")
    for sym in symbols[:2]:
        try:
            param_scan(sym, strategy_ma_pullback, "MA20回调")
        except Exception as e:
            print(f"  {sym}: 扫描失败 - {e}")
