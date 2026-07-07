import io, pandas as pd, numpy as np
from datetime import datetime, timedelta
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.buy_point.buy_point_service import BuyPointService
from tradingagents.buy_point.chain_backtest import run_baseline, run_backtest_ml, BacktestConfig

for sym in ["300265.SZ", "600498.SH"]:
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
    raw = route_to_vendor("get_stock_data", symbol=sym, start_date=start, end_date=end)
    df = pd.read_csv(io.StringIO(raw), comment="#")
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    svc = BuyPointService.from_raw_kline(df, symbol=sym)
    facts = svc.facts
    signals = (facts["niuxiong_direction"] == "多头") & (facts["gs_buy"].astype(bool))

    print(f"\n{'='*60}")
    print(f"{sym} 回测对比 (信号链={signals.sum()}天)")
    print(f"{'='*60}")

    # Baseline
    config = BacktestConfig(stop_loss_pct=-5, take_profit_pct=15, max_hold_days=20)
    base_trades, base_stats = run_baseline(facts, config)
    print(f"基线(纯信号链): {base_stats['total_trades']}笔, 胜率{base_stats['win_rate']}%, "
          f"均收益{base_stats['avg_return_pct']}%, 盈亏比{base_stats['profit_factor']}, "
          f"总收益{base_stats['total_return_pct']}%")

    # ML at various thresholds
    for t in [0.3, 0.4, 0.5, 0.6]:
        ml_trades, ml_stats = run_backtest_ml(facts, threshold=t, config=config)
        print(f"ML(th={t:.1f}):      {ml_stats['total_trades']}笔, 胜率{ml_stats['win_rate']}%, "
              f"均收益{ml_stats['avg_return_pct']}%, 盈亏比{ml_stats['profit_factor']}, "
              f"总收益{ml_stats['total_return_pct']}%")
