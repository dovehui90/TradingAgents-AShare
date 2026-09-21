"""Tests for position_index.get_position_transition — 单日档位转变判定。

偏低转超卖(low→oversold) / 超卖转偏低(oversold→low) 是选股神器「位置指标」
筛选维度新增的两个条件，本质是位置指标 zone 跨 20 分界线的单日转变。
"""

from tradingagents.indicators.position_index import get_position_transition


class TestPositionTransition:
    """单日转变（前一日 → 当日）判定。"""

    def test_low_to_oversold(self):
        # 偏低(20~40) → 超卖(<20)：跌破 20 线，继续走弱
        assert get_position_transition("low", "oversold") == "low_to_oversold"

    def test_oversold_to_low(self):
        # 超卖(<20) → 偏低(20~40)：上穿 20 线，超卖反弹
        assert get_position_transition("oversold", "low") == "oversold_to_low"

    def test_same_zone_no_transition(self):
        assert get_position_transition("low", "low") is None
        assert get_position_transition("oversold", "oversold") is None

    def test_other_zone_changes_no_transition(self):
        # 不跨 20 分界线的转变不算
        assert get_position_transition("neutral", "low") is None
        assert get_position_transition("low", "neutral") is None
        assert get_position_transition("high", "overbought") is None
        assert get_position_transition("overbought", "high") is None

    def test_direction_matters(self):
        # 反方向不命中（low→oversold 与 oversold→low 互斥）
        assert get_position_transition("oversold", "oversold") is None
        assert get_position_transition("low", "oversold") != "oversold_to_low"

    def test_unknown_zone_no_transition(self):
        assert get_position_transition("unknown", "oversold") is None
        assert get_position_transition("low", "unknown") is None
        assert get_position_transition(None, "low") is None
