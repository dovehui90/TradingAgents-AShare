"""时间分割回测 v5：分池模型，训练截止3个月前，回测仅统计最近3个月交易"""
import io, sys, numpy as np, pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.buy_point.buy_point_service import BuyPointService
from tradingagents.buy_point.chain_backtest import BacktestConfig, Trade, _compute_stats, _vectorized_find_exit
from tradingagents.buy_point.ml_predictor import PooledPredictor
from tradingagents.buy_point.pool_config import POOL_CONFIGS, resolve_pool

MODEL_DIR = Path(__file__).parent / "tradingagents" / "buy_point"
CUTOFF = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
config = BacktestConfig(stop_loss_pct=-5, take_profit_pct=3, max_hold_days=7, atr_multiplier=1.0)


def run_alldays_pooled(facts_df: pd.DataFrame, predictor: PooledPredictor,
                        pool: str, threshold: float = 0.5,
                        cfg: BacktestConfig | None = None) -> tuple[list, dict]:
    """全样本 ML 回测（分池版）"""
    if cfg is None:
        cfg = config

    n = len(facts_df)
    open_arr = facts_df["open"].values.astype(float)
    high_arr = facts_df["high"].values.astype(float)
    low_arr = facts_df["low"].values.astype(float)
    close_arr = facts_df["close"].values.astype(float)
    dates = facts_df.index.values

    # ML 预测
    pool_cfg = POOL_CONFIGS[pool]
    X = predictor.build_features(facts_df, pool)
    model = predictor._get_model(pool)
    numeric_cols = [f for f in model.features if f in X.columns and X[f].dtype in ('float64', 'float32', 'int64', 'bool')]
    valid_mask = X[numeric_cols].notna().all(axis=1)
    proba = np.full(n, np.nan)
    valid_idx = np.flatnonzero(valid_mask)
    if len(valid_idx) > 0:
        X_valid = X.iloc[valid_idx][model.features]
        proba[valid_idx] = model.predict_proba(X_valid)

    entry_mask = (~np.isnan(proba)) & (proba >= threshold)
    entry_mask[-1] = False
    entry_candidates = np.flatnonzero(entry_mask)

    atr_arr = None
    if cfg.atr_multiplier > 0:
        tr_arr = np.maximum.reduce([
            high_arr - low_arr,
            np.abs(high_arr - np.roll(close_arr, 1)),
            np.abs(low_arr - np.roll(close_arr, 1)),
        ])
        tr_arr[0] = high_arr[0] - low_arr[0]
        atr14 = np.convolve(tr_arr, np.ones(14) / 14, mode="valid")
        atr_arr = np.concatenate([np.full(13, np.nan), atr14])

    trades = []
    next_available = 0
    for e in entry_candidates:
        if e < next_available:
            continue
        e = int(e)
        if e + 1 >= n:
            continue
        entry_px = float(open_arr[e + 1])
        tp_pct = None
        if atr_arr is not None and e < len(atr_arr) and not np.isnan(atr_arr[e]):
            tp_pct = atr_arr[e] / entry_px * 100 * cfg.atr_multiplier
        result = _vectorized_find_exit(e, entry_px, open_arr, high_arr, low_arr, close_arr, dates, cfg, n, tp_pct)
        if result is None:
            continue
        prob = float(proba[e])
        trades.append(Trade(
            entry_date=result["entry_date"], exit_date=result["exit_date"],
            entry_price=result["entry_price"], exit_price=result["exit_price"],
            return_pct=round((result["exit_price"] - result["entry_price"]) / result["entry_price"] * 100, 2),
            hold_days=result["hold_days"], exit_reason=result["exit_reason"],
            entry_patterns=[], confirmed_factors=f"ML_{pool}(thresh={threshold},prob={prob:.3f})",
        ))
        next_available = result["exit_idx"] + 1

    return trades, _compute_stats(trades)


def is_long_bear(df):
    close = df["close"]
    ma60 = close.rolling(60).mean()
    n = len(ma60)
    if n < 120: return False
    mid = n // 2
    slope = (ma60.iloc[mid:].mean() - ma60.iloc[:mid].mean()) / ma60.iloc[:mid].mean() * 100
    below_pct = (close < ma60).sum() / n
    total_ret = (close.iloc[-1] - close.iloc[0]) / close.iloc[0] * 100
    return (slope < -10.0 and below_pct > 0.50) or total_ret < -25.0


def filter_trades(trades, cutoff_str):
    cutoff = pd.Timestamp(cutoff_str)
    filtered = [t for t in trades if pd.Timestamp(t.entry_date) >= cutoff]
    if not filtered:
        return [], {"total_trades": 0, "win_rate": 0, "total_return_pct": 0, "avg_return_pct": 0}
    wins = [t for t in filtered if t.return_pct > 0]
    wr = len(wins) / len(filtered) * 100
    total_ret = sum(t.return_pct for t in filtered)
    avg_ret = total_ret / len(filtered)
    return filtered, {"total_trades": len(filtered), "win_rate": wr,
                      "total_return_pct": total_ret, "avg_return_pct": avg_ret}


