"""验证600498是否与300265有一致的特征规律"""
import io, pandas as pd, numpy as np
from datetime import datetime, timedelta
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.buy_point.buy_point_service import BuyPointService
from tradingagents.indicators.candlestick_patterns import pattern_registry

for sym in ['600498.SH', '000001.SZ']:
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

    next_ret = close.shift(-1) / close - 1
    fwd_high_7 = high.rolling(7).max().shift(-7)
    fwd_ret_7 = fwd_high_7 / close - 1

    svc = BuyPointService.from_raw_kline(df, symbol=sym)
    facts = svc.facts

    feat = pd.DataFrame(index=facts.index)
    feat["range_pos"] = (close - close.rolling(60).min()) / (close.rolling(60).max() - close.rolling(60).min()) * 100
    feat["bollinger_position"] = pd.to_numeric(facts["bollinger_position"], errors="coerce")
    feat["gs_bias"] = pd.to_numeric(facts["gs_bias"], errors="coerce")
    feat["consecutive_yin"] = pd.to_numeric(facts["consecutive_yin"], errors="coerce")
    feat["consecutive_yang"] = pd.to_numeric(facts["consecutive_yang"], errors="coerce")
    feat["ret_10d"] = close / close.shift(10) - 1
    feat["vol_ratio"] = volume / volume.rolling(20).mean()
    feat["next_up"] = next_ret > 0
    feat["fwd_7d_gt5"] = fwd_ret_7 > 0.05
    feat["fwd_7d_gt8"] = fwd_ret_7 > 0.08
    feat["fwd_7d_gt10"] = fwd_ret_7 > 0.10

    v = feat.dropna(subset=["range_pos", "next_up", "fwd_7d_gt5"])
    print(f"\n{sym} 验证 ({len(v)}天)")
    print(f"  次日涨率: {v['next_up'].mean()*100:.1f}%")
    print(f"  7日>5%: {v['fwd_7d_gt5'].mean()*100:.1f}%")
    print(f"  7日>8%: {v['fwd_7d_gt8'].mean()*100:.1f}%")
    print(f"  7日>10%: {v['fwd_7d_gt10'].mean()*100:.1f}%")

    # Test 300265's key finding: 连阴>=1 → next day up rate
    yin_mask = v["consecutive_yin"] >= 1
    strong_mask = v["range_pos"] >= 50
    combo = yin_mask & strong_mask

    for label, mask in [("全样本", slice(None)), ("连阴>=1", yin_mask),
                         ("强势区(>50%)", strong_mask), ("连阴>=1+强势", combo)]:
        sub = v[mask]
        print(f"  {label:<20}: {len(sub):>4}天, 次日涨{sub['next_up'].mean()*100:.1f}%, "
              f"7日>5%:{sub['fwd_7d_gt5'].mean()*100:.1f}%, "
              f"7日>8%:{sub['fwd_7d_gt8'].mean()*100:.1f}%, "
              f"7日>10%:{sub['fwd_7d_gt10'].mean()*100:.1f}%")
