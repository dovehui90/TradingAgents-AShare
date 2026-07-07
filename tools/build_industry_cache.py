"""
预构建行业板块K线缓存 — 绕过代理直接请求东财 API

Usage: python tools/build_industry_cache.py
"""
import sys, json, logging, time, os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("build_industry_cache")

CACHE_DIR = Path(__file__).parent.parent / "data" / "industry_cache"
NO_PROXY = {"http": None, "https": None}

# 训练标的列表（与 train_buypoint_v4.py 一致）
SYMBOLS = [
    "300265.SZ", "300750.SZ", "300059.SZ", "300274.SZ", "300502.SZ",
    "300394.SZ", "300024.SZ", "300014.SZ", "300433.SZ", "300122.SZ",
    "600498.SH", "600519.SH", "601127.SH", "601012.SH", "600118.SH",
    "600760.SH", "603501.SH", "603986.SH", "603259.SH", "603019.SH",
    "000001.SZ", "000858.SZ", "000568.SZ", "002594.SZ", "002475.SZ",
    "002230.SZ", "002371.SZ", "002049.SZ", "002241.SZ", "002074.SZ",
]

# 东财个股市场代码映射
MARKET_MAP = {"sh": 1, "sz": 0}


def _normalize_code(symbol: str) -> str:
    return symbol.split(".")[0] if "." in symbol else symbol


def _market(symbol: str) -> str:
    code = _normalize_code(symbol)
    return "sh" if code[:1] in ("5", "6", "9") else "sz"


def _em_request(url: str, params: dict, timeout: int = 15) -> dict | None:
    """绕过代理请求东财 API"""
    try:
        r = requests.get(url, params=params, timeout=timeout, proxies=NO_PROXY)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"  请求失败: {url[:60]} — {e}")
        return None


def get_stock_industry(symbol: str) -> str | None:
    """获取个股所属行业名称（绕过代理）"""
    code = _normalize_code(symbol)
    mkt = _market(symbol)
    secid = f"{MARKET_MAP.get(mkt, 0)}.{code}"

    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f57,f58,f100,f127",
        "ut": "fa5fd1943c7b386f172d6893dbf16ec8",
    }
    data = _em_request(url, params)
    if data and data.get("data"):
        info = data["data"]
        # f100 = industry name in some responses, f127 in others
        industry = info.get("f100", "") or info.get("f127", "")
        if industry and industry != "-":
            return industry
    return None


def get_industry_board_list() -> dict[str, str]:
    """获取行业→板块代码映射（绕过代理）"""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "500",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:90+t:2+f:!50",
        "fields": "f12,f14",
    }
    data = _em_request(url, params)
    if not data or not data.get("data") or not data["data"].get("diff"):
        logger.error("获取行业板块列表失败")
        return {}

    mapping = {}
    for item in data["data"]["diff"]:
        name = item.get("f14", "")
        code = item.get("f12", "")
        if name and code:
            mapping[name] = code
    logger.info(f"行业板块列表: {len(mapping)} 个")
    return mapping


def download_board_kline(board_code: str, board_name: str) -> pd.DataFrame | None:
    """下载板块历史日K线（绕过代理）"""
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": f"90.{board_code}",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "beg": "20200101",
        "end": datetime.now().strftime("%Y%m%d"),
        "lmt": "2000",
    }
    data = _em_request(url, params)
    if not data or not data.get("data") or not data["data"].get("klines"):
        logger.warning(f"  {board_name}({board_code}): 无K线数据")
        return None

    klines = data["data"]["klines"]
    rows = []
    for line in klines:
        parts = line.split(",")
        rows.append({
            "date": parts[0],
            "open": float(parts[1]),
            "close": float(parts[2]),
            "high": float(parts[3]),
            "low": float(parts[4]),
            "volume": float(parts[5]),
            "amount": float(parts[6]),
            "amplitude": float(parts[7]),
            "pct_change": float(parts[8]),
            "change": float(parts[9]),
            "turnover": float(parts[10]),
        })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 获取行业板块列表
    board_map = get_industry_board_list()
    if not board_map:
        logger.error("无法获取行业板块列表，退出")
        return

    # 2. 获取训练标的的行业
    stock_industries: dict[str, str] = {}
    for sym in SYMBOLS:
        industry = get_stock_industry(sym)
        if industry:
            stock_industries[sym] = industry
            logger.info(f"  {sym} → {industry}")
        else:
            logger.warning(f"  {sym}: 未获取到行业")
        time.sleep(0.3)

    # 3. 收集需要的行业板块
    needed_industries = set(stock_industries.values())
    logger.info(f"需要 {len(needed_industries)} 个行业板块: {needed_industries}")

    # 4. 下载行业板块K线
    board_kline_cache: dict[str, str] = {}
    for industry_name in needed_industries:
        board_code = board_map.get(industry_name)
        if not board_code:
            # 模糊匹配
            for bn, bc in board_map.items():
                if industry_name[:2] in bn or bn[:2] in industry_name:
                    board_code = bc
                    logger.info(f"  模糊匹配: {industry_name} → {bn}({bc})")
                    break
        if not board_code:
            logger.warning(f"  {industry_name}: 在板块列表中未找到")
            continue

        board_kline_cache[industry_name] = board_code
        cache_path = CACHE_DIR / f"{board_code}.parquet"
        if cache_path.exists():
            df = pd.read_parquet(cache_path)
            logger.info(f"  {industry_name}({board_code}): 已缓存 {len(df)} 条，跳过")
            continue

        logger.info(f"  下载 {industry_name}({board_code}) ...")
        df = download_board_kline(board_code, industry_name)
        if df is not None and not df.empty:
            df.to_parquet(cache_path)
            logger.info(f"    ✓ {len(df)} 条，{df.index[0].date()} ~ {df.index[-1].date()}")
        time.sleep(0.5)

    # 5. 保存映射文件
    mapping = {"stock_industries": stock_industries, "board_codes": board_kline_cache}
    mapping_path = CACHE_DIR / "mapping.json"
    mapping_path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False))
    logger.info(f"映射已保存: {mapping_path}")
    logger.info("完成")


if __name__ == "__main__":
    main()
