"""Tests for trade_calendar.latest_cn_trading_day — 历史回看的日期对齐（含当日）。"""

from datetime import date

from tradingagents.dataflows import trade_calendar as tc


def _week(dates, monkeypatch):
    monkeypatch.setattr(tc, "_load_cn_trade_dates", lambda: (dates, set(dates)))


class TestLatestTradingDay:
    def test_inclusive_when_trading_day(self, monkeypatch):
        dates = [date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17), date(2026, 9, 18)]
        _week(dates, monkeypatch)
        # 交易日 → 返回当日（不是前一日）
        assert tc.latest_cn_trading_day("2026-09-18") == "2026-09-18"
        assert tc.latest_cn_trading_day("2026-09-15") == "2026-09-15"

    def test_rollback_on_weekend(self, monkeypatch):
        dates = [date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17), date(2026, 9, 18)]
        _week(dates, monkeypatch)
        # 周末 → 回退到周五
        assert tc.latest_cn_trading_day("2026-09-19") == "2026-09-18"
        assert tc.latest_cn_trading_day("2026-09-20") == "2026-09-18"

    def test_fallback_weekend_only(self, monkeypatch):
        monkeypatch.setattr(tc, "_load_cn_trade_dates", lambda: ([], set()))
        assert tc.latest_cn_trading_day("2026-09-18") == "2026-09-18"
        assert tc.latest_cn_trading_day("2026-09-20") == "2026-09-18"
