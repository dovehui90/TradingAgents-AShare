"""Tests for api.main._load_cn_stock_map — incremental merge + akshare lru_cache bypass.

根因：akshare 的 stock_info_a_code_name 及其底层三个接口都带 @lru_cache()，
进程启动后首次调用会把「当时的股票列表」永久缓存，导致进程启动后才上市的新股
即使项目级 7 天 TTL 过期重新加载也拿不到（重载仍命中 akshare 旧缓存）。

修复：重载前清 akshare lru_cache；并把「整体替换」改为「增量合并」——
旧 map 已有条目原地不动，只补入新出现的 name/code，加载失败时保留旧数据。
"""

import pandas as pd
import pytest

import akshare as ak
import api.main as main_mod


@pytest.fixture
def reset_stock_map():
    """Reset _load_cn_stock_map 模块级状态，保证测试隔离。"""
    main_mod._cn_stock_map = None
    main_mod._cn_stock_reverse_map = None
    main_mod._cn_a_stock_symbols = None
    main_mod._cn_stock_map_loaded_at = 0
    yield
    main_mod._cn_stock_map = None
    main_mod._cn_stock_reverse_map = None
    main_mod._cn_a_stock_symbols = None
    main_mod._cn_stock_map_loaded_at = 0


def _stock_df(pairs):
    """pairs: list of (name, code)。"""
    return pd.DataFrame([{"code": c, "name": n} for n, c in pairs])


def _fund_df(pairs):
    """pairs: list of (name, code)。"""
    return pd.DataFrame([{"基金代码": c, "基金简称": n} for n, c in pairs])


def _seed_old_map():
    """预置一份旧 map（只有老股），loaded_at=0 强制下次调用触发重载。"""
    main_mod._cn_stock_map = {"老股A": "000001.SZ"}
    main_mod._cn_stock_reverse_map = {"000001.SZ": "老股A"}
    main_mod._cn_a_stock_symbols = {"000001.SZ"}
    main_mod._cn_stock_map_loaded_at = 0


class TestIncrementalMerge:
    def test_preserves_existing_and_adds_new_stock(self, monkeypatch, reset_stock_map):
        """旧条目原地保留，新股（301660）增量补入。"""
        _seed_old_map()
        monkeypatch.setattr(
            ak, "stock_info_a_code_name",
            lambda: _stock_df([("老股A", "000001"), ("粤芯半导体-U", "301660")]),
        )
        monkeypatch.setattr(ak, "fund_name_em", lambda: pd.DataFrame())

        result = main_mod._load_cn_stock_map()

        assert result.get("老股A") == "000001.SZ"          # 旧条目保留
        assert result.get("粤芯半导体-U") == "301660.SZ"   # 新股补入
        assert main_mod._cn_stock_reverse_map.get("301660.SZ") == "粤芯半导体-U"
        assert "301660.SZ" in main_mod._cn_a_stock_symbols

    def test_adds_new_fund(self, monkeypatch, reset_stock_map):
        """新增 ETF/基金也能增量补入。"""
        _seed_old_map()
        monkeypatch.setattr(
            ak, "stock_info_a_code_name",
            lambda: _stock_df([("老股A", "000001")]),
        )
        monkeypatch.setattr(ak, "fund_name_em", lambda: _fund_df([("某ETF", "159900")]))

        result = main_mod._load_cn_stock_map()

        assert result.get("某ETF") == "159900.SZ"

    def test_does_not_overwrite_existing_entry(self, monkeypatch, reset_stock_map):
        """同 name 的旧条目不被新列表覆盖（改名/映射不变）。"""
        _seed_old_map()
        # 新列表里老股A 的 code 若变化（模拟异常），不应覆盖旧映射
        monkeypatch.setattr(
            ak, "stock_info_a_code_name",
            lambda: _stock_df([("老股A", "999999"), ("粤芯半导体-U", "301660")]),
        )
        monkeypatch.setattr(ak, "fund_name_em", lambda: pd.DataFrame())

        result = main_mod._load_cn_stock_map()

        assert result.get("老股A") == "000001.SZ"  # 旧映射保持不变

    def test_reload_clears_akshare_lru_cache(self, monkeypatch, reset_stock_map):
        """重载前清掉 akshare 四个带 lru_cache 的接口缓存。"""
        _seed_old_map()
        cleared = []

        class Fake:
            def __init__(self, n):
                self.n = n

            def cache_clear(self):
                cleared.append(self.n)

            def __call__(self):
                return _stock_df([("老股A", "000001")])

        for n in ("stock_info_a_code_name", "stock_info_sh_name_code",
                  "stock_info_sz_name_code", "stock_info_bj_name_code"):
            monkeypatch.setattr(ak, n, Fake(n))
        monkeypatch.setattr(ak, "fund_name_em", lambda: pd.DataFrame())

        main_mod._load_cn_stock_map()

        assert "stock_info_a_code_name" in cleared
        assert "stock_info_sh_name_code" in cleared
        assert "stock_info_sz_name_code" in cleared
        assert "stock_info_bj_name_code" in cleared

    def test_failed_reload_keeps_old_map(self, monkeypatch, reset_stock_map):
        """重载失败时不丢旧数据（不整体置空）。"""
        _seed_old_map()

        def boom():
            raise RuntimeError("network down")

        monkeypatch.setattr(ak, "stock_info_a_code_name", boom)
        monkeypatch.setattr(ak, "fund_name_em", lambda: pd.DataFrame())

        result = main_mod._load_cn_stock_map()

        assert result.get("老股A") == "000001.SZ"  # 旧数据保留

    def test_no_reload_when_fresh(self, monkeypatch, reset_stock_map):
        """TTL 未过期时不重载（缓存命中，不碰现有数据）。"""
        import time
        _seed_old_map()
        main_mod._cn_stock_map_loaded_at = time.time()  # 刚加载过，未过期

        called = {"n": 0}

        def fake_stock():
            called["n"] += 1
            return _stock_df([("老股A", "000001"), ("粤芯半导体-U", "301660")])

        monkeypatch.setattr(ak, "stock_info_a_code_name", fake_stock)
        monkeypatch.setattr(ak, "fund_name_em", lambda: pd.DataFrame())

        result = main_mod._load_cn_stock_map()

        assert called["n"] == 0  # 未重新拉取
        assert result.get("老股A") == "000001.SZ"
        assert result.get("粤芯半导体-U") is None  # 新股尚未进入（缓存未过期）
