"""
预缓存三大市场指数日K线，用于计算大盘相对强度特征

Usage: python tools/build_market_cache.py
"""
import sys, logging, io
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from tradingagents.dataflows.interface import route_to_vendor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("build_market_cache")

CACHE_DIR = Path(__file__).parent.parent / "data" / "market_cache"

# 三大市场指数
INDICES = {
    "000001.SH": "上证综指",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
}


def fetch_index(symbol: str) -> pd.DataFrame | None:
    """获取指数日K线"""
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=1825)).strftime("%Y-%m-%d")  # 5 years

    try:
        raw = route_to_vendor("get_stock_data", symbol=symbol, start_date=start, end_date=end)
        df = pd.read_csv(io.StringIO(raw), comment="#")
        if df.empty:
            return None

        df.columns = [c.lower().replace(" ", "_") for c in df.columns]
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        return df[["open", "high", "low", "close", "volume"]]
    except Exception as e:
        logger.warning(f"{symbol}: 获取失败 — {e}")
        return None


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for symbol, name in INDICES.items():
        cache_path = CACHE_DIR / f"{symbol}.parquet"
        if cache_path.exists():
            df = pd.read_parquet(cache_path)
            logger.info(f"{symbol}({name}): 已缓存 {len(df)} 条")
            continue

        logger.info(f"下载 {symbol}({name}) ...")
        df = fetch_index(symbol)
        if df is not None and not df.empty:
            df.to_parquet(cache_path)
            logger.info(f"  ✓ {len(df)} 条，{df.index[0].date()} ~ {df.index[-1].date()}")


if __name__ == "__main__":
    main()
