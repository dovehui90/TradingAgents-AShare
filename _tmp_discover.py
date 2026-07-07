"""
正确思路：全样本 → 按次日涨跌分组 → 对比特征差异 → 跟踪后续走势
"""
import io, pandas as pd, numpy as np
from datetime import datetime, timedelta
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.buy_point.buy_point_service import BuyPointService
from tradingagents.indicators.candlestick_patterns import pattern_registry

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
low = df["low"]
volume = df["volume"]

# === Labels ===
next_ret = close.shift(-1) / close - 1       # T+1 收益
next_day_up = next_ret > 0                    # 次日上涨
next_day_up_2pct = next_ret > 0.02            # 次日涨>2%

# Multi-day future returns
for w in [3, 5, 7]:
    fwd_high = high.rolling(w).max().shift(-w)
    df[f"fwd_max_{w}d"] = fwd_high / close - 1

# === Features from BuyPointService ===
svc = BuyPointService.from_raw_kline(df, symbol=sym)
facts = svc.facts

feat = pd.DataFrame(index=facts.index)

# Price position
feat["range_pos"] = (close - close.rolling(60).min()) / (close.rolling(60).max() - close.rolling(60).min()) * 100
feat["ret_1d"] = close / close.shift(1) - 1
feat["ret_3d"] = close / close.shift(3) - 1
feat["ret_5d"] = close / close.shift(5) - 1
feat["ret_10d"] = close / close.shift(10) - 1
feat["ret_20d"] = close / close.shift(20) - 1

# Amplitude & volume
feat["amplitude"] = (high - low) / close.shift(1) * 100
feat["vol_ratio"] = volume / volume.rolling(20).mean()
feat["vol_change"] = volume / volume.shift(1)

# Technical factors from facts
for col in ["bollinger_position", "gs_bias", "consecutive_yang", "consecutive_yin",
            "position_percentile"]:
    if col in facts.columns:
        feat[col] = pd.to_numeric(facts[col], errors="coerce")

for col in ["niuxiong_direction", "position_zone", "volume_wash_state", "macd_hist_trend",
            "volume_state", "body_direction"]:
    if col in facts.columns:
        feat[col] = facts[col].astype(str)

for col in ["gs_buy", "niuxiong_buy", "bollinger_cross_lp", "bollinger_warning",
            "top_fractal", "bottom_fractal", "is_SC", "is_BC", "is_ST", "is_spring", "is_SOW"]:
    if col in facts.columns:
        feat[col] = facts[col].astype(bool)

# K-line patterns
for p in pattern_registry():
    col = p["column"]
    if col in facts.columns:
        feat[col] = facts[col].astype(bool)

# Label columns
feat["next_ret"] = next_ret
feat["next_up"] = next_day_up
feat["next_up_2pct"] = next_day_up_2pct
for w in [3, 5, 7]:
    feat[f"fwd_max_{w}d"] = df[f"fwd_max_{w}d"]

valid = feat.dropna(subset=["next_ret", "range_pos"])
print(f"300265 全样本分析: {len(valid)}天")
print(f"次日上涨: {valid['next_up'].sum()}天 ({valid['next_up'].mean()*100:.1f}%)")
print(f"次日涨>2%: {valid['next_up_2pct'].sum()}天 ({valid['next_up_2pct'].mean()*100:.1f}%)")

# ============================================
# Part 1: 次日涨 vs 次日跌 — 特征对比
# ============================================
winners = valid[valid["next_up"]]
losers = valid[~valid["next_up"]]

print(f"\n{'='*70}")
print(f"Part 1: 次日上涨组({len(winners)}天) vs 次日下跌组({len(losers)}天) — 特征差异")
print(f"{'='*70}")

numeric_cols = [c for c in valid.columns if valid[c].dtype in (float, int) and not c.startswith("fwd_") and c != "next_ret"]
# Top differentiating numeric features
diffs = []
for col in numeric_cols:
    w_mean = winners[col].mean()
    l_mean = losers[col].mean()
    gap = abs(w_mean - l_mean)
    # Normalize by pooled std
    pooled = np.sqrt((winners[col].var() + losers[col].var()) / 2)
    if pooled > 0:
        diffs.append((col, w_mean, l_mean, gap, gap/pooled))

