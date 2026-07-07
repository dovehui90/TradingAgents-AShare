"""
All-days ML backtest v3 — 对比新模型(5新特征) vs 信号链基线
"""
import io, sys, pandas as pd, numpy as np
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.buy_point.buy_point_service import BuyPointService
from tradingagents.buy_point.chain_backtest import run_baseline, run_backtest_alldays, BacktestConfig

MODEL_PATH = Path(__file__).parent / "tradingagents" / "buy_point" / "buypoint_model_v4.json"

SYMBOLS = [
    # 创业板高波动
    "300265.SZ", "300750.SZ", "300059.SZ", "300274.SZ", "300502.SZ",
    "300394.SZ", "300024.SZ", "300014.SZ", "300433.SZ", "300122.SZ",
    # 主板科技/制造
    "600498.SH", "600519.SH", "601127.SH", "601012.SH", "600118.SH",
    "600760.SH", "603501.SH", "603986.SH", "603259.SH", "603019.SH",
]

config = BacktestConfig(stop_loss_pct=-5, take_profit_pct=3, max_hold_days=7, atr_multiplier=1.0)

def is_long_bear(raw_df: pd.DataFrame) -> bool:
    """判断是否长期空头：MA60趋势下行 + 整体负收益"""
    close = raw_df["close"]
    ma60 = close.rolling(60).mean()
    n = len(ma60)
    if n < 120:
        return False
    mid = n // 2
    ma60_recent = ma60.iloc[mid:].mean()
    ma60_early = ma60.iloc[:mid].mean()
    slope = (ma60_recent - ma60_early) / ma60_early * 100
    below_pct = (close < ma60).sum() / n
    total_ret = (close.iloc[-1] - close.iloc[0]) / close.iloc[0] * 100
    # 任一条件触发即过滤：MA60下行 + 受压 或 总收益大幅为负
    return (slope < -10.0 and below_pct > 0.50) or total_ret < -25.0

all_results = []
skipped = []

for sym in SYMBOLS:
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
    raw = route_to_vendor("get_stock_data", symbol=sym, start_date=start, end_date=end)
    df = pd.read_csv(io.StringIO(raw), comment="#")
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    # 过滤长期空头股
    if is_long_bear(df):
        skipped.append(sym)
        print(f"{sym}: 长期空头，跳过")
        continue

    svc = BuyPointService.from_raw_kline(df, symbol=sym, skip_merge=True)
    facts = svc.facts
    total_days = len(facts)

    # Baseline
    _, base_stats = run_baseline(facts, config)

    # All-days ML at various thresholds
    best_t = None
    best_wr = 0
    best_trades = 0
    best_total = 0
    for t in [0.4, 0.5, 0.55, 0.6, 0.65]:
        _, ml_stats = run_backtest_alldays(facts, model_path=str(MODEL_PATH), threshold=t, config=config)
        trades_per_year = ml_stats['total_trades'] / 2
        wr = ml_stats['win_rate']
        total_ret = ml_stats['total_return_pct']
        print(f"  {sym} th={t:.2f}: {ml_stats['total_trades']:3d}笔 胜率{wr:5.1f}% 均收益{ml_stats['avg_return_pct']:+5.1f}% 总收益{total_ret:+6.1f}% 年均{trades_per_year:.0f}笔")
        if ml_stats['total_trades'] > 0 and (wr > best_wr or (wr == best_wr and ml_stats['total_trades'] > best_trades)):
            best_wr = wr
            best_t = t
            best_trades = ml_stats['total_trades']
            best_total = total_ret

    all_results.append({
        "symbol": sym, "days": total_days,
        "base_trades": base_stats['total_trades'], "base_wr": base_stats['win_rate'],
        "base_total": base_stats['total_return_pct'],
        "best_th": best_t, "ml_trades": best_trades, "ml_wr": best_wr,
    })

    print(f"\n{sym} ({total_days}天):")
    print(f"  信号链基线: {base_stats['total_trades']:3d}笔 胜率{base_stats['win_rate']:5.1f}% 总收益{base_stats['total_return_pct']:+6.1f}%")
    if best_t is not None:
        print(f"  ML全天最优: th={best_t:.2f} {best_trades:3d}笔 胜率{best_wr:5.1f}%")
    else:
        print(f"  ML全天: 无信号(波动率过低，不适合该策略)")
    print()

# Summary
print(f"\n{'='*70}")
print(f"汇总:")
for r in all_results:
    bt = f"{r['best_th']:.2f}" if r['best_th'] is not None else "N/A"
    print(f"  {r['symbol']:12s}: 基线{r['base_trades']:3d}笔{r['base_wr']:5.1f}% | ML_th={bt} {r['ml_trades']:3d}笔{r['ml_wr']:5.1f}%")

avg_base_wr = np.mean([r['base_wr'] for r in all_results])
avg_ml_wr = np.mean([r['ml_wr'] for r in all_results])
total_base = sum(r['base_trades'] for r in all_results)
total_ml = sum(r['ml_trades'] for r in all_results)
print(f"  平均胜率: 基线{avg_base_wr:.1f}% vs ML{avg_ml_wr:.1f}%")
print(f"  总交易数: 基线{total_base} vs ML{total_ml}")
if skipped:
    print(f"  已跳过(长期空头): {', '.join(skipped)}")
