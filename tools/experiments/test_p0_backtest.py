"""
P0 策略回测 — 验证四阶段+趋势模板+量价确认的胜率

用法: python test_p0_backtest.py
"""

import sys
import numpy as np
import pandas as pd
from dataclasses import dataclass, field


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
# 信号检测（逐日计算）
# ═══════════════════════════════════════════════════════

def detect_stage_for_df(df: pd.DataFrame, idx: int) -> int:
    """在指定位置判断阶段，返回 stage 编号"""
    if idx < 200:
        return 0

    close = df["close"]
    # 用 idx 之前的 200 日计算 MA
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
    bearish = latest < ma50 < ma150 < ma200

    if bullish and ma200_rising:
        return 2
    elif bearish and not ma200_rising:
        return 4
    elif ma200_rising and latest > ma200:
        return 1  # 1.5 → 用 1 表示过渡
    elif not ma200_rising and latest < ma200:
        return 3
    else:
        return 2 if latest > ma200 else 4


def check_template_for_df(df: pd.DataFrame, idx: int) -> int:
    """在指定位置检查趋势模板，返回通过数"""
    if idx < 252:
        return 0

    close = df["close"]
    latest = close.iloc[idx]
    ma50 = close.iloc[idx-49:idx+1].mean()
    ma150 = close.iloc[idx-149:idx+1].mean()
    ma200 = close.iloc[idx-199:idx+1].mean()

    # 条件3: 200MA 上升
    ma200_now = close.iloc[idx-199:idx+1].mean()
    ma200_1m = close.iloc[max(0,idx-220):idx-19].mean() if idx > 220 else close.iloc[0:200].mean()
    cond3 = ma200_now > ma200_1m

    # 52周高低
    low_52w = close.iloc[max(0,idx-251):idx+1].min()
    high_52w = close.iloc[max(0,idx-251):idx+1].max()

    cond6 = (latest / low_52w - 1) >= 0.30
    cond7 = (1 - latest / high_52w) <= 0.25

    # 12月涨幅
    ret_12m = latest / close.iloc[idx-252] - 1 if idx >= 252 else 0
    cond8 = ret_12m >= 0.30

    conditions = [
        latest > ma150 and latest > ma200,     # 1
        ma150 > ma200,                          # 2
        cond3,                                  # 3
        ma50 > ma150 and ma50 > ma200,          # 4
        latest > ma50,                          # 5
        cond6,                                  # 6
        cond7,                                  # 7
        cond8,                                  # 8
    ]

    return sum(conditions)


def check_volume_for_df(df: pd.DataFrame, idx: int) -> dict:
    """在指定位置检查量价"""
    if idx < 20:
        return {"vol_ratio": 0, "breakout_ok": False, "vdu": False}

    volume = df["volume"]
    vol_today = volume.iloc[idx]
    vol_ma20 = volume.iloc[max(0,idx-19):idx+1].mean()
    vol_ratio = vol_today / vol_ma20 if vol_ma20 > 0 else 0

    # VDU
    vol_10min = volume.iloc[max(0,idx-9):idx+1].min()
    vdu = vol_today <= vol_ma20 * 0.6 and vol_today <= vol_10min * 1.1

    return {
        "vol_ratio": round(vol_ratio, 2),
        "breakout_ok": vol_ratio >= 1.5,
        "vdu": vdu,
    }


# ═══════════════════════════════════════════════════════
# 回测引擎
# ═══════════════════════════════════════════════════════

@dataclass
class Trade:
    """单笔交易记录"""
    entry_date: str
    entry_price: float
    exit_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    hold_days: int = 0
    pnl_pct: float = 0.0
    win: bool = False


@dataclass
class BacktestResult:
    """回测结果"""
    symbol: str
    total_days: int
    total_trades: int
    win_trades: int
    lose_trades: int
    win_rate: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_factor: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_hold_days: float = 0.0
    trades: list = field(default_factory=list)


