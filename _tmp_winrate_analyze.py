"""分析：各因子条件下7日内>10%的胜率，找出高胜率因子组合"""
import io, pandas as pd, numpy as np
from datetime import datetime, timedelta
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.buy_point.buy_point_service import BuyPointService

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

# Label: 7日内最高价涨幅 >= 10%
fwd_high_7 = high.rolling(7).max().shift(-7)
label = (fwd_high_7 / close - 1) >= 0.10

# Features from BuyPointService
svc = BuyPointService.from_raw_kline(df, symbol=sym)
facts = svc.facts

# Merge features
features = pd.DataFrame(index=facts.index)
features["label"] = label
features["range_pos"] = (close - close.rolling(60).min()) / (close.rolling(60).max() - close.rolling(60).min()) * 100
features["bollinger_position"] = facts.get("bollinger_position", np.nan)
features["niuxiong_direction"] = facts.get("niuxiong_direction", "")
features["gs_buy"] = facts.get("gs_buy", False).astype(bool)
features["signal_chain"] = (features["niuxiong_direction"] == "多头") & features["gs_buy"]
features["position_zone"] = facts.get("position_zone", "")
features["volume_wash_state"] = facts.get("volume_wash_state", "")
features["consecutive_yang"] = facts.get("consecutive_yang", 0)
features["consecutive_yin"] = facts.get("consecutive_yin", 0)
features["gs_bias"] = facts.get("gs_bias", 0)
features["macd_hist_trend"] = facts.get("macd_hist_trend", "")

for k in ["is_SC","is_BC","is_ST","is_spring","is_SOW","bottom_fractal","top_fractal",
          "bollinger_cross_lp","bollinger_warning"]:
    features[k] = facts.get(k, False).astype(bool)

# K-line patterns
from tradingagents.indicators.candlestick_patterns import pattern_registry
for p in pattern_registry():
    col = p["column"]
    if col in facts.columns:
        features[col] = facts[col].astype(bool)

valid = features.dropna(subset=["range_pos","label"])

print(f"300265 胜率分析 — 标签: 7日内最高涨幅>=10%")
print(f"总样本: {len(valid)}  正样本: {valid['label'].sum()}  基线胜率: {valid['label'].mean()*100:.1f}%")
print(f"信号链样本: {valid['signal_chain'].sum()}  信号链胜率: {valid[valid['signal_chain']]['label'].mean()*100:.1f}%")

# Test individual factor conditions for win rate
def test_cond(name, mask):
    sub = valid[mask]
    if len(sub) < 5:
        return None
    wr = sub["label"].mean() * 100
    return (name, len(sub), wr)

results = []

# Range position buckets
for lo, hi, nm in [(0,20,"底部0-20"),(20,40,"低位20-40"),(40,60,"中位40-60"),(60,80,"强势60-80"),(80,100,"高位80-100")]:
    r = test_cond(nm, (valid["range_pos"]>=lo)&(valid["range_pos"]<hi))
    if r: results.append(r)

# Bollinger
results.append(test_cond("布林<20", valid["bollinger_position"] < 20))
results.append(test_cond("布林<30", valid["bollinger_position"] < 30))
results.append(test_cond("布林>70", valid["bollinger_position"] > 70))
results.append(test_cond("布林20-50", (valid["bollinger_position"]>=20)&(valid["bollinger_position"]<50)))

# Position zone
for zone in ["oversold","low","neutral","high","overbought"]:
    r = test_cond(f"zone={zone}", valid["position_zone"]==zone)
    if r: results.append(r)

# Volume wash
for state in valid["volume_wash_state"].unique():
    if pd.isna(state): continue
    r = test_cond(f"量能={state}", valid["volume_wash_state"]==state)
    if r: results.append(r)

# Consecutive yang/yin
results.append(test_cond("连阳>=3", valid["consecutive_yang"] >= 3))
results.append(test_cond("连阴>=3", valid["consecutive_yin"] >= 3))
results.append(test_cond("连阳>=2", valid["consecutive_yang"] >= 2))

# MACD
for trend in valid["macd_hist_trend"].dropna().unique():
    r = test_cond(f"MACD={trend}", valid["macd_hist_trend"]==trend)
    if r: results.append(r)

# Wyckoff
for k in ["is_SC","is_BC","is_ST","is_spring","is_SOW"]:
    r = test_cond(k, valid[k])
    if r: results.append(r)

# Bottom fractal
results.append(test_cond("底分型", valid["bottom_fractal"]))
results.append(test_cond("底分型+范围<50", valid["bottom_fractal"] & (valid["range_pos"]<50)))

# GS bias
results.append(test_cond("GS乖离>0", valid["gs_bias"] > 0))
results.append(test_cond("GS乖离>5", valid["gs_bias"] > 5))
results.append(test_cond("GS乖离<-5", valid["gs_bias"] < -5))

# Combined conditions
results.append(test_cond("强势区+连阳>=2", (valid["range_pos"]>=60)&(valid["consecutive_yang"]>=2)))
results.append(test_cond("强势区+GS乖离>0", (valid["range_pos"]>=60)&(valid["gs_bias"]>0)))
results.append(test_cond("强势区+放量突破", (valid["range_pos"]>=60)&(valid["volume_wash_state"]=="放量突破")))
results.append(test_cond("底分型+布林<30", valid["bottom_fractal"] & (valid["bollinger_position"]<30)))
results.append(test_cond("is_SC+布林<30", valid["is_SC"] & (valid["bollinger_position"]<30)))
results.append(test_cond("信号链+强势区", valid["signal_chain"] & (valid["range_pos"]>=50)))
results.append(test_cond("信号链+布林<50", valid["signal_chain"] & (valid["bollinger_position"]<50)))
results.append(test_cond("信号链+底分型", valid["signal_chain"] & valid["bottom_fractal"]))
results.append(test_cond("信号链+GS乖离>5", valid["signal_chain"] & (valid["gs_bias"]>5)))

# Sort by win rate
results = [r for r in results if r is not None and r[1] >= 5]
results.sort(key=lambda x: x[2], reverse=True)

print(f"\n{'条件':<28} {'样本':<8} {'胜率':<8}")
print("-" * 44)
for name, cnt, wr in results[:30]:
    bar = "█" * int(wr/5)
    print(f"{name:<28} {cnt:<8} {wr:.1f}% {bar}")
