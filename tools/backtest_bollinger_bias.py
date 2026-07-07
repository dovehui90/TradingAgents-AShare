"""
布林乖离 + 乖离率 联合信号回测 v2
对比三种信号源：BD-only / Bias-only / BD+Bias联合
"""
import sys
sys.path.insert(0, ".")
import pandas as pd
import numpy as np
from tradingagents.indicators import fetch_realtime_data
from tradingagents.indicators.bollinger_deviation import calculate_bollinger_deviation

STOCKS = [
    "000001.SZ", "600519.SH", "000858.SZ", "601318.SH", "002415.SZ",
    "300750.SZ", "600036.SH", "000333.SZ", "601012.SH", "603259.SH",
    "000002.SZ", "601166.SH", "600887.SH", "300059.SZ", "688981.SH",
]
HOLD_DAYS = [1, 3, 5, 10]
BIAS_WINDOW = 252


def rolling_pct(series, window):
    def _pct(x):
        return (x.iloc[-1] <= x).mean() * 100
    return series.rolling(window).apply(_pct, raw=False)


def backtest_stock(symbol: str) -> list:
    try:
        df = fetch_realtime_data(symbol, days=600, period="daily")
    except Exception as e:
        return []

    if len(df) < 120:
        return []

    bd = calculate_bollinger_deviation(df)
    close = df["close"].astype(float)
    ma13 = close.rolling(13).mean()
    bias_pct = (close - ma13) / ma13 * 100

    combined = pd.DataFrame({
        "close": close,
        "mccd": bd["mccd"],
        "ub": bd["ub"], "lb": bd["lb"],
        "uub": bd["uub"], "llb": bd["llb"],
        "is_cross_lp": bd["is_cross_lp"],
        "is_warning": bd["is_warning"],
        "bias_pct": bias_pct,
    }, index=df.index)

    combined["bias_rank"] = rolling_pct(combined["bias_pct"].ffill(), BIAS_WINDOW)

    # ── 定义信号 ──
    signals = {
        # BD buy signals
        "BD_乖离反转": combined["is_cross_lp"],
        "BD_极端超卖(买)": combined["mccd"] < combined["llb"],
        # BD sell signals
        "BD_顶部警示(卖)": combined["is_warning"],
        "BD_超买(卖)": combined["mccd"] > combined["ub"],
        # Bias buy signals
        "Bias_低乖离(买)": combined["bias_rank"] < 15,
        # Bias sell signals
        "Bias_高乖离(卖)": combined["bias_rank"] > 85,
    }

    # 联合信号：BD + 乖离率分位数加成
    # 乖离反转 + 偏低乖离 → 更强买点
    signals["联合_反转+偏低(买)"] = combined["is_cross_lp"] & (combined["bias_rank"] < 35)
    # 极端超卖 + 低乖离 → 最强买点
    signals["联合_超卖+低乖离(买)"] = (combined["mccd"] < combined["llb"]) & (combined["bias_rank"] < 25)
    # 顶部警示 + 偏高乖离 → 更强卖点
    signals["联合_警示+偏高(卖)"] = combined["is_warning"] & (combined["bias_rank"] > 65)
    # 超买 + 高乖离 → 最强卖点
    signals["联合_超买+高乖离(卖)"] = (combined["mccd"] > combined["ub"]) & (combined["bias_rank"] > 75)

    results = []
    for n in HOLD_DAYS:
        fwd_ret = combined["close"].pct_change(n).shift(-n) * 100
        valid = fwd_ret.notna()
        cutoff = len(combined) - n

        for sig_name, sig_mask in signals.items():
            mask = sig_mask & valid
            mask.iloc[cutoff:] = False
            if mask.sum() < 10:
                continue

            rets = fwd_ret[mask]
            is_buy = "(买)" in sig_name
            if is_buy:
                win = (rets > 0).sum()
            else:
                win = (rets < 0).sum()

            results.append({
                "stock": symbol,
                "signal": sig_name,
                "days": n,
                "count": len(rets),
                "win%": round(win / len(rets) * 100, 1),
                "avg_ret%": round(rets.mean(), 2),
            })

    return results


def main():
    print("=" * 80)
    print("BollingerDeviation + Bias Joint Backtest v2")
    print("Stocks: %d | Hold: %s | Bias rolling: %dd" % (
        len(STOCKS), HOLD_DAYS, BIAS_WINDOW))
    print("=" * 80)

    all_results = []
    for sym in STOCKS:
        res = backtest_stock(sym)
        all_results.extend(res)
        print(f"  {sym}: {len(res)} records")

    if not all_results:
        print("No data")
        return

    df = pd.DataFrame(all_results)

    # ── 汇总表1: 按持有期 × 信号 ──
    for n in HOLD_DAYS:
        print(f"\n{'─' * 70}")
        print(f"  Hold {n}d")
        print(f"{'─' * 70}")
        sub = df[df["days"] == n].groupby("signal").agg(
            total=("count", "sum"),
            win_rate=("win%", "mean"),
            avg_ret=("avg_ret%", "mean"),
        ).round(1).sort_values("win_rate", ascending=False)
        print(sub.to_string())

    # ── 汇总表2: 信号族对比 (跨持有期均值) ──
    print(f"\n{'=' * 80}")
    print("SIGNAL FAMILY COMPARISON (avg across all periods)")
    print(f"{'─' * 80}")

    def family(s):
        if s.startswith("BD_"): return "BD-only"
        if s.startswith("Bias_"): return "Bias-only"
        if s.startswith("联合"): return "Joint"
        return "Other"

    df["family"] = df["signal"].apply(family)
    summary = df.groupby("family").agg(
        total_signals=("count", "sum"),
        avg_win=("win%", "mean"),
        avg_ret=("avg_ret%", "mean"),
        median_win=("win%", "median"),
    ).round(1).sort_values("avg_win", ascending=False)
    print(summary.to_string())

    # ── 汇总表3: 信号排名 ──
    print(f"\n{'=' * 80}")
    print("SIGNAL RANKING (cross-period avg, min 50 total)")
    print(f"{'─' * 80}")
    rank = df.groupby("signal").agg(
        total=("count", "sum"),
        win_rate=("win%", "mean"),
        avg_ret=("avg_ret%", "mean"),
    ).round(1).query("total >= 50").sort_values("win_rate", ascending=False)
    print(rank.to_string())

    print(f"\n{'=' * 80}")
    print("Done.")


if __name__ == "__main__":
    main()
