"""Tests for signal_history.derive_daily_signals — 全维度逐日信号抽取。"""

from tradingagents.indicators.signal_history import (
    derive_daily_signals,
    derive_gs_states,
    derive_weekly_gs_status,
)


def _make(dates, close, **kw):
    n = len(dates)
    def arr(v):
        return v if isinstance(v, (list, tuple)) else [v] * n
    return dict(
        dates=dates, close=close,
        decision_line=arr(kw.get("dl", 10.5)), bull_line=arr(kw.get("bl", 9.0)),
        orbit_line=arr(kw.get("orbit", 10.2)), zones=kw.get("zones", ["low"] * n),
        gs_buy=kw.get("gs_buy", [False] * n), gs_sell=kw.get("gs_sell", [False] * n),
        trend_strength=kw.get("trend", [1.0] * n), radar_wave=kw.get("radar", [0.5] * n),
        symbol="600089.SH",
    )


class TestDeriveDailySignals:
    def test_full_dimensions_per_bar(self):
        dates = ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]
        args = _make(
            dates,
            close=[10.0, 11.0, 10.5, 10.0, 10.8],
            dl=10.5, bl=9.0, orbit=10.2,
            zones=["low", "oversold", "low", "oversold", "low"],
            gs_buy=[False, True, False, False, False],
            gs_sell=[False, False, False, True, False],
            trend=[1.0, 1.0, -1.0, -1.0, -1.0],
            radar=[0.5, 0.6, 0.7, 0.8, 0.9],
        )
        rows = derive_daily_signals(**args)

        # 首日无前一日，跳过 → 4 行
        assert [r["date"] for r in rows] == dates[1:]

        # i=1 (09-15)
        r = rows[0]
        assert r["price"] == 11.0
        assert r["change_pct"] == 10.0
        assert r["decision_status"] == "above"
        assert r["bull_status"] == "above"
        assert r["orbit_status"] == "cross_up"          # 10.0<=10.2 且 11>10.2
        assert r["position_zone"] == "oversold"
        assert r["position_transition"] == "low_to_oversold"
        assert r["gs_status"] == "G"
        assert r["trend_status"] == "red_hold"          # cur>0 且前日红
        assert r["radar_wave"] == 0.6

        # i=2 (09-16)：G_zone、to_green、above2
        r = rows[1]
        assert r["decision_status"] == "below"          # 10.5 不大于 10.5
        assert r["orbit_status"] == "above2"
        assert r["position_transition"] == "oversold_to_low"
        assert r["gs_status"] == "G_zone"               # 最近信号是 G
        assert r["trend_status"] == "to_green"          # cur<=0 且前5日有红

        # i=3 (09-17)：cross_down、S
        r = rows[2]
        assert r["orbit_status"] == "cross_down"
        assert r["position_transition"] == "low_to_oversold"
        assert r["gs_status"] == "S"

        # i=4 (09-18)：S_zone
        r = rows[3]
        assert r["orbit_status"] == "cross_up"
        assert r["position_transition"] == "oversold_to_low"
        assert r["gs_status"] == "S_zone"

    def test_gs_zone_expires_after_60(self):
        # 造 62 根：bar0 发 G，之后 61 根无信号
        n = 62
        dates = [f"2026-01-{i+1:02d}" for i in range(n)]
        args = _make(dates, close=[10.0] * n,
                     gs_buy=[True] + [False] * (n - 1),
                     gs_sell=[False] * n)
        rows = derive_daily_signals(**args)
        # 第 1..60 根：G_zone；第 61 根起（距 G 超过60）：None
        assert rows[0]["gs_status"] == "G_zone"
        assert rows[59]["gs_status"] == "G_zone"        # 第 60 根（i=60）
        assert rows[60]["gs_status"] is None            # i=61，超 60

    def test_nan_indicator_means_no_status(self):
        import math
        dates = ["2026-09-14", "2026-09-15"]
        args = _make(dates, close=[10.0, 11.0],
                     dl=[math.nan, math.nan], orbit=[math.nan, math.nan])
        rows = derive_daily_signals(**args)
        assert rows[0]["decision_status"] is None
        assert rows[0]["orbit_status"] is None


