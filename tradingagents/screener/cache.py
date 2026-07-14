"""Screener cache — standalone, does not touch 大盘点金 pipeline."""

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "screener_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 缓存有效期：收盘前盘中数据2小时，收盘后数据到明日开盘前
_CACHE_TTL_DAY = 7200   # 2 hours during trading
_CACHE_TTL_NIGHT = 86400  # 24 hours after close


def _cache_path(symbol: str) -> Path:
    code = symbol.split(".")[0]
    suffix = symbol.split(".")[1].upper()
    return CACHE_DIR / f"{code}_{suffix}.parquet"


def _is_stale(path: Path) -> bool:
    """Check if cache is stale based on modification time and market hours."""
    if not path.exists():
        return True
    age = time.time() - path.stat().st_mtime
    now = datetime.now()
    market_close = now.replace(hour=15, minute=45, second=0, microsecond=0)
    if now < market_close:
        return age > _CACHE_TTL_DAY
    return age > _CACHE_TTL_NIGHT


def get_kline(symbol: str, days: int = 250) -> Optional[pd.DataFrame]:
    """Get K-line data from cache, or fetch + cache if stale or missing."""
    path = _cache_path(symbol)

    if not _is_stale(path):
        try:
            df = pd.read_parquet(str(path))
            if not df.empty and "close" in df.columns:
                return df.tail(days)
        except Exception:
            pass

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
    except Exception:
        pass

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
            except Exception:
                pass
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
            if age < 7 * 86400:  # 1 week TTL
                with open(path) as f:
                    _CONCEPT_CACHE = json.load(f)
                return _CONCEPT_CACHE
        except Exception:
            pass
    return {}


def save_concept_map(concept_map: dict[str, list[str]]):
    """Persist concept reverse index."""
    import json
    global _CONCEPT_CACHE
    _CONCEPT_CACHE = concept_map
    with open(_CONCEPT_MAP_PATH, "w") as f:
        json.dump(concept_map, f, ensure_ascii=False)
    logger.info(f"Concept map saved: {len(concept_map)} stocks")
