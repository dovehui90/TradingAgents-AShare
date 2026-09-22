"""Screener cache — standalone, does not touch 大盘点金 pipeline."""

import logging
import os
import time
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "screener_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 缓存有效期：盘中数据 2 小时过期（盘中价持续变动）
_CACHE_TTL_DAY = 7200   # 2 hours during trading
# 收盘判定时间点（含 45 分钟缓冲，避免收盘后数据源尚未更新时误判）
_MARKET_CLOSE = dt_time(15, 45)


def _cache_path(symbol: str) -> Path:
    code = symbol.split(".")[0]
    suffix = symbol.split(".")[1].upper()
    return CACHE_DIR / f"{code}_{suffix}.parquet"


def _is_stale(path: Path) -> bool:
    """判断缓存是否过期。

    核心修复：按「落盘时间」而非「当前时间」决定用哪套过期规则——
    - 盘中落盘（当日 15:45 前）：盘中价，2 小时过期；
    - 收盘后落盘（当日 15:45 后）：最终收盘价，有效到下一个交易日收盘前。

    旧实现用「当前时间 < 15:45」决定 TTL，导致早上未开盘时把隔夜收盘数据
    误判为盘中 2 小时 → 每次早上重启都全量重抓（隔夜/周末数据本无需更新）。

    注：这里的「交易日」仅按周末过滤（未接入节假日日历），长假首日仍会多抓一次，
    属于无害的重复抓取（拿到的仍是上一收盘数据）。
    """
    if not path.exists():
        return True

    mtime = path.stat().st_mtime
    mtime_dt = datetime.fromtimestamp(mtime)

    # 盘中落盘 → 2 小时过期
    if mtime_dt.time() < _MARKET_CLOSE:
        return (time.time() - mtime) > _CACHE_TTL_DAY

    # 收盘后落盘 → 有效到下一个交易日（跳过周末）收盘
    next_td = mtime_dt.date() + timedelta(days=1)
    while next_td.weekday() >= 5:  # 5=周六 6=周日
        next_td += timedelta(days=1)
    next_close = datetime.combine(next_td, _MARKET_CLOSE)
    return datetime.now() >= next_close


def get_kline(symbol: str, days: int = 250, fetch_if_missing: bool = True) -> Optional[pd.DataFrame]:
    """Get K-line data from cache, or fetch + cache if stale or missing.

    fetch_if_missing=False 时只读缓存，缓存缺失/过期直接返回 None，绝不触发网络抓取。
    （screener 用它，避免冷缓存时请求被慢速实时抓取拖垮。）
    """
    path = _cache_path(symbol)

    if not _is_stale(path):
        try:
            df = pd.read_parquet(str(path))
            if not df.empty and "close" in df.columns:
                return df.tail(days)
        except Exception as e:
            logger.warning(f"[file read] failed: {e}", exc_info=True)

    if not fetch_if_missing:
        return None

    # Fetch fresh data
    from tradingagents.indicators import fetch_realtime_data

    try:
        df = fetch_realtime_data(symbol, days=days, period="daily")
    except Exception:
        return None

    if df is None or df.empty:
        return None

    # Reset index for parquet storage
    df_out = df.reset_index()
    try:
        df_out.to_parquet(str(path), index=False)
    except Exception as e:
        logger.debug(f"[file write] failed: {e}", exc_info=True)
    return df