class TestSignalHistoryStorage:
    """save_signal_history / load_signal_history 往返（重点验证 None 不变成 NaN）。"""

    def test_save_load_roundtrip(self, tmp_path, monkeypatch):
        from tradingagents.screener import cache as cache_mod
        monkeypatch.setattr(cache_mod, "_SIGNAL_HISTORY_DIR", tmp_path)

        rows = [
            {"date": "2026-09-16", "symbol": "600089.SH", "price": 11.0, "change_pct": 10.0,
             "position_zone": "low", "position_transition": "oversold_to_low",
             "decision_status": "above", "bull_status": "above", "orbit_status": "cross_up",
             "gs_status": "G", "trend_status": "red_hold", "radar_wave": 0.6},
            {"date": "2026-09-16", "symbol": "000001.SZ", "price": None, "change_pct": None,
             "position_zone": "oversold", "position_transition": None,
             "decision_status": None, "bull_status": None, "orbit_status": None,
             "gs_status": None, "trend_status": None, "radar_wave": None},
        ]
        cache_mod.save_signal_history(rows)

        loaded = cache_mod.load_signal_history("2026-09-16")
        assert loaded is not None
        by_symbol = {r["symbol"]: r for r in loaded}
        a = by_symbol["600089.SH"]
        assert a["price"] == 11.0
        assert a["change_pct"] == 10.0
        assert a["position_transition"] == "oversold_to_low"
        assert a["gs_status"] == "G"
        assert a["radar_wave"] == 0.6

        b = by_symbol["000001.SZ"]
        assert b["price"] is None
        assert b["change_pct"] is None
        assert b["position_transition"] is None
        assert b["gs_status"] is None
        assert b["radar_wave"] is None

        # 缺失日期返回 None
        assert cache_mod.load_signal_history("1999-01-01") is None


class TestIncrementalSlice:
    """增量切片核心正确性：切最后 65 根求出的末日信号 == 全量末日信号。"""

    LOOKBACK = 65

    def _full_and_sliced_last(self, args, max_days=1):
        full = derive_daily_signals(**args)
        n = len(args["dates"])
        s = max(0, n - (max_days + self.LOOKBACK))
        sliced = {k: v[s:] for k, v in args.items() if k != "symbol"}
        sliced["symbol"] = args["symbol"]
        sl = derive_daily_signals(**sliced)
        return full[-1], sl[-1]

    def test_last_day_equals_full_at_gs_boundary(self):
        # 200 根：bar0 发 G，bar139 发 S（距末日 60 根，正好在 gs 回溯边界内）
        n = 200
        dates = [f"2026-01-{i+1:02d}" for i in range(n)]
        gs_buy = [True] + [False] * (n - 1)
        gs_sell = [False] * n
        gs_sell[139] = True
        args = _make(
            dates,
            close=[10.0 + (i % 7) * 0.5 for i in range(n)],
            zones=["low"] * n, gs_buy=gs_buy, gs_sell=gs_sell,
            trend=[1.0 if i % 3 else -1.0 for i in range(n)],
            radar=[0.5 + (i % 5) * 0.1 for i in range(n)],
        )
        full_last, sliced_last = self._full_and_sliced_last(args)
        assert full_last == sliced_last
        assert full_last["gs_status"] == "S_zone"  # 距 S 正好 60 根 → S_zone

    def test_last_day_equals_full_varied(self):
        # 多空/zone 多变的序列，验证切片等价（不依赖具体数值）
        n = 150
        dates = [f"2026-02-{i+1:02d}" for i in range(n)]
        args = _make(
            dates,
            close=[10.0 + (i % 9) * 0.3 for i in range(n)],
            zones=["low" if i % 4 == 0 else ("oversold" if i % 4 == 1
                   else ("high" if i % 4 == 2 else "overbought")) for i in range(n)],
            gs_buy=[i % 20 == 0 for i in range(n)],
            gs_sell=[i % 23 == 0 for i in range(n)],
            trend=[1.0 if i % 2 else -1.0 for i in range(n)],
            radar=[0.5 + (i % 6) * 0.1 for i in range(n)],
        )
        full_last, sliced_last = self._full_and_sliced_last(args)
        assert full_last == sliced_last