diffs.sort(key=lambda x: x[4], reverse=True)
print(f"\n区分力最强的20个数值特征 (按Cohen's d):")
print(f"{'特征':<25} {'次日涨组均值':<14} {'次日跌组均值':<14} {'差值':<10} {'区分力':<8}")
print("-" * 72)
for col, wm, lm, gap, d in diffs[:20]:
    print(f"{col:<25} {wm:<14.3f} {lm:<14.3f} {gap:<10.3f} {d:.2f}")

# Bool features
bool_cols = [c for c in valid.columns if valid[c].dtype == bool]
print(f"\n布尔特征 — 次日涨组触发率 vs 次日跌组触发率:")
bool_diffs = []
for col in bool_cols:
    w_rate = winners[col].mean()
    l_rate = losers[col].mean()
    gap = w_rate - l_rate
    if abs(gap) > 0.02:
        bool_diffs.append((col, w_rate, l_rate, gap))
bool_diffs.sort(key=lambda x: abs(x[3]), reverse=True)
for col, wr, lr, gap in bool_diffs[:15]:
    print(f"  {col:<30} 涨组{wr:.1%}  跌组{lr:.1%}  差{gap:+.1%}")

# Categorical features
cat_cols = [c for c in valid.columns if valid[c].dtype == object and c != "next_up"]
print(f"\n分类特征 — 次日涨组分布 vs 次日跌组分布:")
for col in cat_cols[:6]:
    if col.startswith("fwd_"): continue
    print(f"\n  [{col}]")
    w_dist = winners[col].value_counts(normalize=True)
    l_dist = losers[col].value_counts(normalize=True)
    all_vals = set(w_dist.index) | set(l_dist.index)
    for v in sorted(all_vals, key=lambda x: str(x)):
        wp = w_dist.get(v, 0) * 100
        lp = l_dist.get(v, 0) * 100
        mark = " <<<" if abs(wp - lp) > 5 else ""
        print(f"    {str(v):<20} 涨组{wp:5.1f}%  跌组{lp:5.1f}%  差{wp-lp:+4.1f}%{mark}")

# ============================================
# Part 2: 次日涨组 → 后续走势分化
# ============================================
print(f"\n{'='*70}")
print(f"Part 2: 次日上涨后 → 后续是继续涨还是反转下跌？")
print(f"{'='*70}")

# Within winners, who continues up vs reverses?
winners_df = winners.copy()
winners_df["continue_3d"] = winners_df["fwd_max_3d"] > 0.02  # 3日内继续涨>2%
winners_df["continue_5d"] = winners_df["fwd_max_5d"] > 0.03
winners_df["continue_7d"] = winners_df["fwd_max_7d"] > 0.05

for label, mask in [("3日续涨>2%", "continue_3d"), ("5日续涨>3%", "continue_5d"), ("7日续涨>5%", "continue_7d")]:
    sub = winners_df.dropna(subset=[mask])
    cont = sub[sub[mask]]
    rev = sub[~sub[mask]]
    print(f"\n[{label}] 续涨{len(cont)}天({len(cont)/len(sub)*100:.1f}%) vs 反转{len(rev)}天({len(rev)/len(sub)*100:.1f}%)")
    # What separates continuers from reversers?
    print(f"  区分特征:")
    for col, wm, lm, gap, d in diffs[:10]:
        if col in cont.columns and col in rev.columns:
            c_val = cont[col].mean()
            r_val = rev[col].mean()
            if abs(c_val - r_val) > 0.001:
                print(f"    {col:<25} 续涨{c_val:.3f}  反转{r_val:.3f}")

# ============================================
# Part 3: 次日跌组 → 后续走势分化
# ============================================
print(f"\n{'='*70}")
print(f"Part 3: 次日下跌后 → 是继续跌还是反弹？")
print(f"{'='*70}")

