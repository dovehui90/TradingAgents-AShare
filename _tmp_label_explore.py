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

# Compute forward max returns within windows 1,3,5,7 days
close = df["close"]
high = df["high"]

for w in [1, 3, 5, 7]:
    # max high in forward window / entry close - 1
    fwd_high = high.rolling(w).max().shift(-w)
    fwd_ret = fwd_high / close - 1
    df[f"fwd_max_{w}d"] = fwd_ret

# Range position as feature
low_60 = close.rolling(60).min()
high_60 = close.rolling(60).max()
df["range_pos"] = (close - low_60) / (high_60 - low_60) * 100

# Signal chain
svc = BuyPointService.from_raw_kline(df, symbol=sym)
facts = svc.facts
df["niuxiong_direction"] = facts["niuxiong_direction"]
df["gs_buy"] = facts["gs_buy"].astype(bool)
df["signal_chain"] = (df["niuxiong_direction"] == "多头") & df["gs_buy"]

valid = df.dropna(subset=["range_pos"] + [f"fwd_max_{w}d" for w in [1,3,5,7]]).copy()

print(f"通光线缆 300265 — 短线标签分析 (1-7日)")
print(f"{'='*60}")
print(f"总交易日: {len(df)}  有效样本: {len(valid)}  信号链样本: {valid['signal_chain'].sum()}")
print()

# For each window + threshold, count samples
thresholds = [0.03, 0.05, 0.08, 0.10]
print(f"{'窗口':<6} {'阈值':<6} {'总样本':<8} {'信号链中':<10} {'全样本占比':<10}")
print("-" * 50)
for w in [1, 3, 5, 7]:
    col = f"fwd_max_{w}d"
    for t in thresholds:
        mask = valid[col] >= t
        total = mask.sum()
        sig = valid.loc[mask & valid["signal_chain"], col].count()
        pct = total / len(valid) * 100
        print(f"{w}日     >={t:.0%}    {total:<8} {sig:<10} {pct:.1f}%")

# Bucket: range_pos vs short-term returns
print(f"\n各区间位置的短线平均收益:")
print(f"{'区间':<12} {'1日':<8} {'3日':<8} {'5日':<8} {'7日':<8} {'样本':<6}")
print("-" * 50)
for label, (lo, hi) in [("0-20%",(0,20)),("20-40%",(20,40)),("40-60%",(40,60)),("60-80%",(60,80)),("80-100%",(80,100))]:
    sub = valid[(valid["range_pos"] >= lo) & (valid["range_pos"] < hi)]
    if len(sub) == 0:
        continue
    vals = [f"{sub[f'fwd_max_{w}d'].mean()*100:.1f}%" for w in [1,3,5,7]]
    print(f"{label:<12} {vals[0]:<8} {vals[1]:<8} {vals[2]:<8} {vals[3]:<8} {len(sub):<6}")

# What % of days can hit >10% within 7 days?
print(f"\n核心指标 — 各区间能命中>10%的概率:")
for label, (lo, hi) in [("0-20%",(0,20)),("20-40%",(20,40)),("40-60%",(40,60)),("60-80%",(60,80)),("80-100%",(80,100))]:
    sub = valid[(valid["range_pos"] >= lo) & (valid["range_pos"] < hi)]
    if len(sub) == 0:
        continue
    for w in [3,5,7]:
        hit = (sub[f"fwd_max_{w}d"] >= 0.10).sum()
        print(f"  {label} {w}日内>10%: {hit}/{len(sub)} = {hit/len(sub)*100:.1f}%")

# Signal chain days specifically
sig_days = valid[valid["signal_chain"]]
if len(sig_days) > 0:
    print(f"\n信号链日短线表现 (共{len(sig_days)}天):")
    for w in [1,3,5,7]:
        col = f"fwd_max_{w}d"
        avg = sig_days[col].mean()
        hit5 = (sig_days[col] >= 0.05).sum()
        hit10 = (sig_days[col] >= 0.10).sum()
        print(f"  {w}日: 均值{avg*100:.1f}%  >5%:{hit5}/{len(sig_days)}  >10%:{hit10}/{len(sig_days)}")