class TestSignalHistoryIncremental:
    """save_signal_history 增量写：skip_existing 不重写 + signal_history_dates。"""

    def _row(self, date, symbol, price):
        return {"date": date, "symbol": symbol, "price": price, "change_pct": 10.0,
                "position_zone": "low", "position_transition": None, "decision_status": "above",
                "bull_status": "above", "orbit_status": "cross_up", "gs_status": "G",
                "trend_status": "red_hold", "radar_wave": 0.6}

    def test_skip_existing_does_not_overwrite(self, tmp_path, monkeypatch):
        from tradingagents.screener import cache as cache_mod
        monkeypatch.setattr(cache_mod, "_SIGNAL_HISTORY_DIR", tmp_path)

        cache_mod.save_signal_history([self._row("2026-09-16", "600089.SH", 11.0)])
        # 同日期第二次写（不同 price），skip_existing 应跳过 → 保留原值
        cache_mod.save_signal_history([self._row("2026-09-16", "600089.SH", 999.0)])
        assert cache_mod.load_signal_history("2026-09-16")[0]["price"] == 11.0

        # 新日期正常写入
        cache_mod.save_signal_history([self._row("2026-09-17", "600089.SH", 12.0)])
        assert cache_mod.load_signal_history("2026-09-17")[0]["price"] == 12.0
        assert cache_mod.signal_history_dates() == {"2026-09-16", "2026-09-17"}

    def test_force_rewrite_when_skip_disabled(self, tmp_path, monkeypatch):
        from tradingagents.screener import cache as cache_mod
        monkeypatch.setattr(cache_mod, "_SIGNAL_HISTORY_DIR", tmp_path)

        cache_mod.save_signal_history([self._row("2026-09-16", "600089.SH", 11.0)])
        cache_mod.save_signal_history([self._row("2026-09-16", "600089.SH", 999.0)], skip_existing=False)
        assert cache_mod.load_signal_history("2026-09-16")[0]["price"] == 999.0


class TestDeriveGsStates:
    """derive_gs_states — 抽出的 GS 状态机（日线 60 / 周线 26 共用）。"""

    def test_buy_then_zone(self):
        assert derive_gs_states(
            [True, False, False], [False, False, False]
        ) == ["G", "G_zone", "G_zone"]

    def test_sell_then_zone(self):
        assert derive_gs_states(
            [False, False, False, False], [False, False, True, False]
        ) == [None, None, "S", "S_zone"]

    def test_most_recent_signal_wins(self):
        assert derive_gs_states(
            [True, False, False, False, False],
            [False, False, False, True, False],
        ) == ["G", "G_zone", "G_zone", "S", "S_zone"]

    def test_zone_expires_after_lookback(self):
        # 26 周回溯：bar0 发 G，bar1..26 仍是 G_zone，bar27 过期归 None
        states = derive_gs_states([True] + [False] * 27, [False] * 28, zone_lookback=26)
        assert states[0] == "G"
        assert all(s == "G_zone" for s in states[1:27])
        assert states[27] is None

    def test_default_lookback_is_60(self):
        # 默认 60：bar0 G，bar60 仍是 G_zone，bar61 过期
        states = derive_gs_states([True] + [False] * 61, [False] * 62)
        assert states[60] == "G_zone"
        assert states[61] is None


class TestDeriveWeeklyGsStatus:
    """derive_weekly_gs_status — 周线 GS 状态按 ISO 周键返回。"""

    def test_maps_week_keys_to_states(self):
        result = derive_weekly_gs_status(
            ["2026-W01", "2026-W02", "2026-W03"],
            [True, False, False],
            [False, False, False],
        )
        assert result == {
            "2026-W01": "G",
            "2026-W02": "G_zone",
            "2026-W03": "G_zone",
        }

    def test_uses_26_week_lookback_by_default(self):
        # W01 发 G，W27（age 26）仍 G_zone，W28（age 27）过期 None
        weeks = [f"2026-W{i:02d}" for i in range(1, 29)]
        result = derive_weekly_gs_status(
            weeks, [True] + [False] * 27, [False] * 28
        )
        assert result["2026-W01"] == "G"
        assert result["2026-W27"] == "G_zone"
        assert result["2026-W28"] is None
