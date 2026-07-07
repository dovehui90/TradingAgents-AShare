"""分析失败买点 — 找出亏损共性原因"""
import io, sys, pandas as pd, numpy as np
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.buy_point.buy_point_service import BuyPointService
from tradingagents.buy_point.chain_backtest import run_backtest_alldays, BacktestConfig
from tradingagents.buy_point.ml_predictor import BuyPointPredictor
from tradingagents.buy_point.ml_trainer import NUMERIC_FEATURES, BOOL_FEATURES

MODEL_PATH = Path(__file__).parent / "tradingagents" / "buy_point" / "buypoint_model_v4.json"

SYMBOLS = [
    "300265.SZ", "300750.SZ", "300059.SZ", "300274.SZ", "300502.SZ",
    "300394.SZ", "300024.SZ", "300014.SZ", "300433.SZ",
    "600498.SH", "600519.SH", "600118.SH",
    "600760.SH", "603501.SH", "603986.SH", "603259.SH", "603019.SH",
]

def is_long_bear(raw_df):
    close = raw_df["close"]
    ma60 = close.rolling(60).mean()
    n = len(ma60)
    if n < 120:
        return False
    mid = n // 2
    slope = (ma60.iloc[mid:].mean() - ma60.iloc[:mid].mean()) / ma60.iloc[:mid].mean() * 100
    below_pct = (close < ma60).sum() / n
    total_ret = (close.iloc[-1] - close.iloc[0]) / close.iloc[0] * 100
    return (slope < -10.0 and below_pct > 0.50) or total_ret < -25.0

config = BacktestConfig(stop_loss_pct=-5, take_profit_pct=3, max_hold_days=7, atr_multiplier=1.0)
predictor = BuyPointPredictor(MODEL_PATH)

all_losing = []
all_winning = []

for sym in SYMBOLS:
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
    raw = route_to_vendor("get_stock_data", symbol=sym, start_date=start, end_date=end)
    df = pd.read_csv(io.StringIO(raw), comment="#")
    if df.empty:
        continue
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    if is_long_bear(df):
        continue

    svc = BuyPointService.from_raw_kline(df, symbol=sym, skip_merge=True)
    facts = svc.facts

    # 跑最优阈值附近的回测，收集盈亏明细
    for th in [0.4, 0.5, 0.6]:
        trades, stats = run_backtest_alldays(facts, model_path=str(MODEL_PATH), threshold=th, config=config)
        for t in trades:
            rec = {"symbol": sym, "threshold": th, "entry_date": t.entry_date,
                   "return_pct": t.return_pct, "hold_days": t.hold_days,
                   "exit_reason": t.exit_reason}
            if t.return_pct <= 0:
                all_losing.append(rec)
            else:
                all_winning.append(rec)

    # 合并ML特征
    try:
        X = predictor.build_features(facts, symbol=sym)
        valid = X[NUMERIC_FEATURES].notna().all(axis=1)
        Xv = X[valid].copy()
        proba = predictor.model.predict_proba(Xv[predictor.model.features])
        Xv["proba"] = proba
        idx_map = {str(i)[:10]: Xv.loc[i] for i in Xv.index}

        # 填入特征
        for lst in [all_losing, all_winning]:
            for rec in lst:
                if rec["symbol"] == sym and rec["entry_date"] in idx_map:
                    row = idx_map[rec["entry_date"]]
                    rec["proba"] = float(row["proba"])
    except Exception:
        pass

# ====== 分析 ======
print("=" * 60)
print(f"全市场: {len(all_winning)}胜 / {len(all_losing)}负")
print(f"胜率: {len(all_winning)/(len(all_winning)+len(all_losing))*100:.1f}%")

lose_df = pd.DataFrame(all_losing).sort_values("return_pct")

# 1. 离场原因
print("\n--- 失败离场原因 ---")
for reason in lose_df["exit_reason"].unique():
    sub = lose_df[lose_df["exit_reason"] == reason]
    print(f"  {reason}: {len(sub)}笔 ({len(sub)/len(lose_df)*100:.0f}%), 均亏{sub['return_pct'].mean():.1f}%")

# 2. 亏损幅度分布
print("\n--- 亏损幅度分布 ---")
for cut in [(-10,-7), (-7,-5), (-5,-3), (-3,-1), (-1,0)]:
    cnt = lose_df[lose_df["return_pct"].between(*cut)].shape[0]
    bar = "#" * (cnt // 2 + 1)
    print(f"  {cut[0]}~{cut[1]}%: {cnt:3d}笔 {bar}")

# 3. 持仓天数
print("\n--- 失败持仓天数 ---")
day_groups = lose_df.groupby("hold_days")["return_pct"].agg(["count","mean"])
for d, row in day_groups.iterrows():
    print(f"  {d}天: {int(row['count'])}笔, 均亏{row['mean']:.1f}%")

# 4. 高概率失败的股票
print("\n--- 各股票失败 vs 成功 ---")
per_sym = []
for sym in lose_df["symbol"].unique():
    wins = sum(1 for w in all_winning if w["symbol"] == sym)
    fails = sum(1 for w in all_losing if w["symbol"] == sym)
    per_sym.append((sym, wins, fails, wins/(wins+fails)*100 if wins+fails else 0))
per_sym.sort(key=lambda x: x[2]-x[1])  # 失败多的在前
for sym, wins, fails, wr in per_sym[:10]:
    flag = "!!" if wr < 60 else "! " if wr < 65 else "  "
    print(f"  {flag} {sym}: {wins}胜/{fails}负, WR={wr:.0f}%")

# 5. ML概率与失败关系
if "proba" in lose_df.columns:
    valid = lose_df[lose_df["proba"].notna()]
    if len(valid) > 0:
        print(f"\n--- 失败交易的ML概率分布 (n={len(valid)}) ---")
        print(f"  均值: {valid['proba'].mean():.3f}  中位: {valid['proba'].median():.3f}")
        print(f"  最低: {valid['proba'].min():.3f}  最高: {valid['proba'].max():.3f}")
        for lo in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
            hi = lo + 0.1
            cnt = valid[valid["proba"].between(lo, hi)].shape[0]
            if cnt > 0:
                avg = valid[valid["proba"].between(lo, hi)]["return_pct"].mean()
                print(f"  [{lo:.1f}-{hi:.1f}): {cnt:3d}笔, 均亏{avg:.1f}%")

    win_df = pd.DataFrame(all_winning)
    if "proba" in win_df.columns and win_df["proba"].notna().any():
        print(f"\n  对比: 成功交易proba均值={win_df['proba'].dropna().mean():.3f}")

# 6. 典型失败案例
print("\n--- 最惨10笔失败 ---")
for _, row in lose_df.head(10).iterrows():
    proba_str = f" proba={row.get('proba', '?'):.3f}" if pd.notna(row.get('proba')) else ""
    print(f"  {row['symbol']} {row['entry_date']}: {row['return_pct']:.1f}%"
          f" 持有{row['hold_days']}天 {row['exit_reason']}{proba_str}")
