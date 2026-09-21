"""Tests for position_index.extract_position_history — 逐日位置历史抽取。

选股神器「历史回看」最小版：从 calculate_position_index 的全序列结果，
按日抽取出 position_zone 与 position_transition（供按交易日分文件存储）。
"""

import pandas as pd

from tradingagents.indicators.position_index import extract_position_history


def _make_pos(dates, zones):
    return pd.DataFrame({
        "date": dates,
        "position_index": [0.0] * len(dates),  # 仅占位，extract 只用 zone 列
        "zone": zones,
    })


class TestExtractPositionHistory:
    def test_two_transitions_and_no_change(self):
        pos = _make_pos(
            ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"],
            ["oversold", "low", "low", "oversold"],
        )
        rows = extract_position_history(pos, "600089.SH")
        # 首日无前一日，不产出；后续每日一行
        assert [r["date"] for r in rows] == ["2026-09-16", "2026-09-17", "2026-09-18"]
        assert [r["position_zone"] for r in rows] == ["low", "low", "oversold"]
        # oversold→low = 超卖转偏低；low→low 无转变；low→oversold = 偏低转超卖
        assert [r["position_transition"] for r in rows] == [
            "oversold_to_low", None, "low_to_oversold",
        ]

    def test_symbol_passthrough(self):
        pos = _make_pos(["2026-09-15", "2026-09-16"], ["neutral", "low"])
        rows = extract_position_history(pos, "000001.SZ")
        assert all(r["symbol"] == "000001.SZ" for r in rows)

    def test_single_bar_returns_empty(self):
        pos = _make_pos(["2026-09-15"], ["low"])
        assert extract_position_history(pos, "X") == []

    def test_unknown_zone_no_transition(self):
        # 滚动预热期的 unknown 不产生误报
        pos = _make_pos(["2026-09-15", "2026-09-16"], ["unknown", "low"])
        rows = extract_position_history(pos, "X")
        assert rows[0]["position_transition"] is None

    def test_date_index_fallback(self):
        # 无 date 列时回退用 datetime 索引
        idx = pd.to_datetime(["2026-09-15", "2026-09-16"])
        pos = pd.DataFrame({"position_index": [0.0, 0.0], "zone": ["low", "oversold"]}, index=idx)
        rows = extract_position_history(pos, "X")
        assert rows[0]["date"] == "2026-09-16"
        assert rows[0]["position_transition"] == "low_to_oversold"


class TestPositionHistoryStorage:
    """save_position_history / load_position_history 往返（重点验证 None 不变成 NaN）。"""

    def test_save_load_roundtrip(self, tmp_path, monkeypatch):
        from tradingagents.screener import cache as cache_mod
        monkeypatch.setattr(cache_mod, "_POSITION_HISTORY_DIR", tmp_path)

        rows = [
            {"date": "2026-09-16", "symbol": "600089.SH", "position_zone": "low",
             "position_transition": "oversold_to_low"},
            {"date": "2026-09-16", "symbol": "000001.SZ", "position_zone": "oversold",
             "position_transition": None},
        ]
        cache_mod.save_position_history(rows)

        loaded = cache_mod.load_position_history("2026-09-16")
        assert loaded is not None
        by_symbol = {r["symbol"]: r for r in loaded}
        assert by_symbol["600089.SH"]["position_transition"] == "oversold_to_low"
        assert by_symbol["000001.SZ"]["position_transition"] is None
        # 缺失日期返回 None
        assert cache_mod.load_position_history("1999-01-01") is None
