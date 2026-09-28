"""Tests for tradingagents/screener/cache.py — cache staleness and file I/O.

Uses tmp_path for filesystem isolation and freezegun for time control.
"""

import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from freezegun import freeze_time

# Import the module to get CACHE_DIR, but override paths in tests
os.environ.setdefault("_TESTING", "1")


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Redirect screener cache CACHE_DIR to a temp directory."""
    import tradingagents.screener.cache as cache_mod

    test_dir = tmp_path / "screener_cache"
    test_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cache_mod, "CACHE_DIR", test_dir)
    monkeypatch.setattr(cache_mod, "_CONCEPT_MAP_PATH", test_dir / "concept_map.json")
    # Reset module-level cache
    monkeypatch.setattr(cache_mod, "_CONCEPT_CACHE", None)
    return test_dir


class TestCachePath:
    """_cache_path() tests."""

    def test_sz_stock(self, cache_dir):
        from tradingagents.screener.cache import _cache_path

        path = _cache_path("000001.SZ")
        assert path.name == "000001_SZ.parquet"
        assert path.parent == cache_dir

    def test_sh_stock(self, cache_dir):
        from tradingagents.screener.cache import _cache_path

        path = _cache_path("600519.SH")
        assert path.name == "600519_SH.parquet"

    def test_bj_stock(self, cache_dir):
        from tradingagents.screener.cache import _cache_path

        path = _cache_path("920001.BJ")
        assert path.name == "920001_BJ.parquet"


class TestIsStale:
    """_is_stale() tests with freezegun."""

    def test_missing_file_is_stale(self, cache_dir):
        from tradingagents.screener.cache import _is_stale

        path = cache_dir / "nonexistent.parquet"
        assert _is_stale(path) is True

    @freeze_time("2026-07-15 10:00:00")
    def test_recent_file_during_trading_not_stale(self, cache_dir):
        from tradingagents.screener.cache import _is_stale

        path = cache_dir / "test.parquet"
        path.write_text("dummy")
        # mtime is now (frozen at 10:00)
        assert _is_stale(path) is False

    @freeze_time("2026-07-15 10:00:00")
    def test_old_file_during_trading_is_stale(self, cache_dir):
        from tradingagents.screener.cache import _is_stale

        path = cache_dir / "test.parquet"
        path.write_text("dummy")
        # Set mtime to 3 hours ago
        old_time = time.time() - 7201
        os.utime(str(path), (old_time, old_time))
        assert _is_stale(path) is True

    @freeze_time("2026-07-15 18:00:00")
    def test_after_market_close_uses_longer_ttl(self, cache_dir):
        from tradingagents.screener.cache import _is_stale

        path = cache_dir / "test.parquet"
        path.write_text("dummy")
        # Set mtime to 2 hours ago (exceeds day TTL but within night TTL)
        old_time = time.time() - 7201
        os.utime(str(path), (old_time, old_time))
        # After market close, TTL is 86400s, so 7201s old → not stale
        assert _is_stale(path) is False

    @freeze_time("2026-07-15 07:33:00")  # 周三早上（未开盘）
    def test_overnight_close_data_not_stale_in_morning(self, cache_dir):
        """隔夜收盘数据在次日早上不应被误判过期（旧 bug：早上全量重抓）。"""
        from tradingagents.screener.cache import _is_stale

        path = cache_dir / "test.parquet"
        path.write_text("dummy")
        # 落盘时间 = 昨日（周二）16:00 收盘后，距今 15h33m
        old_time = time.time() - (15 * 3600 + 33 * 60)
        os.utime(str(path), (old_time, old_time))
        assert _is_stale(path) is False

    @freeze_time("2026-07-20 07:33:00")  # 周一早上（未开盘）
    def test_friday_close_data_not_stale_monday_morning(self, cache_dir):
        """周五收盘数据在周一早上不应被误判过期（跨周末）。"""
        from tradingagents.screener.cache import _is_stale

        path = cache_dir / "test.parquet"
        path.write_text("dummy")
        # 落盘时间 = 上周五 16:00 收盘后，距今 2 天 15h33m
        old_time = time.time() - (2 * 86400 + 15 * 3600 + 33 * 60)
        os.utime(str(path), (old_time, old_time))
        assert _is_stale(path) is False

    @freeze_time("2026-07-16 16:00:00")  # 周四收盘后
    def test_stale_after_next_trading_day_close(self, cache_dir):
        """下一个交易日收盘后，上一收盘数据应过期（有新收盘价了）。"""
        from tradingagents.screener.cache import _is_stale

        path = cache_dir / "test.parquet"
        path.write_text("dummy")
        # 落盘时间 = 昨日（周三）16:00 收盘后，距今 24h（已过今日收盘）
        old_time = time.time() - 86400
        os.utime(str(path), (old_time, old_time))
        assert _is_stale(path) is True


class TestIsStaleHoliday:
    """长假期间 K 线缓存不应被判过期（_is_stale 改用真实交易日历）。"""

    HOLIDAYS = {"2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"}

    @pytest.fixture(autouse=True)
    def _mock_calendar(self, monkeypatch):
        import tradingagents.dataflows.trade_calendar as tc

        def fake_is_trading(d: str) -> bool:
            dt = datetime.strptime(d, "%Y-%m-%d")
            if dt.weekday() >= 5:  # 周末
                return False
            return d not in self.HOLIDAYS

        monkeypatch.setattr(tc, "is_cn_trading_day", fake_is_trading)

    def test_next_trading_day_skips_holiday(self, cache_dir):
        from tradingagents.screener.cache import _next_trading_day

        # 节前最后交易日 09-30（周三）→ 下一交易日应跳过国庆长假到 10-08（周四）
        assert _next_trading_day(datetime(2026, 9, 30).date()) == datetime(2026, 10, 8).date()
        # 普通周末：周五 09-25 → 周一 09-28
        assert _next_trading_day(datetime(2026, 9, 25).date()) == datetime(2026, 9, 28).date()

    @freeze_time("2026-10-03 12:00:00")  # 国庆长假中（周六）
    def test_holiday_keeps_pre_holiday_close_cache_fresh(self, cache_dir):
        from tradingagents.screener.cache import _is_stale

        path = cache_dir / "test.parquet"
        path.write_text("dummy")
        # 落盘时间 = 09-30（节前最后交易日）17:05，长假中读取 → 不应过期
        mtime = datetime(2026, 9, 30, 17, 5).timestamp()
        os.utime(str(path), (mtime, mtime))
        assert _is_stale(path) is False

    @freeze_time("2026-10-08 16:00:00")  # 节后第一个交易日收盘后
    def test_stale_after_holiday_first_trading_day_close(self, cache_dir):
        from tradingagents.screener.cache import _is_stale

        path = cache_dir / "test.parquet"
        path.write_text("dummy")
        mtime = datetime(2026, 9, 30, 17, 5).timestamp()
        os.utime(str(path), (mtime, mtime))
        # 10-08 已收盘（16:00 > 15:45），节前数据应过期
        assert _is_stale(path) is True


class TestConceptMapCache:
    """load_concept_map() / save_concept_map() tests."""

    def test_load_returns_none_for_missing_file(self, cache_dir):
        """When concept_map.json doesn't exist, load_concept_map returns None."""
        from tradingagents.screener.cache import load_concept_map

        result = load_concept_map()
        assert result is None

    def test_save_and_load_roundtrip(self, cache_dir):
        from tradingagents.screener.cache import load_concept_map, save_concept_map

        test_map = {"000001.SZ": ["概念A", "概念B"], "600519.SH": ["白酒"]}
        save_concept_map(test_map)

        # load should return the same data (within TTL)
        result = load_concept_map()
        assert result == test_map

    @freeze_time("2026-07-15 10:00:00")
    def test_expired_cache_returns_empty(self, cache_dir):
        from tradingagents.screener.cache import load_concept_map, save_concept_map

        test_map = {"000001.SZ": ["概念A"]}
        save_concept_map(test_map)

        # Set file mtime to 31 days ago
        old_mtime = time.time() - (31 * 86400)
        concept_path = cache_dir / "concept_map.json"
        os.utime(str(concept_path), (old_mtime, old_mtime))

        # Also reset module cache so it re-reads from disk
        import tradingagents.screener.cache as cache_mod
        cache_mod._CONCEPT_CACHE = None

        result = load_concept_map()
        assert result == {}