def build_screener_cache(symbols: list[str], max_workers: int = 8):
    """Pre-compute and cache K-line data for a list of symbols. Call on first use or daily."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    updated = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(get_kline, s): s for s in symbols}
        for fut in as_completed(futures):
            try:
                df = fut.result(timeout=45)
                if df is not None and not df.empty:
                    updated += 1
            except Exception as e:
                logger.debug(f"[operation] failed: {e}", exc_info=True)
    logger.info(f"Screener cache updated: {updated}/{len(symbols)} stocks")
    return updated


def cached_symbol_count() -> int:
    return len(list(CACHE_DIR.glob("*.parquet")))


# ── Concept reverse index ──

_CONCEPT_MAP_PATH = CACHE_DIR / "concept_map.json"
_CONCEPT_CACHE: Optional[dict] = None


def load_concept_map() -> dict[str, list[str]]:
    """Load stock→concepts mapping from cache, or return empty."""
    global _CONCEPT_CACHE
    if _CONCEPT_CACHE is not None:
        return _CONCEPT_CACHE

    path = _CONCEPT_MAP_PATH
    if path.exists():
        try:
            import json
            age = time.time() - path.stat().st_mtime
            if age < 30 * 86400:  # 1 month TTL
                with open(path, encoding='utf-8') as f:
                    _CONCEPT_CACHE = json.load(f)
                return _CONCEPT_CACHE
        except Exception as e:
            logger.debug(f"[JSON parse] failed: {e}", exc_info=True)
        return {}


def save_concept_map(concept_map: dict[str, list[str]]):
    """Persist concept reverse index."""
    import json
    global _CONCEPT_CACHE
    _CONCEPT_CACHE = concept_map
    with open(_CONCEPT_MAP_PATH, "w", encoding='utf-8') as f:
        json.dump(concept_map, f, ensure_ascii=False)
    logger.info(f"Concept map saved: {len(concept_map)} stocks")


# ── 指标结果缓存（预计算，避免请求内重算全量指标）──

_SIGNAL_CACHE_PATH = CACHE_DIR / "signals.json"


def save_signal_cache(rows: list[dict]):
    """把预计算好的全量指标结果存成单个 json 文件。

    原子写：先写临时文件再 os.replace，避免重算过程中 signals.json 被删/写一半，
    导致请求窗口期内读到空文件（选股神器无数据）。
    """
    import json
    import os
    tmp_path = _SIGNAL_CACHE_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False)
    os.replace(tmp_path, _SIGNAL_CACHE_PATH)
    logger.info(f"Signal cache saved: {len(rows)} stocks")


def load_signal_cache() -> Optional[list[dict]]:
    """读预计算的指标结果；过期（超过 24h，即非当天）返回 None。"""
    if not _SIGNAL_CACHE_PATH.exists():
        return None
    age = time.time() - _SIGNAL_CACHE_PATH.stat().st_mtime
    if age > 86400:  # 24h TTL（指标随收盘价每天变化，每日重算一次）
        return None
    try:
        import json
        with open(_SIGNAL_CACHE_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[signal cache read] failed: {e}", exc_info=True)
        return None


# ── 信号历史（按交易日分文件，供选股神器历史回看，覆盖所有维度）──

_SIGNAL_HISTORY_DIR = CACHE_DIR / "signal_history"

_SIGNAL_STRING_FIELDS = [
    "position_zone", "position_transition", "decision_status",
    "bull_status", "orbit_status", "gs_status", "trend_status",
]


def save_signal_history(rows: list[dict]):
    """把逐日全维度信号按交易日分文件存成 parquet（每天一个文件，约 4757 行）。

    rows: [{date, symbol, price, change_pct, position_zone, position_transition,
            decision_status, bull_status, orbit_status, gs_status, trend_status,
            radar_wave}, ...]
    """
    if not rows:
        return
    import pandas as pd
    _SIGNAL_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    # 字符串字段 None → ""，避免 parquet 往返把 None 变 NaN
    for f in _SIGNAL_STRING_FIELDS:
        if f in df.columns:
            df[f] = df[f].fillna("").astype(str)
    for date, grp in df.groupby("date"):
        out = grp.drop(columns=["date"]).reset_index(drop=True)
        out.to_parquet(_SIGNAL_HISTORY_DIR / f"{date}.parquet", index=False)
    logger.info(f"Signal history saved: {len(rows)} rows across {df['date'].nunique()} dates")


def load_signal_history(date_str: str) -> Optional[list[dict]]:
    """读取某交易日的全维度信号历史。缺失返回 None。"""
    import math
    import pandas as pd
    path = _SIGNAL_HISTORY_DIR / f"{date_str}.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(str(path))
    except Exception as e:
        logger.warning(f"[signal history read] failed: {e}", exc_info=True)
        return None
    records = df.to_dict("records")
    for r in records:
        for f in _SIGNAL_STRING_FIELDS:
            if r.get(f) == "":
                r[f] = None
        # float NaN → None（price/change_pct/radar_wave 的缺失值）
        for k, v in list(r.items()):
            if isinstance(v, float) and math.isnan(v):
                r[k] = None
    return records
