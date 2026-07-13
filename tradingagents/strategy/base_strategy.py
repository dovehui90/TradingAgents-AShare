"""
短线交易策略基类

所有短线策略继承此类，统一接口：信号评估 → 买点判定 → 交易记录 → 胜率学习。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
import json
from pathlib import Path


@dataclass
class SignalResult:
    """单次信号评估结果"""

    symbol: str
    date: str

    # --- 6个回调结束信号 ---
    signal_1_no_new_low: bool = False
    signal_2_above_ma5: bool = False
    signal_3_volume_shrink: bool = False
    signal_4_5d_positive: bool = False
    signal_5_near_high: bool = False
    signal_6_pattern_action: str = "neutral"  # "upgrade" / "veto" / "neutral"

    signal_count: int = 0
    ma5_deviation: float = 0.0
    is_overheated: bool = False

    # --- 硬过滤 ---
    ma60_slope_positive: bool = False
    above_ma10: bool = False
    volume_ratio: float = 0.0
    ret_5d: float = 0.0

    # --- 评分 ---
    entry_score: int = 0
    strategy_type: str = "none"  # "低吸" / "抄底" / "追涨" / "观望" / "减仓"

    # --- 辅助 ---
    close: float = 0.0
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    rsi_6: float = 0.0
    atr_14: float = 0.0
    volume_5d_mean: float = 0.0
    volume_3d_mean: float = 0.0
    volume_10d_mean: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def triggered_signals(self) -> list[int]:
        """返回触发的信号编号列表"""
        sigs = []
        if self.signal_1_no_new_low:
            sigs.append(1)
        if self.signal_2_above_ma5:
            sigs.append(2)
        if self.signal_3_volume_shrink:
            sigs.append(3)
        if self.signal_4_5d_positive:
            sigs.append(4)
        if self.signal_5_near_high:
            sigs.append(5)
        return sigs


@dataclass
class TradeOutcome:
    """单笔交易结果"""

    symbol: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    return_pct: float
    is_win: bool
    holding_days: int
    signals: SignalResult | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.signals:
            d["signals"] = self.signals.to_dict()
        return d


class BaseStrategy(ABC):
    """短线交易策略基类"""

    name: str = "base"
    version: str = "0.1.0"

    def __init__(self, config_path: str | None = None):
        self.config: dict = {}
        if config_path:
            self.config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        self._trades: list[TradeOutcome] = []

    # --- 子类必须实现 ---

    @abstractmethod
    def evaluate_signals(self, df, symbol: str = "") -> SignalResult:
        """输入K线DataFrame，输出信号评估结果"""
        ...

    # --- 基类提供 ---

    def is_valid_entry(self, signals: SignalResult) -> tuple[bool, str]:
        """判断是否为有效买点。子类可覆盖。"""
        if signals.is_overheated:
            return False, "过热不买"
        if not signals.ma60_slope_positive:
            return False, "MA60斜率≤0，中期趋势向下"
        if not signals.above_ma10:
            return False, "未站上MA10"
        if signals.volume_ratio < 0.9:
            return False, f"量比{signals.volume_ratio:.2f}<0.9，量能不足"
        if signals.ret_5d <= 0:
            return False, "近5日涨幅≤0，动能不足"
        if signals.strategy_type in ("观望", "减仓", "none"):
            return False, f"形态判定为{signals.strategy_type}"
        if signals.signal_count < 3:
            return False, f"回调结束信号仅{signals.signal_count}个，等待"
        if signals.signal_count >= 6:
            return False, "信号全触发，绝对过热"
        return True, "通过"

    def record_trade(self, outcome: TradeOutcome):
        self._trades.append(outcome)

    def win_rate(self) -> float:
        if not self._trades:
            return 0.0
        return sum(1 for t in self._trades if t.is_win) / len(self._trades)

    def trade_count(self) -> int:
        return len(self._trades)

    @classmethod
    def meta(cls) -> dict:
        return {"name": cls.name, "version": cls.version}
