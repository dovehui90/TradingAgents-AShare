"""Screener cache — standalone, does not touch 大盘点金 pipeline."""

import logging
import os
import time
from datetime import date, datetime, time as dt_time, timedelta
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


def _next_trading_day(d: date) -> date:
    """返回严格晚于 d 的下一个交易日。

    用真实交易日历（is_cn_trading_day），覆盖周末与长假（春节/国庆约 7-8 个交易日）；
    日历加载失败时降级为仅周末过滤。
    """
    from tradingagents.dataflows.trade_calendar import is_cn_trading_day

    cur = d + timedelta(days=1)
    for _ in range(30):  # 30 天上界，覆盖最长连续休市
        if is_cn_trading_day(cur.strftime("%Y-%m-%d")):
            return cur
        cur += timedelta(days=1)
    # 降级：仅周末过滤
    while cur.weekday() >= 5:
        cur += timedelta(days=1)
    return cur


def _is_stale(path: Path) -> bool:
    """判断缓存是否过期。

    核心修复：按「落盘时间」而非「当前时间」决定用哪套过期规则——
    - 盘中落盘（当日 15:45 前）：盘中价，2 小时过期；
    - 收盘后落盘（当日 15:45 后）：最终收盘价，有效到下一个交易日收盘前。

    旧实现用「当前时间 < 15:45」决定 TTL，导致早上未开盘时把隔夜收盘数据
    误判为盘中 2 小时 → 每次早上重启都全量重抓（隔夜/周末数据本无需更新）。

    「下一个交易日」用真实交易日历（_next_trading_day），长假期间收盘后落盘的
    缓存不会被误判过期 → 不再触发长假首日的全量重复抓取。
    """
    if not path.exists():
        return True

    mtime = path.stat().st_mtime
    mtime_dt = datetime.fromtimestamp(mtime)

    # 盘中落盘 → 2 小时过期
    if mtime_dt.time() < _MARKET_CLOSE:
        return (time.time() - mtime) > _CACHE_TTL_DAY

    # 收盘后落盘 → 有效到下一个交易日（跳过周末+长假）收盘
    next_td = _next_trading_day(mtime_dt.date())
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

# 信号缓存过期时间：与 scheduler/screener_scheduler.py 盘后 17:00 重算对齐，
# 加 30 分钟缓冲，等重算完成后再判过期，避免重算窗口期内被误判为无数据。
_SIGNAL_RECOMPUTE_TIME = dt_time(17, 30)


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


def _is_signal_cache_stale(path: Path) -> bool:
    """信号快照（signals.json）过期判定。

    核心规则：只有在「出现了更新的交易日数据」时才判过期，其余情况一律返回缓存——
    - 非交易日（周末/长假）：永不判过期，直接显示最近一次盘后重算（上一交易日）的数据；
    - 交易日：当天盘后重算（17:30）之前仍用旧数据；已过重算时间但缓存还没更新到当天，才判过期。

    旧实现用 24h TTL，周五盘后写入的信号周末/长假超过 24h 被误判过期 → 选股神器无数据。
    """
    if not path.exists():
        return True

    from tradingagents.dataflows.trade_calendar import is_cn_trading_day, cn_today_str

    today = cn_today_str()
    # 非交易日：缓存永不判过期，直接显示上一个交易日数据
    if not is_cn_trading_day(today):
        return False

    # 交易日：缓存已更新到当天（盘后重算过）→ 不判过期
    mtime_date = datetime.fromtimestamp(path.stat().st_mtime).date()
    if mtime_date >= date.fromisoformat(today):
        return False

    # 当天还没到盘后重算时间 → 旧数据仍是最新可用，先用着
    if datetime.now().time() < _SIGNAL_RECOMPUTE_TIME:
        return False

    # 已过盘后重算时间但缓存没更新到当天 → 过期（触发重算）
    return True


def load_signal_cache() -> Optional[list[dict]]:
    """读预计算的指标结果；过期（出现更新的交易日数据且未重算）返回 None。"""
    if _is_signal_cache_stale(_SIGNAL_CACHE_PATH):
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


def signal_history_dates() -> set[str]:
    """返回已存在的信号历史文件日期集合（YYYY-MM-DD），用于判断增量 vs 回填。"""
    if not _SIGNAL_HISTORY_DIR.exists():
        return set()
    return {p.stem for p in _SIGNAL_HISTORY_DIR.glob("*.parquet")}


def save_signal_history(rows: list[dict], skip_existing: bool = True):
    """把逐日全维度信号按交易日分文件存成 parquet（每天一个文件，约 4757 行）。

    skip_existing=True（默认）：已存在的日期文件跳过不重写 —— 历史信号是点-in-time
    的（历史值不随新增交易日变化），增量模式下只需写新日期，避免每天重写 60 个文件。

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
    written = 0
    for date, grp in df.groupby("date"):
        path = _SIGNAL_HISTORY_DIR / f"{date}.parquet"
        if skip_existing and path.exists():
            continue
        out = grp.drop(columns=["date"]).reset_index(drop=True)
        # 原子写：先写 tmp 再 os.replace，避免写一半崩溃留下损坏/半截文件
        tmp_path = path.with_name(path.name + ".tmp")
        out.to_parquet(tmp_path, index=False)
        os.replace(tmp_path, path)
        written += 1
    logger.info(
        f"Signal history saved: {len(rows)} rows across {df['date'].nunique()} dates "
        f"(written={written}, skipped={df['date'].nunique() - written})"
    )


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