losers_df = losers.copy()
losers_df["bounce_3d"] = losers_df["fwd_max_3d"] > 0.02
losers_df["bounce_5d"] = losers_df["fwd_max_5d"] > 0.03
losers_df["bounce_7d"] = losers_df["fwd_max_7d"] > 0.05

for label, mask in [("3日反弹>2%", "bounce_3d"), ("5日反弹>3%", "bounce_5d"), ("7日反弹>5%", "bounce_7d")]:
    sub = losers_df.dropna(subset=[mask])
    if mask not in sub.columns:
        continue
    bounce = sub[sub[mask]]
    sink = sub[~sub[mask]]
    print(f"\n[{label}] 反弹{len(bounce)}天({len(bounce)/len(sub)*100:.1f}%) vs 续跌{len(sink)}天({len(sink)/len(sub)*100:.1f}%)")
    print(f"  区分特征:")
    for col, wm, lm, gap, d in diffs[:10]:
        if col in bounce.columns and col in sink.columns:
            b_val = bounce[col].mean()
            s_val = sink[col].mean()
            if abs(b_val - s_val) > 0.001:
                print(f"    {col:<25} 反弹{b_val:.3f}  续跌{s_val:.3f}")

# ============================================
# Part 4: 高胜率子集的共同特征
# ============================================
print(f"\n{'='*70}")
print(f"Part 4: 什么条件下次日涨的概率最高？")
print(f"{'='*70}")

# Find subsets with highest next-day-up rate
# Test threshold-based filters on top differentiating features
top_features = [c for c, _, _, _, _ in diffs[:8]]

for col in top_features:
    if col not in valid.columns: continue
    series = valid[col]
    if series.dtype != bool:
        for pct in [20, 30, 40, 60, 70, 80]:
            threshold = series.quantile(pct / 100)
            mask = series > threshold
            sub = valid[mask]
            if len(sub) < 10: continue
            wr = sub["next_up"].mean()
            wr_2pct = sub["next_up_2pct"].mean()
            fwd7 = sub["fwd_max_7d"].mean()
            if wr > 0.55 or wr < 0.42:
                print(f"  {col} > P{pct}({threshold:.3f}): {len(sub)}天, 次日涨{wr:.1%}, 次日涨>2%:{wr_2pct:.1%}, 7日涨幅均值{fwd7*100:.1f}%")
    else:
        sub = valid[series]
        if len(sub) < 10: continue
        wr = sub["next_up"].mean()
        wr_2pct = sub["next_up_2pct"].mean()
        fwd7 = sub["fwd_max_7d"].mean()
        if wr > 0.55 or wr < 0.42:
            print(f"  {col}=True: {len(sub)}天, 次日涨{wr:.1%}, 次日涨>2%:{wr_2pct:.1%}, 7日涨幅均值{fwd7*100:.1f}%")

# Combined: top-2 features intersection
print(f"\n组合条件:")
for c1 in top_features[:4]:
    for c2 in top_features[4:8]:
        if c1 == c2 or c1 not in valid.columns or c2 not in valid.columns: continue
        s1, s2 = valid[c1], valid[c2]
        if s1.dtype == bool and s2.dtype == bool:
            mask = s1 & s2
        elif s1.dtype == bool:
            mask = s1 & (s2 > s2.median())
        elif s2.dtype == bool:
            mask = (s1 > s1.median()) & s2
        else:
            mask = (s1 > s1.median()) & (s2 > s2.median())
        sub = valid[mask]
        if len(sub) < 15: continue
        wr = sub["next_up"].mean()
        wr_2pct = sub["next_up_2pct"].mean()
        fwd7 = sub["fwd_max_7d"].mean()
        if wr > 0.54:
            print(f"  {c1} + {c2}: {len(sub)}天, 次日涨{wr:.1%}, 次日涨>2%:{wr_2pct:.1%}, 7日涨幅均值{fwd7*100:.1f}%")
