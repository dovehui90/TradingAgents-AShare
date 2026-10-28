"""Tests for concept cache — 过期不清空 + 增量补齐。

根因：concept_map.json 30 天 TTL 过期后 load_concept_map 返回空，
_build_concept_cache 再 `concept_map = {}` 清空重来，全量重爬 5000+ 只
一旦中断就停在中断点（如 1658 只），导致筛选结果大量缺概念。

修复：
1. load_concept_map 过期也返回旧数据（不再判 30 天过期清空）；
2. _build_concept_cache 增量补齐缺失的 symbol，不清空已有数据。
"""

import os
import time

import requests as _requests_mod
import time as _time_mod

import api.main as main_mod
from tradingagents.screener import cache as cache_mod


def test_load_concept_map_returns_stale_data(monkeypatch, tmp_path):
    """过期（mtime > 30 天）也返回旧数据，不再清空。"""
    monkeypatch.setattr(cache_mod, "_CONCEPT_CACHE", None)
    p = tmp_path / "concept_map.json"
    p.write_text('{"000001.SZ": ["旧概念"]}', encoding="utf-8")
    old = time.time() - 60 * 86400  # 60 天前
    os.utime(p, (old, old))
    monkeypatch.setattr(cache_mod, "_CONCEPT_MAP_PATH", p)

    result = cache_mod.load_concept_map()

    assert result == {"000001.SZ": ["旧概念"]}


def test_load_concept_map_returns_empty_when_missing(monkeypatch, tmp_path):
    """文件不存在时返回空 dict（触发全量构建）。"""
    monkeypatch.setattr(cache_mod, "_CONCEPT_CACHE", None)
    monkeypatch.setattr(cache_mod, "_CONCEPT_MAP_PATH", tmp_path / "nope.json")

    assert cache_mod.load_concept_map() == {}


class _FakeResp:
    def __init__(self, text):
        self.content = text.encode("gbk")


def test_build_concept_cache_incremental_fill(monkeypatch):
    """已有部分数据时，只爬缺失的 symbol，不清空、不重爬已有的。"""
    existing = {"000001.SZ": ["旧概念"]}
    saved = {}

    monkeypatch.setattr(cache_mod, "load_concept_map", lambda: dict(existing))

    def fake_save(m):
        saved.clear()
        saved.update(m)

    monkeypatch.setattr(cache_mod, "save_concept_map", fake_save)

    # 候选池 3 只：000001 已有概念，000002/000003 缺失
    stock_map = {"股1": "000001.SZ", "股2": "000002.SZ", "股3": "000003.SZ"}
    monkeypatch.setattr(main_mod, "_load_cn_stock_map", lambda: stock_map)

    called_codes = []

    def fake_get(url, **kwargs):
        code = url.split("/")[-2]
        called_codes.append(code)
        return _FakeResp('<td class="gnName">新概念1</td><td class="gnName">新概念2</td>')

    monkeypatch.setattr(_requests_mod, "get", fake_get)
    monkeypatch.setattr(_time_mod, "sleep", lambda _: None)

    main_mod._build_concept_cache()

    # 只爬了缺失的 2 只，没重爬已有的 000001
    assert called_codes == ["000002", "000003"]
    # 旧数据保留 + 新数据补入
    assert saved["000001.SZ"] == ["旧概念"]
    assert saved["000002.SZ"] == ["新概念1", "新概念2"]
    assert saved["000003.SZ"] == ["新概念1", "新概念2"]


def test_build_concept_cache_no_missing_returns_early(monkeypatch):
    """无缺失时直接返回，不发任何网络请求。"""
    existing = {"000001.SZ": ["旧概念"], "000002.SZ": ["旧概念"]}
    saved = {}

    monkeypatch.setattr(cache_mod, "load_concept_map", lambda: dict(existing))

    def fake_save(m):
        saved.clear()
        saved.update(m)

    monkeypatch.setattr(cache_mod, "save_concept_map", fake_save)

    stock_map = {"股1": "000001.SZ", "股2": "000002.SZ"}
    monkeypatch.setattr(main_mod, "_load_cn_stock_map", lambda: stock_map)

    called = {"n": 0}

    def fake_get(url, **kwargs):
        called["n"] += 1
        return _FakeResp('<td class="gnName">x</td>')

    monkeypatch.setattr(_requests_mod, "get", fake_get)
    monkeypatch.setattr(_time_mod, "sleep", lambda _: None)

    main_mod._build_concept_cache()

    assert called["n"] == 0  # 无缺失，不爬


def test_build_concept_cache_retries_on_empty(monkeypatch):
    """概念为空时重试（THS 反爬返回空页），重试后成功则写入。"""
    existing = {}
    saved = {}

    monkeypatch.setattr(cache_mod, "load_concept_map", lambda: dict(existing))

    def fake_save(m):
        saved.clear()
        saved.update(m)

    monkeypatch.setattr(cache_mod, "save_concept_map", fake_save)
    stock_map = {"股1": "000001.SZ"}
    monkeypatch.setattr(main_mod, "_load_cn_stock_map", lambda: stock_map)

    calls = {"n": 0}

    def fake_get(url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            return _FakeResp("<html>no concept</html>")
        return _FakeResp('<td class="gnName">概念A</td>')

    monkeypatch.setattr(_requests_mod, "get", fake_get)
    monkeypatch.setattr(_time_mod, "sleep", lambda _: None)

    main_mod._build_concept_cache()

    assert calls["n"] == 3
    assert saved["000001.SZ"] == ["概念A"]


def test_build_concept_cache_retries_on_exception(monkeypatch):
    """请求异常时重试，重试成功则写入。"""
    existing = {}
    saved = {}

    monkeypatch.setattr(cache_mod, "load_concept_map", lambda: dict(existing))

    def fake_save(m):
        saved.clear()
        saved.update(m)

    monkeypatch.setattr(cache_mod, "save_concept_map", fake_save)
    stock_map = {"股1": "000001.SZ"}
    monkeypatch.setattr(main_mod, "_load_cn_stock_map", lambda: stock_map)

    calls = {"n": 0}

    def fake_get(url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("timeout")
        return _FakeResp('<td class="gnName">概念A</td>')

    monkeypatch.setattr(_requests_mod, "get", fake_get)
    monkeypatch.setattr(_time_mod, "sleep", lambda _: None)

    main_mod._build_concept_cache()

    assert calls["n"] == 3
    assert saved["000001.SZ"] == ["概念A"]
