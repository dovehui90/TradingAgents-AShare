"""Tests for signal_history.derive_daily_signals — 全维度逐日信号抽取。"""

from tradingagents.indicators.signal_history import derive_daily_signals


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