def run_backtest(
    symbol: str,
    hold_days_limit: int = 20,
    stop_loss_pct: float = 0.07,
    take_profit_pct: float = 0.08,
) -> BacktestResult:
    """
    回测 P0 策略

    入场条件:
    - Stage = 2（上涨阶段）
    - 趋势模板 >= 7/8
    - 量比 >= 1.2x（放宽到1.2x以便捕捉更多信号）

    出场条件:
    - 止损: -7%
    - 止盈: +8%
    - 最大持有: 20日
    """
    df = fetch_data(symbol, days=1000)
    trades = []

    i = 252  # 跳过前252日（需要52周数据）

    while i < len(df) - hold_days_limit:
        stage = detect_stage_for_df(df, i)
        template = check_template_for_df(df, i)
        vol = check_volume_for_df(df, i)

        # 入场判断
        is_buy = (
            stage == 2
            and template >= 7
            and vol["vol_ratio"] >= 1.2
        )

        if not is_buy:
            i += 1
            continue

        # 入场
        entry_price = float(df["close"].iloc[i])
        entry_date = str(df.index[i].date())

        # 模拟持仓
        exit_price = entry_price
        exit_date = entry_date
        exit_reason = "到期"
        hold_days = 0

        for j in range(1, hold_days_limit + 1):
            if i + j >= len(df):
                break

            day_high = float(df["high"].iloc[i+j])
            day_low = float(df["low"].iloc[i+j])
            day_close = float(df["close"].iloc[i+j])
            hold_days = j

            # 止损检查（日内低点触及）
            if day_low <= entry_price * (1 - stop_loss_pct):
                exit_price = entry_price * (1 - stop_loss_pct)
                exit_date = str(df.index[i+j].date())
                exit_reason = "止损"
                break

            # 止盈检查
            if day_high >= entry_price * (1 + take_profit_pct):
                exit_price = entry_price * (1 + take_profit_pct)
                exit_date = str(df.index[i+j].date())
                exit_reason = "止盈"
                break

            exit_price = day_close
            exit_date = str(df.index[i+j].date())

        pnl_pct = (exit_price / entry_price - 1) * 100

        trade = Trade(
            entry_date=entry_date,
            entry_price=entry_price,
            exit_date=exit_date,
            exit_price=round(exit_price, 2),
            exit_reason=exit_reason,
            hold_days=hold_days,
            pnl_pct=round(pnl_pct, 2),
            win=pnl_pct > 0,
        )
        trades.append(trade)

        # 跳过持仓期，避免重叠
        i += max(hold_days, 1) + 5
        continue

    # 汇总统计
    result = BacktestResult(
        symbol=symbol,
        total_days=len(df),
        total_trades=len(trades),
        win_trades=sum(1 for t in trades if t.win),
        lose_trades=sum(1 for t in trades if not t.win),
        trades=trades,
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

        # 累计收益
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
# 报告输出
# ═══════════════════════════════════════════════════════

def format_report(result: BacktestResult) -> str:
    """格式化回测报告"""
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"  P0 策略回测: {result.symbol}")
    lines.append(f"{'='*60}")
    lines.append(f"  数据天数: {result.total_days}")
    lines.append(f"  总交易数: {result.total_trades}")
    lines.append(f"  盈利次数: {result.win_trades}")
    lines.append(f"  亏损次数: {result.lose_trades}")
    lines.append(f"  胜率: {result.win_rate:.1f}%")
    lines.append(f"  平均盈利: +{result.avg_win_pct:.2f}%")
    lines.append(f"  平均亏损: {result.avg_loss_pct:.2f}%")
    lines.append(f"  盈亏比: {result.profit_factor}:1")
    lines.append(f"  累计收益: {result.total_return_pct:+.2f}%")
    lines.append(f"  最大回撤: {result.max_drawdown_pct:.2f}%")
    lines.append(f"  平均持仓: {result.avg_hold_days:.1f}天")
    lines.append(f"{'='*60}")

    if result.trades:
        lines.append(f"\n  交易明细:")
        lines.append(f"  {'入场日期':<12} {'入场价':>8} {'出场日期':<12} {'出场价':>8} {'收益%':>8} {'原因':<6}")
        lines.append(f"  {'-'*58}")
        for t in result.trades:
            marker = "+" if t.pnl_pct > 0 else ""
            lines.append(
                f"  {t.entry_date:<12} {t.entry_price:>8.2f} "
                f"{t.exit_date:<12} {t.exit_price:>8.2f} "
                f"{marker}{t.pnl_pct:>7.2f}% {t.exit_reason:<6}"
            )

    lines.append(f"\n{'='*60}")
    lines.append(f"  [!] 仅供研究参考，不构成投资建议")
    lines.append(f"{'='*60}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# 参数扫描（不同止损/止盈组合）
# ═══════════════════════════════════════════════════════

def param_scan(symbol: str):
    """扫描不同参数组合的回测结果"""
    configs = [
        {"stop_loss_pct": 0.05, "take_profit_pct": 0.08, "label": "SL5%_TP8%"},
        {"stop_loss_pct": 0.07, "take_profit_pct": 0.08, "label": "SL7%_TP8%"},
        {"stop_loss_pct": 0.07, "take_profit_pct": 0.10, "label": "SL7%_TP10%"},
        {"stop_loss_pct": 0.07, "take_profit_pct": 0.15, "label": "SL7%_TP15%"},
        {"stop_loss_pct": 0.10, "take_profit_pct": 0.15, "label": "SL10%_TP15%"},
        {"stop_loss_pct": 0.05, "take_profit_pct": 0.15, "label": "SL5%_TP15%"},
    ]

    print(f"\n{'='*80}")
    print(f"  参数扫描: {symbol}")
    print(f"{'='*80}")
    print(f"  {'参数':<16} {'交易数':>6} {'胜率':>8} {'盈亏比':>8} {'累计收益':>10} {'最大回撤':>10} {'均持天':>8}")
    print(f"  {'-'*72}")

    for cfg in configs:
        r = run_backtest(
            symbol,
            stop_loss_pct=cfg["stop_loss_pct"],
            take_profit_pct=cfg["take_profit_pct"],
        )
        print(
            f"  {cfg['label']:<16} {r.total_trades:>6} "
            f"{r.win_rate:>7.1f}% {r.profit_factor:>7.2f}:1 "
            f"{r.total_return_pct:>+9.2f}% {r.max_drawdown_pct:>9.2f}% "
            f"{r.avg_hold_days:>7.1f}"
        )

    print(f"{'='*80}")


# ═══════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    symbols = ["600519", "002475", "300750", "601012"]

    for sym in symbols:
        try:
            result = run_backtest(sym)
            print(format_report(result))
            print()
        except Exception as e:
            print(f"  {sym}: 回测失败 - {e}")
            print()

    # 参数扫描
    for sym in symbols[:2]:
        try:
            param_scan(sym)
        except Exception as e:
            print(f"  {sym}: 参数扫描失败 - {e}")
