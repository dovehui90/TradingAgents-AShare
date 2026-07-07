"""时间分割回测：训练截止3个月前，回测仅统计最近3个月交易"""
import io, sys, numpy as np, pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.buy_point.buy_point_service import BuyPointService
from tradingagents.buy_point.chain_backtest import run_backtest_alldays, BacktestConfig, run_baseline
from tradingagents.buy_point.ml_predictor import BuyPointPredictor

MODEL_PATH = Path(__file__).parent / "tradingagents" / "buy_point" / "buypoint_model_v4.json"
CUTOFF = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
config = BacktestConfig(stop_loss_pct=-5, take_profit_pct=3, max_hold_days=7, atr_multiplier=1.0)

ALL_TEST = [
    "300265.SZ", "300750.SZ", "300059.SZ", "300274.SZ", "300502.SZ",
    "300394.SZ", "300024.SZ", "300014.SZ", "300433.SZ",
    "600498.SH", "600519.SH", "600118.SH",
    "600760.SH", "603501.SH", "603986.SH", "603259.SH", "603019.SH",
    # 半导体+先进封装（新增训练标的）
    "688981.SH", "002371.SZ", "600584.SH", "002156.SZ", "002185.SZ",
    "600703.SH", "300661.SZ", "688008.SH", "002049.SZ", "688012.SH",
    # 样本外
    "600869.SH", "300476.SZ", "300124.SZ", "300316.SZ", "688111.SH", "600406.SH",
]
TRAIN_SYMS = set(ALL_TEST[:27])

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
    """只保留cutoff之后的交易并重算统计"""
    cutoff = pd.Timestamp(cutoff_str)
    filtered = [t for t in trades if pd.Timestamp(t.entry_date) >= cutoff]
    if not filtered:
        return [], {"total_trades": 0, "win_rate": 0, "total_return_pct": 0, "avg_return_pct": 0}
    wins = [t for t in filtered if t.return_pct > 0]
    wr = len(wins) / len(filtered) * 100
    total_ret = sum(t.return_pct for t in filtered)
    avg_ret = total_ret / len(filtered)
    stats = {"total_trades": len(filtered), "win_rate": wr,
             "total_return_pct": total_ret, "avg_return_pct": avg_ret}
    return filtered, stats

predictor = BuyPointPredictor(MODEL_PATH)
print(f"模型特征数: {len(predictor.model.features)}")
print(f"训练截止: {CUTOFF}，仅统计 {CUTOFF} 之后的交易\n")

all_results = []
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
    facts = svc.facts  # 全时间段，保证滚动窗口有足够历史

    # 基线
    raw_trades, base = run_baseline(facts, config)
    _, base_recent = filter_trades(raw_trades, CUTOFF)

    # ML
    best_wr, best_t, best_trades, best_total, best_avg = 0, None, 0, 0, 0
    for th in [0.4, 0.5, 0.55, 0.6, 0.65]:
        raw_trades, _ = run_backtest_alldays(facts, model_path=str(MODEL_PATH), threshold=th, config=config)
        _, s = filter_trades(raw_trades, CUTOFF)
        if s['total_trades'] > 0:
            flag = "!!" if s['win_rate'] < 60 else "! " if s['win_rate'] < 70 else "  "
            print(f"  {sym} th={th:.2f}: {s['total_trades']:2d}笔 WR={s['win_rate']:5.1f}% 收益{s['total_return_pct']:+5.1f}% {flag}")
            if s['win_rate'] >= best_wr or (s['win_rate'] == best_wr and s['total_trades'] > best_trades):
                best_wr, best_t, best_trades, best_total, best_avg = s['win_rate'], th, s['total_trades'], s['total_return_pct'], s['avg_return_pct']

    tag = "内" if sym in TRAIN_SYMS else "外"
    all_results.append({"sym": sym, "tag": tag, "base_wr": base_recent['win_rate'],
                        "base_trades": base_recent['total_trades'],
                        "ml_wr": best_wr, "ml_trades": best_trades, "ml_total": best_total})
    if best_t is not None:
        print(f"  => [{tag}] 基线WR={base_recent['win_rate']:.0f}%({base_recent['total_trades']}笔) ML最佳WR={best_wr:.0f}%({best_trades}笔)\n")
    else:
        print(f"  => [{tag}] 无信号\n")

# 汇总
print(f"\n{'='*60}")
print(f"时间分割回测汇总 (近3个月, cutoff={CUTOFF})")
print(f"{'类型':4s} {'股票':12s} {'基线WR':>6s} {'基线笔':>5s} {'ML WR':>6s} {'ML笔':>5s}")
in_wins, in_total = 0, 0
out_wins, out_total = 0, 0
for r in all_results:
    bw = f"{r['base_wr']:.0f}%" if r['base_wr'] else "N/A"
    mw = f"{r['ml_wr']:.0f}%" if r['ml_wr'] else "N/A"
    print(f"  [{r['tag']}] {r['sym']:12s} {bw:>6s} {r['base_trades']:4d}  {mw:>6s} {r['ml_trades']:4d}")
    if r['ml_wr'] and r['ml_trades'] >= 3:
        wins = int(r['ml_trades'] * r['ml_wr'] / 100)
        if r['tag'] == "内":
            in_wins += wins; in_total += r['ml_trades']
        else:
            out_wins += wins; out_total += r['ml_trades']

if in_total:
    print(f"\n样本内加权WR: {in_wins/in_total*100:.1f}% ({in_wins}W/{in_total}T)")
if out_total:
    print(f"样本外加权WR: {out_wins/out_total*100:.1f}% ({out_wins}W/{out_total}T)")
