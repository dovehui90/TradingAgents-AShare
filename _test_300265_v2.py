import io, pandas as pd
from datetime import datetime, timedelta
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.buy_point.buy_point_service import BuyPointService
from tradingagents.buy_point.condition_parser import ConfirmSpec, Condition
from tradingagents.buy_point.chain_backtest import compare_specs

sym = '300265.SZ'
end = datetime.now().strftime('%Y-%m-%d')
start = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')
raw = route_to_vendor("get_stock_data", symbol=sym, start_date=start, end_date=end)
df = pd.read_csv(io.StringIO(raw), comment="#")
df.columns = [c.lower().replace(" ", "_") for c in df.columns]
df["date"] = pd.to_datetime(df["date"])
df = df.set_index("date").sort_index()

svc = BuyPointService.from_raw_kline(df, symbol=sym)

# Compare: baseline vs 启明星 vs 布林 vs 启明星+布林
specs = {
    "基线(无确认)": None,
    "启明星确认": ConfirmSpec(name="启明星", logic="all", conditions=[
        Condition(factor="pattern_morning_star", op="eq", value=True),
    ]),
    "布林<80": ConfirmSpec(name="布林安全", logic="all", conditions=[
        Condition(factor="bollinger_position", op="lt", value=80),
    ]),
    "布林30-70": ConfirmSpec(name="布林中位", logic="all", conditions=[
        Condition(factor="bollinger_position", op="between", value=[30, 70]),
    ]),
    "启明星+布林<80": ConfirmSpec(name="双确认", logic="all", conditions=[
        Condition(factor="pattern_morning_star", op="eq", value=True),
        Condition(factor="bollinger_position", op="lt", value=80),
    ]),
}

cmp = compare_specs(svc.facts, specs)

print("=" * 80)
print("  通光线缆 300265 — 确认条件对比")
print("=" * 80)
print(cmp.to_string())

# Show trade-by-trade for the best filter
print("\n" + "=" * 80)
print("  最优方案逐笔明细")
print("=" * 80)

# Find best by win_rate
best_label = cmp["win_rate"].idxmax()
best_spec = specs[best_label]
trades_result = svc.backtest(confirm_spec={
    "name": best_label,
    "logic": best_spec.logic if best_spec else "all",
    "conditions": [{"factor": c.factor, "op": c.op, "value": c.value} for c in (best_spec.conditions if best_spec else [])],
} if best_spec else None)

print(f"方案: {best_label}")
print(f"交易: {trades_result['stats']['total_trades']}笔  胜率: {trades_result['stats']['win_rate']}%  均收益: {trades_result['stats']['avg_return_pct']}%  累计: {trades_result['stats']['total_return_pct']}%")
print()

baseline_trades = svc.backtest()
filtered_trades = trades_result['trades']
filtered_dates = {t['entry_date'] for t in filtered_trades}

print(f"{'基线交易':<40} {'确认后'}")
print("-" * 60)
for t in baseline_trades['trades']:
    kept = t['entry_date'] in filtered_dates
    marker = "KEEP" if kept else "DROP"
    print(f"{t['entry_date']} {t['return_pct']:+6.2f}% {t['hold_days']:3d}d [{t['exit_reason']:<12}] -> [{marker}]")

# Summary of improvement
bl_wr = cmp.loc["基线(无确认)", "win_rate"]
bl_ret = cmp.loc["基线(无确认)", "avg_return_pct"]
best_wr = cmp.loc[best_label, "win_rate"]
best_ret = cmp.loc[best_label, "avg_return_pct"]
print(f"\n基线: 胜率{bl_wr}% 均收益{bl_ret}%")
print(f"最优: 胜率{best_wr}% 均收益{best_ret}%")
print(f"提升: 胜率+{best_wr - bl_wr}pp 均收益+{best_ret - bl_ret}%")
print("Done.")
