"""
留一股票交叉验证：测试XGBoost泛化能力
对每只股票：用其余股票训练→该股票回测→统计胜率
"""
import io, sys, numpy as np, pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.buy_point.buy_point_service import BuyPointService
from tradingagents.buy_point.chain_backtest import run_backtest_alldays, BacktestConfig
from tradingagents.buy_point.ml_trainer import train

MODEL_PATH = Path(__file__).parent / "tradingagents" / "buy_point" / "buypoint_model_v4.json"

SYMBOLS = [
    "300265.SZ", "300750.SZ", "300059.SZ", "300274.SZ", "300502.SZ",
    "300394.SZ", "300024.SZ", "300014.SZ", "300433.SZ",
    "600498.SH", "600519.SH", "600118.SH",
    "600760.SH", "603501.SH", "603986.SH", "603259.SH", "603019.SH",
]

config = BacktestConfig(stop_loss_pct=-5, take_profit_pct=3, max_hold_days=7, atr_multiplier=1.0)

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

all_results = []

for test_sym in SYMBOLS:
    train_syms = [s for s in SYMBOLS if s != test_sym]
    print(f"\n{'='*60}")
    print(f"留一验证: 测试={test_sym}  训练={len(train_syms)}只")

    # 训练
    try:
        model, metrics = train(
            train_syms, label_window=5, atr_multiplier=1.5,
            n_estimators=200, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, reg_alpha=0.5, reg_lambda=1.0,
        )
    except Exception as e:
        print(f"  训练失败: {e}")
        continue

    # 获取测试股数据
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
    raw = route_to_vendor("get_stock_data", symbol=test_sym, start_date=start, end_date=end)
    df = pd.read_csv(io.StringIO(raw), comment="#")
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    if is_long_bear(df):
        print(f"  {test_sym}: 长期空头，跳过")
        continue

    svc = BuyPointService.from_raw_kline(df, symbol=test_sym, skip_merge=True)
    facts = svc.facts

    # 回测多个阈值
    best_wr = 0
    best_trades = 0
    best_t = None
    for t in [0.4, 0.5, 0.55, 0.6, 0.65]:
        model.save(MODEL_PATH)
        trades, stats = run_backtest_alldays(facts, model_path=str(MODEL_PATH), threshold=t, config=config)
        if trades:
            wr = stats['win_rate']
            if stats['total_trades'] > 0:
                print(f"  th={t:.2f}: {stats['total_trades']:3d}笔 胜率{wr:5.1f}% 均收益{stats['avg_return_pct']:+5.1f}%")
                if wr > best_wr or (wr == best_wr and stats['total_trades'] > best_trades):
                    best_wr = wr
                    best_t = t
                    best_trades = stats['total_trades']

    all_results.append({
        "test_sym": test_sym,
        "train_stocks": len(train_syms),
        "best_t": best_t,
        "trades": best_trades,
        "wr": best_wr,
    })
    if best_t is not None:
        print(f"  => 最优: th={best_t:.2f} {best_trades}笔 WR={best_wr:.1f}%")

# 汇总
print(f"\n{'='*60}")
print("留一股票交叉验证汇总:")
print(f"{'股票':12s} {'训练数':>5s} {'阈值':>5s} {'交易数':>5s} {'胜率':>6s}")
all_wr = []
all_trades = []
total_wins = 0
total_losses = 0
for r in all_results:
    bw = f"{r['wr']:.1f}%" if r['wr'] else "N/A"
    bt = f"{r['best_t']:.2f}" if r['best_t'] is not None else "N/A"
    print(f"  {r['test_sym']:12s} {r['train_stocks']:5d} {bt:>5s} {r['trades']:5d} {bw:>6s}")
    if r['wr']:
        all_wr.append(r['wr'])
        all_trades.append(r['trades'])
        total_wins += int(r['trades'] * r['wr'] / 100)
        total_losses += r['trades'] - int(r['trades'] * r['wr'] / 100)

avg_wr = np.mean(all_wr) if all_wr else 0
print(f"\n平均胜率: {avg_wr:.1f}%   总交易: {sum(all_trades)}笔   总胜/负: {total_wins}/{total_losses}")
print(f"整体胜率: {total_wins/(total_wins+total_losses)*100:.1f}%" if total_wins+total_losses else "")
