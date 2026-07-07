import io, pandas as pd, numpy as np
from datetime import datetime, timedelta
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.buy_point.buy_point_service import BuyPointService
from tradingagents.buy_point.ml_predictor import BuyPointPredictor

for sym in ["300265.SZ", "600498.SH"]:
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
    raw = route_to_vendor("get_stock_data", symbol=sym, start_date=start, end_date=end)
    df = pd.read_csv(io.StringIO(raw), comment="#")
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    svc = BuyPointService.from_raw_kline(df, symbol=sym)
    facts = svc.facts

    predictor = BuyPointPredictor()
    result = predictor.predict_latest(facts)

    print(f"\n{sym} 最新交易日 ML 评分:")
    if result:
        print(f"  日期: {result['date']}")
        print(f"  买入概率: {result['probability']:.4f}  {'>>> 买入 <<<' if result['signal']==1 else ''}")
        print(f"  正向贡献:")
        for c in result["top_positive"][:3]:
            print(f"    + {c['feature']}: {c['contribution']:+.4f}")
        print(f"  负向贡献:")
        for c in result["top_negative"][:3]:
            print(f"    - {c['feature']}: {c['contribution']:+.4f}")
    else:
        print("  数据不足")