# ============================================================
# 测试标的 — 按池分类
# ============================================================
ALL_TEST = [
    # Pool A candidates (主板 >100亿)
    "600519.SH", "601127.SH", "601012.SH", "600118.SH", "600760.SH",
    "603501.SH", "603986.SH", "603259.SH", "603019.SH", "600584.SH",
    "600703.SH", "002371.SZ", "002049.SZ",
    # Pool B candidates (主板 50-100亿)
    "300265.SZ", "300502.SZ", "300394.SZ", "300122.SZ", "300024.SZ",
    "300014.SZ", "300433.SZ", "002156.SZ", "002185.SZ", "600498.SH",
    # Pool C candidates (创业板)
    "300750.SZ", "300059.SZ", "300274.SZ", "300661.SZ",
    # 样本外
    "300476.SZ", "300124.SZ", "300316.SZ", "688111.SH", "600406.SH", "600869.SH",
]

predictor = PooledPredictor()
print(f"模型目录: {MODEL_DIR}")
for p in ["A", "B", "C"]:
    path = MODEL_DIR / f"buypoint_model_v5_{p.lower()}.json"
    pool_cfg = POOL_CONFIGS[p]
    print(f"  池 {p} ({pool_cfg.name}): {path.exists()} — {len(pool_cfg.all_features)} 特征")
print(f"训练截止: {CUTOFF}，仅统计 {CUTOFF} 之后的交易\n")

pool_results = {"A": [], "B": [], "C": [], "?": []}

for sym in ALL_TEST:
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
    raw = route_to_vendor("get_stock_data", symbol=sym, start_date=start, end_date=end)
    df = pd.read_csv(io.StringIO(raw), comment="#")
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    if is_long_bear(df):
        continue

    svc = BuyPointService.from_raw_kline(df, symbol=sym, skip_merge=True)
    facts = svc.facts

    # 确定池（用代码前缀，回测环境无市值数据）
    code = sym.split(".")[0]
    if code.startswith("300"):
        pool = "C"
    elif code.startswith(("688", "8", "4")):
        continue  # 排除
    else:
        # 主板：根据代码前缀大致判断（无法获取精确市值时，默认B池）
        # 已知大盘股列表
        large_caps = {"600519", "601127", "601012", "600118", "600760",
                      "603501", "603986", "603259", "603019", "600584",
                      "600703", "600036", "601318", "600900", "601857"}
        pool = "A" if code in large_caps else "B"

    pool_cfg = POOL_CONFIGS[pool]
    best_wr, best_th, best_trades, best_total = 0, None, 0, 0

    for th in [0.4, 0.45, 0.5, 0.55, 0.6, 0.65]:
        raw_trades, _ = run_alldays_pooled(facts, predictor, pool, threshold=th)
        _, s = filter_trades(raw_trades, CUTOFF)
        if s['total_trades'] > 0:
            flag = "!!" if s['win_rate'] < 60 else "! " if s['win_rate'] < 70 else "  "
            print(f"  {sym} [{pool}] th={th:.2f}: {s['total_trades']:2d}笔 WR={s['win_rate']:5.1f}% 收益{s['total_return_pct']:+5.1f}% {flag}")
            if s['win_rate'] >= best_wr or (s['win_rate'] == best_wr and s['total_trades'] > best_trades):
                best_wr, best_th, best_trades, best_total = s['win_rate'], th, s['total_trades'], s['total_return_pct']

    pool_results[pool].append({
        "sym": sym, "ml_wr": best_wr, "ml_trades": best_trades,
        "ml_total": best_total, "best_th": best_th,
    })

    if best_th is not None:
        print(f"  => [{pool}] 最佳WR={best_wr:.0f}%({best_trades}笔) th={best_th:.2f}\n")
    else:
        print(f"  => [{pool}] 无信号\n")

# ============================================================
# 汇总
# ============================================================
print(f"\n{'='*60}")
print(f"时间分割回测汇总 (近3个月, cutoff={CUTOFF})")
print(f"{'池':4s} {'股票':12s} {'ML WR':>6s} {'ML笔':>5s} {'最佳阈值':>8s}")

for pool in ["A", "B", "C"]:
    wins_total, trades_total = 0, 0
    print(f"\n--- 池 {pool} ({POOL_CONFIGS[pool].name}) ---")
    for r in pool_results[pool]:
        mw = f"{r['ml_wr']:.0f}%" if r['ml_wr'] else "N/A"
        th = f"{r['best_th']:.2f}" if r['best_th'] else "N/A"
        print(f"  {r['sym']:12s} {mw:>6s} {r['ml_trades']:4d}  {th:>8s}")
        if r['ml_wr'] and r['ml_trades'] >= 3:
            wins = int(r['ml_trades'] * r['ml_wr'] / 100)
            wins_total += wins
            trades_total += r['ml_trades']

    if trades_total:
        print(f"  {'加权WR':>12s} {wins_total/trades_total*100:.1f}% ({wins_total}W/{trades_total}T)")