class TestCachedSymbolCount:
    """cached_symbol_count() tests."""

    def test_empty_dir_returns_zero(self, cache_dir):
        from tradingagents.screener.cache import cached_symbol_count

        assert cached_symbol_count() == 0

    def test_counts_parquet_files(self, cache_dir):
        from tradingagents.screener.cache import cached_symbol_count

        (cache_dir / "000001_SZ.parquet").write_text("dummy")
        (cache_dir / "600519_SH.parquet").write_text("dummy")
        (cache_dir / "not_a_parquet.txt").write_text("dummy")

        assert cached_symbol_count() == 2


class TestResolveScreenerDataDate:
    """resolve_screener_data_date — 数据日期回退（方案A）。

    核心诉求：日历上的最近交易日（latest_cn_trading_day 含当日）在当天 17:00
    盘后重算前还没有当日信号数据，需回退到最近一个有数据的交易日，避免
    data_date 显示当天却筛出前一交易日数据。
    """

    def _setup(self, monkeypatch, today, history_dates):
        """mock 交易日历（纯工作日，忽略节假日）与信号历史日期集合。"""
        import tradingagents.dataflows.trade_calendar as tc
        import tradingagents.screener.cache as cache_mod

        # 纯工作日日历：2026-09-01 ~ 2026-10-31
        dates = []
        d = date(2026, 9, 1)
        end = date(2026, 10, 31)
        while d <= end:
            if d.weekday() < 5:
                dates.append(d)
            d += timedelta(days=1)
        monkeypatch.setattr(tc, "_load_cn_trade_dates", lambda: (dates, set(dates)))
        monkeypatch.setattr(tc, "cn_today_str", lambda: today)
        monkeypatch.setattr(cache_mod, "signal_history_dates", lambda: history_dates)

    def _resolve(self):
        from tradingagents.screener.cache import resolve_screener_data_date
        return resolve_screener_data_date

    def test_default_latest_rollback_when_today_not_computed(self, monkeypatch):
        # 周一(交易日)默认最新，但当天盘后重算未跑 → 回退到周五
        self._setup(monkeypatch, today="2026-09-28", history_dates={"2026-09-25"})
        assert self._resolve()(None) == "2026-09-25"

    def test_default_latest_no_rollback_when_today_computed(self, monkeypatch):
        self._setup(monkeypatch, today="2026-09-28",
                    history_dates={"2026-09-25", "2026-09-28"})
        assert self._resolve()(None) == "2026-09-28"

    def test_weekend_default_returns_last_trading_day(self, monkeypatch):
        # 周日默认最新 → 最近交易日=周五，周五有数据，不回退
        self._setup(monkeypatch, today="2026-09-27", history_dates={"2026-09-25"})
        assert self._resolve()(None) == "2026-09-25"

    def test_explicit_past_date_not_rolled_back(self, monkeypatch):
        # 明确选历史日期 → 原样返回，不做回退
        self._setup(monkeypatch, today="2026-09-28",
                    history_dates={"2026-09-25", "2026-09-21"})
        assert self._resolve()("2026-09-21") == "2026-09-21"

    def test_explicit_today_rollback_when_not_computed(self, monkeypatch):
        # 明确选今天(交易日)但当天未重算 → 回退到上一交易日
        self._setup(monkeypatch, today="2026-09-28", history_dates={"2026-09-25"})
        assert self._resolve()("2026-09-28") == "2026-09-25"

    def test_future_date_rolls_back_to_latest_available(self, monkeypatch):
        # 选未来日期 → 对齐后无数据 → 回退到最近有数据的交易日
        self._setup(monkeypatch, today="2026-09-28", history_dates={"2026-09-25"})
        assert self._resolve()("2026-10-01") == "2026-09-25"

    def test_empty_history_rolls_back_to_prev_trading_day(self, monkeypatch):
        # 冷启动（无任何信号历史）→ 回退到上一交易日（数据本身也为空，仅日期诚实）
        self._setup(monkeypatch, today="2026-09-28", history_dates=set())
        assert self._resolve()(None) == "2026-09-25"

    def test_multi_day_gap_rolls_to_latest_available(self, monkeypatch):
        # 断档多日（周四/周五缺）→ 回退到最近有数据的周三，而非上一交易日周五
        self._setup(monkeypatch, today="2026-09-28", history_dates={"2026-09-23"})
        assert self._resolve()(None) == "2026-09-23"
