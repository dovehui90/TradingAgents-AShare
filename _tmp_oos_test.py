"""测试模型在训练集外股票的泛化能力"""
import io, sys, numpy as np, pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.buy_point.buy_point_service import BuyPointService
from tradingagents.buy_point.chain_backtest import run_backtest_alldays, BacktestConfig, run_baseline

MODEL_PATH = Path(__file__).parent / "tradingagents" / "buy_point" / "buypoint_model_v4.json"
config = BacktestConfig(stop_loss_pct=-5, take_profit_pct=3, max_hold_days=7, atr_multiplier=1.0)

NEW_SYMBOLS = [
    "600869.SH",  # 远东股份
    "300476.SZ",  # 胜宏科技
    "300124.SZ", "300316.SZ", "600438.SH", "688111.SH", "600406.SH",
]

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

all_ml_wr, all_ml_trades = [], []
all_base_wr, all_base_trades = [], []

for sym in NEW_SYMBOLS:
    try:
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        raw = route_to_vendor("get_stock_data", symbol=sym, start_date=start, end_date=end)
        df = pd.read_csv(io.StringIO(raw), comment="#")
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        if is_long_bear(df):
            print(f"{sym}: skip long bear")
            continue

        svc = BuyPointService.from_raw_kline(df, symbol=sym, skip_merge=True)
        facts = svc.facts
        _, base = run_baseline(facts, config)
        print(f"\n{sym} ({len(facts)}d):")
        print(f"  基线: {base['total_trades']:3d}笔 WR={base['win_rate']:.1f}%")

        best_wr = 0
        for t in [0.4, 0.5, 0.55, 0.6, 0.65]:
            _, s = run_backtest_alldays(facts, model_path=str(MODEL_PATH), threshold=t, config=config)
            if s['total_trades'] > 0:
                wr = s['win_rate']
                flag = "!!" if wr < 60 else "! " if wr < 70 else "  "
                print(f"  {flag} ML th={t:.2f}: {s['total_trades']:3d}笔 WR={wr:.1f}% avg={s['avg_return_pct']:+.1f}%")
                if wr > best_wr:
                    best_wr = wr

        all_ml_wr.append(best_wr)
        all_ml_trades.append(s['total_trades'])
        all_base_wr.append(base['win_rate'])
        all_base_trades.append(base['total_trades'])
    except Exception as e:
        print(f"{sym}: {e}")

if all_ml_wr:
    print(f"\n=== 样本外汇总 ===")
    print(f"基线均胜率: {np.mean(all_base_wr):.1f}%  总交易: {sum(all_base_trades)}")
    print(f"ML 均胜率:  {np.mean(all_ml_wr):.1f}%  总交易: {sum(all_ml_trades)}")
    print(f"(对比训练集内 ML: 83.6% 952笔)")
