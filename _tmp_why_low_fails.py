"""分析：为什么低位胜率反而低？—— 回看过去涨跌 vs 未来涨跌"""
import io, pandas as pd, numpy as np
from datetime import datetime, timedelta
from tradingagents.dataflows.interface import route_to_vendor

sym = '300265.SZ'
end = datetime.now().strftime('%Y-%m-%d')
start = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')
raw = route_to_vendor("get_stock_data", symbol=sym, start_date=start, end_date=end)
df = pd.read_csv(io.StringIO(raw), comment="#")
df.columns = [c.lower().replace(" ", "_") for c in df.columns]
df["date"] = pd.to_datetime(df["date"])
df = df.set_index("date").sort_index()

close = df["close"]
high = df["high"]

# Features
low_60 = close.rolling(60).min()
high_60 = close.rolling(60).max()
range_pos = (close - low_60) / (high_60 - low_60) * 100

# Past returns
ret_5d = close / close.shift(5) - 1
ret_10d = close / close.shift(10) - 1
ret_20d = close / close.shift(20) - 1

# Future returns (label)
fwd_high_7 = high.rolling(7).max().shift(-7)
fwd_ret_7 = fwd_high_7 / close - 1
label_10 = fwd_ret_7 >= 0.10

# Volatility (amplitude)
atr_20 = (high - df["low"]).rolling(20).mean() / close * 100
volume_ratio = df["volume"] / df["volume"].rolling(20).mean()

valid = pd.DataFrame({
    "range_pos": range_pos,
    "ret_5d": ret_5d, "ret_10d": ret_10d, "ret_20d": ret_20d,
    "fwd_ret_7": fwd_ret_7, "label": label_10,
    "atr_20": atr_20, "vol_ratio": volume_ratio,
}).dropna()

print("低位为何胜率低？—— 过去走势 vs 未来走势")
print("=" * 65)

for label, lo, hi in [("深跌区 0-20%", 0, 20), ("低位 20-40%", 20, 40),
                        ("中位 40-60%", 40, 60), ("强势 60-80%", 60, 80),
                        ("高位 80-100%", 80, 100)]:
    sub = valid[(valid["range_pos"] >= lo) & (valid["range_pos"] < hi)]
    if len(sub) == 0: continue
    print(f"\n{label}: {len(sub)}天")
    print(f"  过去5日涨跌:    {sub['ret_5d'].mean()*100:+.1f}%")
    print(f"  过去10日涨跌:   {sub['ret_10d'].mean()*100:+.1f}%")
    print(f"  过去20日涨跌:   {sub['ret_20d'].mean()*100:+.1f}%")
    print(f"  未来7日最大涨幅: {sub['fwd_ret_7'].mean()*100:+.1f}%")
    print(f"  7日>10%胜率:     {sub['label'].mean()*100:.1f}%")
    print(f"  平均振幅(ATR%):  {sub['atr_20'].mean():.1f}%")
    print(f"  平均量比:        {sub['vol_ratio'].mean():.2f}")

# Check: what happens after the stock enters bottom zone?
# Does it stay there or bounce?
print(f"\n\n低位持续性分析：进入底部20%后...")
bottom_days = valid[valid["range_pos"] < 20]
for days_ahead in [1, 3, 5, 10, 20]:
    future_pos = range_pos.shift(-days_ahead)
    # For days that are now bottom, where are they N days later?
    paired = pd.DataFrame({"now": valid["range_pos"], "future": future_pos}).dropna()
    was_bottom = paired[paired["now"] < 20]
    if len(was_bottom) == 0: continue
    still_bottom = (was_bottom["future"] < 20).mean() * 100
    avg_future_pos = was_bottom["future"].mean()
    print(f"  {days_ahead}日后: 仍<20%的占{still_bottom:.0f}%, 平均位置升至{avg_future_pos:.1f}")

# Trend classification
print(f"\n\n趋势状态 vs 胜率:")
valid["trend"] = "震荡"
valid.loc[valid["ret_10d"] > 0.05, "trend"] = "上升"
valid.loc[valid["ret_10d"] < -0.05, "trend"] = "下跌"
for trend in ["上升", "震荡", "下跌"]:
    sub = valid[valid["trend"] == trend]
    if len(sub) < 5: continue
    print(f"  {trend}: {len(sub)}天, 7日>10%胜率={sub['label'].mean()*100:.1f}%, 平均涨幅={sub['fwd_ret_7'].mean()*100:+.1f}%")
