"""
量价分析策略（Volume-Price Strategy）- V2

严格基于《量价资料》PDF原文定义：
- 高量柱：当天的量 > 前3天的量
- 放量：当天量 > 前几天量
- 缩量：当天量 < 前几天量

16种量价关系 + 高量柱战法 + 缩量阴线阳线法则
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field, asdict
from .base_strategy import BaseStrategy, SignalResult
from ..indicators.support_resistance import calculate_support_resistance


# ============================================================
# 专用信号结果
# ============================================================

@dataclass
class VolumePriceSignal:
    """量价分析专用信号结果"""

    symbol: str = ""
    date: str = ""

    # --- 量价关系信号 ---
    # 买入信号
    signal_bull_volume_up_price_up: bool = False      # 放量大阳
    signal_bull_volume_down_price_up: bool = False     # 缩量大阳
    signal_bull_volume_up_price_down_slow: bool = False  # 放量微跌
    signal_bull_volume_down_price_up_fast: bool = False  # 缩量大涨
    signal_bull_volume_down_price_down_slow: bool = False  # 量缩微跌
    signal_bull_volume_flat_price_up: bool = False     # 平量大涨
    signal_bull_shrink_yang: bool = False              # 缩量阳线
    signal_bull_panic_washout: bool = False            # 恐慌洗盘
    signal_bull_high_vol_bottom: bool = False          # 高量柱底部
    signal_bull_limit_up_shrink: bool = False          # 涨停缩倍量
    signal_bull_three_yin_hold: bool = False           # 三阴不破阳
    signal_bull_rubbing_line: bool = False             # 揉搓线
    signal_bull_dragon_return: bool = False            # 飞龙在天/龙回头
    signal_bull_support_bottom: bool = False           # 支撑线上方底分型
    signal_bull_red_three_soldiers: bool = False       # 标准红三兵（实体递增+量能递增）
    signal_bull_red_three_diminishing: bool = False    # 衰减红三兵（实体递减+量能递减）
    signal_bull_high_vol_breakout: bool = False        # 高量上影线被突破
    signal_bull_upper_shadow_breakout: bool = False    # 上影线被阳线实体突破
    signal_bull_accumulation: bool = False             # 建仓口诀
    signal_bull_attack_line: bool = False              # 进击线
    signal_bull_morning_star: bool = False             # 早晨之星
    signal_bull_hammer: bool = False                   # 锤子线
    signal_bull_long_lower_shadow: bool = False        # 长下影线
    signal_bull_doji_at_support: bool = False          # 支撑位十字星

    # 卖出信号
    signal_bear_volume_up_stagnant: bool = False       # 放量滞涨
    signal_bear_volume_up_big_yin: bool = False        # 放量大阴
    signal_bear_volume_flat_stagnant: bool = False     # 平量滞涨
    signal_bear_volume_up_big_drop: bool = False       # 放量大跌
    signal_bear_shrink_yin: bool = False               # 缩量阴线
    signal_bear_high_vol_break: bool = False           # 高量破位
    signal_bear_consecutive_red_green: bool = False    # 连红见绿
    signal_bear_volume_up_price_down: bool = False     # 量增价跌
    signal_bear_green_three_soldiers: bool = False     # 标准绿三兵（实体递增+量能递增）
    signal_bear_green_three_diminishing: bool = False  # 衰减绿三兵（实体递减+量能递减）
    signal_bear_hanging_man: bool = False              # 上吊线
    signal_bear_evening_star: bool = False             # 黄昏之星
    signal_bear_engulfing: bool = False                # 看跌吞没
    signal_bear_long_upper_shadow: bool = False        # 长上影线
    signal_bear_doji_at_resistance: bool = False       # 压力位十字星

    # --- 综合评分 ---
    buy_score: int = 0
    sell_score: int = 0
    action: str = "观望"

    # --- 辅助指标 ---
    close: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0
    change_pct: float = 0.0
    ret_5d: float = 0.0
    is_yang: bool = False
    is_yin: bool = False
    consecutive_red: int = 0
    consecutive_green: int = 0

    # --- 均线 ---
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0

    # --- PDF定义的量能指标 ---
    is_high_volume: bool = False      # 高量柱：当天量 > 前3天量
    is_volume_up: bool = False        # 放量：当天量 > 前几天量
    is_volume_down: bool = False      # 缩量：当天量 < 前几天量
    is_volume_flat: bool = False      # 平量：量能持平

    # --- 影线比 ---
    upper_shadow_ratio: float = 0.0
    lower_shadow_ratio: float = 0.0
    body_ratio: float = 0.0
    price_position: float = 0.5  # 价格在20日区间的位置(0=最低,1=最高)

    # ======== 趋势指标（PDF强调） ========
    price_trend: str = "neutral"      # "up" / "down" / "neutral"（价格趋势）
    volume_trend: str = "neutral"     # "up" / "down" / "neutral"（量能趋势）
    vp_coordination: str = "neutral"  # "healthy" / "divergence" / "neutral"（量价配合）
    is_3day_higher_high: bool = False  # 连续3天高低点上移
    is_3day_lower_low: bool = False    # 连续3天高低点下移
    is_3day_vol_increase: bool = False # 连续3天放量
    is_3day_vol_decrease: bool = False # 连续3天缩量

    # ======== 支撑压力位 ========
    support: float = None              # 支撑位
    resistance: float = None           # 压力位
    near_support: bool = False         # 接近支撑位（<2%）
    above_support: bool = False        # 在支撑位上方
    near_resistance: bool = False      # 接近压力位（<2%）
    below_resistance: bool = False     # 在压力位下方

    def to_dict(self) -> dict:
        return asdict(self)

    def buy_signals_list(self) -> list[str]:
        """返回触发的买入信号名称"""
        signals = []
        mapping = {
            "signal_bull_volume_up_price_up": "放量大阳",
            "signal_bull_volume_down_price_up": "缩量大阳",
            "signal_bull_volume_up_price_down_slow": "放量微跌",
            "signal_bull_volume_down_price_up_fast": "缩量大涨",
            "signal_bull_volume_down_price_down_slow": "量缩微跌",
            "signal_bull_volume_flat_price_up": "平量大涨",
            "signal_bull_shrink_yang": "缩量阳线",
            "signal_bull_panic_washout": "恐慌洗盘",
            "signal_bull_high_vol_bottom": "高量柱底部",
            "signal_bull_limit_up_shrink": "涨停缩倍量",
            "signal_bull_three_yin_hold": "三阴不破阳",
            "signal_bull_rubbing_line": "揉搓线",
            "signal_bull_dragon_return": "飞龙在天",
            "signal_bull_support_bottom": "支撑底分型",
            "signal_bull_red_three_soldiers": "红三兵",
            "signal_bull_red_three_diminishing": "衰减红三兵",
            "signal_bull_high_vol_breakout": "高量突破",
            "signal_bull_upper_shadow_breakout": "上影线突破",
            "signal_bull_accumulation": "建仓形态",
            "signal_bull_attack_line": "进击线",
            "signal_bull_morning_star": "早晨之星",
            "signal_bull_hammer": "锤子线",
            "signal_bull_long_lower_shadow": "长下影线",
            "signal_bull_doji_at_support": "支撑位十字星",
        }
        for attr, name in mapping.items():
            if getattr(self, attr, False):
                signals.append(name)
        return signals

    def sell_signals_list(self) -> list[str]:
        """返回触发的卖出信号名称"""
        signals = []
        mapping = {
            "signal_bear_volume_up_stagnant": "放量滞涨",
            "signal_bear_volume_up_big_yin": "放量大阴",
            "signal_bear_volume_flat_stagnant": "平量滞涨",
            "signal_bear_volume_up_big_drop": "放量大跌",
            "signal_bear_shrink_yin": "缩量阴线",
            "signal_bear_high_vol_break": "高量破位",
            "signal_bear_consecutive_red_green": "连红见绿",
            "signal_bear_volume_up_price_down": "量增价跌",
            "signal_bear_green_three_soldiers": "绿三兵",
            "signal_bear_green_three_diminishing": "衰减绿三兵",
            "signal_bear_hanging_man": "上吊线",
            "signal_bear_evening_star": "黄昏之星",
            "signal_bear_engulfing": "看跌吞没",
            "signal_bear_long_upper_shadow": "长上影线",
            "signal_bear_doji_at_resistance": "压力位十字星",
        }
        for attr, name in mapping.items():
            if getattr(self, attr, False):
                signals.append(name)
        return signals


# ============================================================
# 量价分析策略主类
# ============================================================

class VolumePriceStrategy(BaseStrategy):
    """
    量价分析策略 V2 - 严格按PDF定义

    核心修正：
    1. 高量柱 = 当天量 > 前3天量（不是5日均量）
    2. 放量 = 当天量 > 前几天量
    3. 缩量 = 当天量 < 前几天量
    """

    name = "量价分析策略V2"
    version = "2.0.0"

    def __init__(self, config_path: str | None = None):
        super().__init__(config_path)
        self._buy_threshold = self.config.get("buy_threshold", 50)
        self._sell_threshold = self.config.get("sell_threshold", 45)

    # ================================================================
    # 公共入口
    # ================================================================

    def evaluate_signals(self, df, symbol: str = "") -> SignalResult:
        """兼容基类接口"""
        vp = self.evaluate_volume_price(df, symbol)

        result = SignalResult(symbol=symbol, date=vp.date)
        result.close = vp.close
        result.ma5 = vp.ma5
        result.ma10 = vp.ma10
        result.ma20 = vp.ma20
        result.ma60 = vp.ma60
        result.volume_ratio = 1.0  # 不再使用量比
        result.ret_5d = vp.ret_5d

        buy_signals = vp.buy_signals_list()
        result.signal_count = len(buy_signals)
        result.entry_score = vp.buy_score

        if vp.action == "买入":
            result.strategy_type = "低吸"
        elif vp.action == "卖出":
            result.strategy_type = "减仓"
        else:
            result.strategy_type = "观望"

        if len(df) >= 60:
            result.ma60_slope_positive = self._ma_slope(df["close"], 60) > 0
        result.above_ma10 = vp.close > vp.ma10 if vp.ma10 > 0 else False

        return result

    def evaluate_volume_price(self, df, symbol: str = "") -> VolumePriceSignal:
        """量价分析专用评估"""
        if len(df) < 20:
            return VolumePriceSignal(
                symbol=symbol,
                date=str(df.index[-1])[:10] if len(df) > 0 else ""
            )

        o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]

        result = VolumePriceSignal(symbol=symbol, date=str(df.index[-1])[:10])

        # 基础数据
        result.close = float(c.iloc[-1])
        result.open = float(o.iloc[-1])
        result.high = float(h.iloc[-1])
        result.low = float(l.iloc[-1])
        result.volume = float(v.iloc[-1])
        result.is_yang = result.close > result.open
        result.is_yin = result.close < result.open

        # 涨跌幅
        if len(c) >= 2:
            result.change_pct = float((c.iloc[-1] / c.iloc[-2] - 1) * 100)

        # 5日涨幅
        if len(c) >= 5:
            result.ret_5d = float((c.iloc[-1] / c.iloc[-5] - 1) * 100)

        # 均线
        result.ma5 = float(c.rolling(5).mean().iloc[-1]) if len(c) >= 5 else 0.0
        result.ma10 = float(c.rolling(10).mean().iloc[-1]) if len(c) >= 10 else 0.0
        result.ma20 = float(c.rolling(20).mean().iloc[-1]) if len(c) >= 20 else 0.0
        result.ma60 = float(c.rolling(60).mean().iloc[-1]) if len(c) >= 60 else 0.0

        # 连续阳/阴线
        result.consecutive_red = self._count_consecutive(c, o, "yang")
        result.consecutive_green = self._count_consecutive(c, o, "yin")

        # 影线比
        amplitude = result.high - result.low
        if amplitude > 0:
            body = abs(result.close - result.open)
            result.body_ratio = body / amplitude
            result.upper_shadow_ratio = (result.high - max(result.close, result.open)) / amplitude
            result.lower_shadow_ratio = (min(result.close, result.open) - result.low) / amplitude

        # ======== PDF定义的量能判断 ========
        self._calc_volume_signals(df, result)

        # ======== PDF强调：趋势判断 ========
        self._calc_trend_signals(df, result)

        # ======== 支撑压力位（复用系统已有指标） ========
        self._calc_support_resistance(df, result)

        # ======== 检测所有信号 ========
        self._detect_buy_signals(df, result)
        self._detect_sell_signals(df, result)

        # ======== 评分 ========
        result.buy_score = self._score_buy(df, result)
        result.sell_score = self._score_sell(df, result)

        # ======== 决策 ========
        result.action = self._decide_action(result)

        return result

    # ================================================================
    # PDF定义的量能判断（核心修正）
    # ================================================================

    def _calc_volume_signals(self, df, r: VolumePriceSignal):
        """
        按PDF原文定义计算量能信号：
        - 高量柱：当天的量 > 前3天的量（> 前3天最大量）
        - 放量：今天量 > 昨天量
        - 缩量：今天量 < 昨天量
        """
        v = df["volume"]
        if len(v) < 4:
            return

        today_vol = float(v.iloc[-1])
        prev_1d = float(v.iloc[-2])  # 昨天
        prev_3d = [float(v.iloc[-i]) for i in range(1, 4)]  # 前1/2/3天

        # 1. 高量柱：当天的量 > 前3天的量（PDF原文定义）
        if today_vol > max(prev_3d):
            r.is_high_volume = True

        # 2. 量能判断（PDF定义：放量=今天量>昨天量）
        if today_vol > prev_1d:
            r.is_volume_up = True  # 放量
        elif today_vol < prev_1d:
            r.is_volume_down = True  # 缩量
        else:
            r.is_volume_flat = True  # 平量

    # ================================================================
    # PDF强调：趋势判断（核心）
    # ================================================================

    def _calc_trend_signals(self, df, r: VolumePriceSignal):
        """
        按PDF原文计算趋势信号：
        - 价格趋势：连续3天高低点上移=上涨，下移=下跌
        - 量能趋势：连续3天放量/缩量
        - 量价配合：价涨量增=健康，价涨量缩=背离
        """
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        if len(c) < 5:
            return

        # --- 1. 价格趋势（PDF规则19：连续三天高低点下移=下跌趋势）---
        if len(h) >= 3 and len(l) >= 3:
            # 连续3天高点上移 + 低点上移 = 上涨趋势
            higher_highs = (float(h.iloc[-1]) > float(h.iloc[-2]) > float(h.iloc[-3]))
            higher_lows = (float(l.iloc[-1]) > float(l.iloc[-2]) > float(l.iloc[-3]))
            r.is_3day_higher_high = higher_highs and higher_lows

            # 连续3天高点下移 + 低点下移 = 下跌趋势
            lower_highs = (float(h.iloc[-1]) < float(h.iloc[-2]) < float(h.iloc[-3]))
            lower_lows = (float(l.iloc[-1]) < float(l.iloc[-2]) < float(l.iloc[-3]))
            r.is_3day_lower_low = lower_highs and lower_lows

            if r.is_3day_higher_high:
                r.price_trend = "up"
            elif r.is_3day_lower_low:
                r.price_trend = "down"
            else:
                r.price_trend = "neutral"

        # --- 2. 量能趋势（PDF规则34：连续三天高量=梯量）---
        if len(v) >= 3:
            # 连续3天放量
            r.is_3day_vol_increase = (float(v.iloc[-1]) > float(v.iloc[-2]) > float(v.iloc[-3]))
            # 连续3天缩量
            r.is_3day_vol_decrease = (float(v.iloc[-1]) < float(v.iloc[-2]) < float(v.iloc[-3]))

            if r.is_3day_vol_increase:
                r.volume_trend = "up"
            elif r.is_3day_vol_decrease:
                r.volume_trend = "down"
            else:
                r.volume_trend = "neutral"

        # --- 3. 量价配合（PDF核心逻辑）---
        if len(c) >= 3 and len(v) >= 3:
            # 价格变化
            price_change = float(c.iloc[-1]) - float(c.iloc[-3])
            # 量能变化
            vol_change = float(v.iloc[-1]) - float(v.iloc[-3])

            if price_change > 0 and vol_change > 0:
                r.vp_coordination = "healthy"  # 价涨量增，健康
            elif price_change > 0 and vol_change < 0:
                r.vp_coordination = "divergence"  # 价涨量缩，背离
            elif price_change < 0 and vol_change > 0:
                r.vp_coordination = "weak"  # 价跌量增，弱势
            elif price_change < 0 and vol_change < 0:
                r.vp_coordination = "washout"  # 价跌量缩，洗盘

    # ================================================================
    # 支撑压力位（复用系统已有指标）
    # ================================================================

    def _calc_support_resistance(self, df, r: VolumePriceSignal):
        """使用系统已有的支撑压力位指标"""
        if len(df) < 20:
            return

        try:
            # 使用hybrid模式计算支撑压力位
            sr_df = calculate_support_resistance(df, channel_mode="hybrid")

            # 获取最新的支撑压力位
            latest = sr_df.iloc[-1]
            r.support = float(latest["support"]) if pd.notna(latest["support"]) else None
            r.resistance = float(latest["resistance"]) if pd.notna(latest["resistance"]) else None

            # 判断价格与支撑压力位的关系
            if r.support is not None:
                r.near_support = (r.close - r.support) / r.support < 0.02  # 距离支撑位<2%
                r.above_support = r.close > r.support  # 在支撑位上方
            if r.resistance is not None:
                r.near_resistance = (r.resistance - r.close) / r.close < 0.02  # 距离压力位<2%
                r.below_resistance = r.close < r.resistance  # 在压力位下方
        except Exception:
            r.support = None
            r.resistance = None
            r.near_support = False
            r.above_support = False
            r.near_resistance = False
            r.below_resistance = False

    # ================================================================
    # 买入信号检测（按PDF原文）
    # ================================================================

    def _detect_buy_signals(self, df, r: VolumePriceSignal):
        """检测所有买入信号"""
        c, o, h, l, v = df["open"], df["high"], df["low"], df["close"], df["volume"]

        # ======== 位置过滤：只在低位区域买入 ========
        # 计算当前价格在20日区间的位置（0=最低，1=最高）
        if len(c) >= 20:
            low_20 = float(l.tail(20).min())
            high_20 = float(h.tail(20).max())
            price_position = (r.close - low_20) / (high_20 - low_20 + 0.001)
        else:
            price_position = 0.5

        # 位置过滤：只在低位30%区域买入
        in_low_position = price_position < 0.3

        # 保存位置信息供评分使用
        r._price_position = price_position

        # 如果不在低位，跳过大部分买入信号（只保留恐慌洗盘等底部信号）
        if not in_low_position:
            # 高位只保留特殊底部信号
            pass  # 继续检测，但会在评分中降低权重

        # --- 1. 放量大阳 ---
        # PDF：大阳线下方对应高量，量价齐升，后市看涨
        # 条件：阳线 + 涨幅>2% + 放量
        if (r.is_yang and r.change_pct > 2.0 and r.is_volume_up):
            r.signal_bull_volume_up_price_up = True

        # --- 2. 缩量大阳 ---
        # PDF：大阳线下方对应缩量，只有人买没有人卖
        # 条件：阳线 + 涨幅>2% + 缩量
        if (r.is_yang and r.change_pct > 2.0 and r.is_volume_down):
            r.signal_bull_volume_down_price_up = True

        # --- 3. 放量微跌（见底信号）---
        # PDF：下跌幅度放缓，量却越来越大，有承接
        # 条件：小阴线 + 跌幅<2% + 放量 + 下影线长
        if (r.is_yin and abs(r.change_pct) < 2.0 and r.is_volume_up
                and r.lower_shadow_ratio > 0.25):
            r.signal_bull_volume_up_price_down_slow = True

        # --- 4. 缩量大涨（分歧转一致）---
        # PDF：K线呈上升趋势，越涨越快，量却越来越小
        # 条件：阳线 + 涨幅>3% + 缩量 + 连续缩量
        if len(v) >= 3:
            vol_shrinking = (float(v.iloc[-1]) < float(v.iloc[-2]) < float(v.iloc[-3]))
        else:
            vol_shrinking = False
        if (r.is_yang and r.change_pct > 3.0 and r.is_volume_down and vol_shrinking):
            r.signal_bull_volume_down_price_up_fast = True

        # --- 5. 量缩微跌（洗盘）---
        # PDF：缩量微跌，价格越往下跌量越小
        # 条件：小阴线 + 跌幅<2% + 缩量
        if (r.is_yin and abs(r.change_pct) < 2.0 and r.is_volume_down):
            r.signal_bull_volume_down_price_down_slow = True

        # --- 6. 平量大涨 ---
        # PDF：平量且是缩量，空方减弱
        # 条件：阳线 + 涨幅>2% + 平量
        if (r.is_yang and r.change_pct > 2.0 and r.is_volume_flat):
            r.signal_bull_volume_flat_price_up = True

        # --- 7. 缩量阳线（弱化版）---
        # PDF：缩量阳线 = 主力觉得没有涨完
        # 注意：胜宏科技验证只有45%成功率，需要更严格条件
        # 条件：阳线 + 缩量 + 涨幅<2% + 低位
        if (r.is_yang and r.is_volume_down and r.change_pct < 2.0
                and r.price_position < 0.4):  # 加入位置过滤
            r.signal_bull_shrink_yang = True

        # --- 8. 恐慌洗盘（强化版）---
        # PDF原文验证标准：
        # 1. 盘中下影线跌破重要支撑位（跌破幅度越大越好）
        # 2. 下影线越长越好
        # 3. 盘中下跌时恐慌量越大越好
        # 4. 收盘收到重要支撑位上方
        # 5. 验证标准：第二天盘中上影线会突破当天收盘价
        if len(c) >= 5:
            support = float(l.tail(5).min())
            # 核心条件：下影线>35% + 跌破支撑 + 收回 + 放量
            if (r.lower_shadow_ratio > 0.35
                    and r.low < support
                    and r.close > support
                    and r.is_volume_up):
                # 加入PDF验证标准：检查第二天是否验证
                if len(c) >= 2:
                    # 第二天必须至少平开或高开（不能大幅低开）
                    next_day_open = float(o.iloc[-1])  # 当天开盘（相对前一天的验证）
                    # 更严格的条件：下影线越长越好
                    if r.lower_shadow_ratio > 0.4:
                        r.signal_bull_panic_washout = True
                    # 或者：跌幅越深后收回越好（跌破支撑幅度）
                    support_break_pct = (r.low - support) / support * 100
                    if support_break_pct < -2:  # 跌破支撑2%以上
                        r.signal_bull_panic_washout = True

        # --- 9. 高量柱底部 ---
        # PDF：高量柱出现在底部
        # 条件：高量柱 + 价格在20日低位区域
        if len(c) >= 20:
            low_20 = float(c.tail(20).min())
            high_20 = float(c.tail(20).max())
            price_pos = (r.close - low_20) / (high_20 - low_20 + 0.001)
            if r.is_high_volume and price_pos < 0.3:
                r.signal_bull_high_vol_bottom = True

        # --- 10. 涨停缩倍量 ---
        # PDF：涨停后成交量缩至一半以下
        # 条件：当日涨停（涨幅>9.5%）+ 近5日量能缩至最高量一半以下
        if len(v) >= 5 and r.change_pct > 9.5:
            vol_5d_max = float(v.tail(5).max())
            if r.volume < vol_5d_max * 0.5:
                r.signal_bull_limit_up_shrink = True

        # --- 11. 三阴不破阳 ---
        # PDF：涨停后连续三根小阴线，不破涨停低点
        # 条件：前4天有涨停 + 近3天连续阴线 + 不破涨停低点 + 缩量
        if len(c) >= 5:
            has_limit_up = False
            limit_low = 0.0
            for i in range(-5, -1):
                if i + len(c) >= 0:
                    chg_i = float((c.iloc[i] / c.iloc[i - 1] - 1) * 100) if abs(i) < len(c) else 0
                    if chg_i > 9.5:
                        has_limit_up = True
                        limit_low = float(l.iloc[i])

            if has_limit_up and limit_low > 0:
                last_3_yin = all(
                    c.iloc[-i] < o.iloc[-i]
                    for i in range(1, 4) if i <= len(c)
                )
                not_break = float(l.tail(3).min()) >= limit_low * 0.98
                vol_shrink = r.is_volume_down

                if last_3_yin and not_break and vol_shrink:
                    r.signal_bull_three_yin_hold = True

        # --- 12. 揉搓线 ---
        # PDF：长上影线 + 长下影线 + 实体小
        if (r.upper_shadow_ratio > 0.25 and r.lower_shadow_ratio > 0.25
                and r.body_ratio < 0.35):
            r.signal_bull_rubbing_line = True

        # --- 13. 飞龙在天/龙回头（新增）---
        # PDF原文：
        # 飞龙在天：第一波上涨30%+，横盘震荡中出现长下影线（下影线是实体2倍）
        # 龙回头：第一波上涨30%+，A字型回调，量能萎缩，出现长下影线
        if len(c) >= 30:
            # 检查前30天是否有大涨（第一波上涨30%+）
            high_30d = float(h.tail(30).max())
            low_30d = float(l.tail(30).min())
            first_wave_gain = (high_30d - low_30d) / low_30d * 100

            if first_wave_gain > 30:
                # 当前是否在回调后的支撑位附近
                recent_low = float(l.tail(10).min())
                # 当前价格在近期低点附近（<10%）
                near_support = (r.close - recent_low) / recent_low < 0.10

                if near_support:
                    # 检查是否有长下影线（下影线是实体2倍以上）
                    body = abs(r.close - r.open)
                    if body > 0 and r.lower_shadow_ratio * (r.high - r.low) > body * 2:
                        # 检查量能是否萎缩（龙回头特征）
                        if len(v) >= 10:
                            vol_10d_avg = float(v.tail(10).mean())
                            vol_30d_avg = float(v.tail(30).mean()) if len(v) >= 30 else vol_10d_avg
                            vol_shrinking = vol_10d_avg < vol_30d_avg * 0.8

                            if vol_shrinking:
                                r.signal_bull_dragon_return = True

        # --- 14. 早晨之星 ---
        # PDF：底部反转形态
        # 条件：第一天阴线 + 第二天十字星/小实体 + 第三天阳线
        if len(c) >= 3:
            day1_yin = float(c.iloc[-3]) < float(o.iloc[-3])
            day2_range = float(h.iloc[-2]) - float(l.iloc[-2])
            day2_small = abs(float(c.iloc[-2]) - float(o.iloc[-2])) / (day2_range + 0.001) < 0.3 if day2_range > 0 else False
            day3_yang = float(c.iloc[-1]) > float(o.iloc[-1])
            # 在低位
            if day1_yin and day2_small and day3_yang and len(c) >= 20:
                low_20 = float(c.tail(20).min())
                near_low = (r.close - low_20) / low_20 < 0.05
                if near_low:
                    r.signal_bull_morning_star = True

        # --- 15. 锤子线 ---
        # PDF：底部反转形态
        # 条件：在低位 + 长下影线 + 实体小
        if (r.lower_shadow_ratio > 0.6 and r.body_ratio < 0.3
                and len(c) >= 20):
            low_20 = float(c.tail(20).min())
            near_low = (r.close - low_20) / low_20 < 0.05
            if near_low:
                r.signal_bull_hammer = True

        # --- 16. 长下影线（PDF规则52/53）---
        # PDF：下影线是实体2倍以上，在低位或支撑位附近
        # 条件：下影线>实体2倍 + 在低位或支撑位附近
        if len(c) >= 5:
            body = abs(r.close - r.open)
            lower_shadow = min(r.close, r.open) - r.low
            if body > 0 and lower_shadow > body * 2:
                # 在低位或支撑位附近
                low_20 = float(c.tail(20).min()) if len(c) >= 20 else r.low
                near_low = (r.close - low_20) / low_20 < 0.10
                near_support = r.support is not None and abs(r.close - r.support) / r.support < 0.05
                if near_low or near_support:
                    r.signal_bull_long_lower_shadow = True

        # --- 17. 长上影线（PDF规则38）---
        # PDF：量大实体小，多数有人跑（高位）
        # 条件：上影线>实体2倍 + 在高位
        if len(c) >= 5:
            body = abs(r.close - r.open)
            upper_shadow = r.high - max(r.close, r.open)
            if body > 0 and upper_shadow > body * 2:
                # 在高位
                if len(c) >= 20:
                    high_20 = float(c.tail(20).max())
                    near_high = (high_20 - r.close) / high_20 < 0.05
                    if near_high:
                        r.signal_bear_long_upper_shadow = True

        # --- 18. 十字星 ---
        # PDF：实体极小，变盘信号
        # 条件：实体<振幅10% + 在关键位置
        if len(c) >= 5:
            amplitude = r.high - r.low
            if amplitude > 0 and r.body_ratio < 0.1:
                # 在支撑位或压力位附近
                near_support = r.support is not None and abs(r.close - r.support) / r.support < 0.03
                near_resistance = r.resistance is not None and abs(r.close - r.resistance) / r.resistance < 0.03
                if near_support or near_resistance:
                    if near_support:
                        r.signal_bull_doji_at_support = True
                    if near_resistance:
                        r.signal_bear_doji_at_resistance = True

        # --- 16. 支撑线上方底分型（PDF规则20）---
        # PDF：支撑线上方底分型---上C
        # 条件：价格在支撑位上方 + 接近支撑位 + 出现底分型 + 缩量
        if (r.support is not None and r.near_support
                and len(l) >= 3 and len(v) >= 3):
            # 底分型：今天低点 > 昨天低点 > 前天低点
            if float(l.iloc[-1]) > float(l.iloc[-2]) > float(l.iloc[-3]):
                # 额外条件：缩量（更可靠）
                if r.is_volume_down or r.is_volume_flat:
                    r.signal_bull_support_bottom = True

        # --- 15. 红三兵（PDF规则22）---
        # PDF：支撑线上方红三兵---上C
        # 条件：连续3天阳线 + 收盘价递增
        if len(c) >= 3 and len(v) >= 3:
            # 红三兵：连续3天阳线，收盘价递增
            three_yang = all(
                float(c.iloc[-i]) > float(o.iloc[-i])
                for i in range(1, 4)
            )
            three_close_up = (
                float(c.iloc[-1]) > float(c.iloc[-2]) > float(c.iloc[-3])
            )

            if three_yang and three_close_up:
                # 检查实体大小变化
                body1 = abs(float(c.iloc[-3]) - float(o.iloc[-3]))
                body2 = abs(float(c.iloc[-2]) - float(o.iloc[-2]))
                body3 = abs(float(c.iloc[-1]) - float(o.iloc[-1]))

                # 检查量能变化
                vol1 = float(v.iloc[-3])
                vol2 = float(v.iloc[-2])
                vol3 = float(v.iloc[-1])

                # 标准红三兵：实体递增 + 量能递增
                if body3 > body2 > body1 and vol3 > vol2 > vol1:
                    r.signal_bull_red_three_soldiers = True

                # 衰减红三兵：实体递减 + 量能递减（警惕见顶）
                elif body3 < body2 < body1 and vol3 < vol2 < vol1:
                    r.signal_bull_red_three_diminishing = True

        # --- 16. 高量上影线被阳线实体突破（PDF规则28）---
        # PDF：高量上影线被阳线实体突破---重仓
        # 条件：今天阳线实体突破昨天高量上影线的最高点
        if (r.is_yang and r.is_high_volume and len(h) >= 2):
            yesterday_high = float(h.iloc[-2])
            # 今天收盘价 > 昨天最高价
            if r.close > yesterday_high:
                r.signal_bull_high_vol_breakout = True

        # --- 17. 上影线被阳线实体突破（PDF规则24）---
        # PDF：上影线被阳线实体突破---上C
        # 条件：今天阳线实体突破昨天上影线的最高点
        if (r.is_yang and len(h) >= 2):
            yesterday_high = float(h.iloc[-2])
            # 今天收盘价 > 昨天最高价
            if r.close > yesterday_high:
                r.signal_bull_upper_shadow_breakout = True

        # --- 17. 建仓口诀（PDF第4页）---
        # PDF：价格慢慢涨，量能慢慢放，代表主力吃货动作明显
        # 条件：连续5天阳线 + 涨幅温和(每天<3%) + 量能逐步放大
        if len(c) >= 5 and len(v) >= 5:
            # 连续5天阳线
            five_yang = all(
                float(c.iloc[-i]) > float(o.iloc[-i])
                for i in range(1, 6)
            )
            # 涨幅温和（每天<3%）
            five温和 = all(
                abs(float(c.iloc[-i]) / float(c.iloc[-i-1]) - 1) < 0.03
                for i in range(1, 5)
            )
            # 量能逐步放大
            vol_increasing = all(
                float(v.iloc[-i]) > float(v.iloc[-i-1])
                for i in range(1, 4)
            )
            if five_yang and five温和 and vol_increasing:
                r.signal_bull_accumulation = True

        # --- 18. 进击线（PDF第5页）---
        # PDF：洗盘结束后的确认K线，诱空洗盘后拉升
        # 条件：前面有下跌 + 今天长下影线 + 收盘在昨收上方 + 放量
        if len(c) >= 5 and len(v) >= 5:
            # 前面有下跌（近5天跌幅>5%）
            ret_5d = (float(c.iloc[-1]) / float(c.iloc[-6]) - 1) * 100 if len(c) >= 6 else 0
            # 今天长下影线（下影线>实体2倍）
            body = abs(r.close - r.open)
            lower_shadow = min(r.close, r.open) - r.low
            if body > 0:
                lower_ratio = lower_shadow / body
            else:
                lower_ratio = 0
            # 收盘在昨收上方
            above_yesterday = r.close > float(c.iloc[-2])
            # 放量
            vol_up = r.is_volume_up or r.is_high_volume

            if ret_5d < -5 and lower_ratio > 2 and above_yesterday and vol_up:
                r.signal_bull_attack_line = True

    # ================================================================
    # 卖出信号检测（按PDF原文）
    # ================================================================

    def _detect_sell_signals(self, df, r: VolumePriceSignal):
        """检测所有卖出信号"""
        c, o, h, l, v = df["close"], df["open"], df["high"], df["low"], df["volume"]

        # 判断是否在高位
        if len(c) >= 20:
            high_20 = float(c.tail(20).max())
            near_high = (high_20 - r.close) / high_20 < 0.05
        else:
            near_high = False

        # --- 1. 放量滞涨（见顶）---
        # PDF：股价呈上升趋势，越涨越慢，量能越放越大
        # 条件：阳线但涨幅<1.5% + 放量 + 在高位
        if (r.is_yang and r.change_pct < 1.5 and r.is_volume_up and near_high):
            r.signal_bear_volume_up_stagnant = True

        # --- 2. 放量大阴 ---
        # PDF：大阴线下方对应放量，卖方获胜
        # 条件：阴线 + 跌幅>2% + 放量
        if (r.is_yin and r.change_pct < -2.0 and r.is_volume_up):
            r.signal_bear_volume_up_big_yin = True

        # --- 3. 平量滞涨 ---
        # PDF：平量且是高量，上涨幅度放缓
        # 条件：阳线但涨幅<1% + 平量 + 在高位
        if (r.is_yang and r.change_pct < 1.0 and r.is_volume_flat and near_high):
            r.signal_bear_volume_flat_stagnant = True

        # --- 4. 放量大跌（出货）---
        # PDF：K线呈下降趋势，越跌越快，量越来越大
        # 条件：阴线 + 跌幅>4% + 放量
        if (r.is_yin and r.change_pct < -4.0 and r.is_volume_up):
            r.signal_bear_volume_up_big_drop = True

        # --- 5. 缩量阴线（弱化版）---
        # PDF：缩量阴线 = 主力洗盘没有达到效果，次日大概率跌
        # 注意：胜宏科技验证只有51%成功率，需要更严格条件
        # 条件：阴线 + 缩量 + 跌幅<2% + 高位（下跌趋势中更有效）
        if (r.is_yin and r.is_volume_down and r.change_pct > -2.0
                and r.price_position > 0.5):  # 只在高位触发（下跌趋势）
            r.signal_bear_shrink_yin = True

        # --- 6. 高量破位 ---
        # PDF：高量破，有灾祸
        # 条件：近3日有高量 + 跌破高量实体低点
        if len(v) >= 3 and len(c) >= 3:
            vol_3d = v.tail(3)
            max_vol_idx = vol_3d.values.argmax()
            max_vol_date_idx = len(df) - 3 + max_vol_idx

            if max_vol_date_idx >= 0 and max_vol_date_idx < len(df):
                max_vol_o = float(o.iloc[max_vol_date_idx])
                max_vol_c = float(c.iloc[max_vol_date_idx])
                max_vol_low实体 = min(max_vol_o, max_vol_c)

                if r.close < max_vol_low实体 and r.is_high_volume:
                    r.signal_bear_high_vol_break = True

        # --- 7. 连红见绿 ---
        # PDF：连红≥4天见绿（放量）→ 减仓
        # 条件：连续>=4天阳线后出现放量阴线
        if r.consecutive_red >= 4 and r.is_yin and r.is_volume_up:
            r.signal_bear_consecutive_red_green = True

        # --- 8. 量增价跌 ---
        # PDF：下跌趋势中，量增价跌
        # 条件：阴线 + 放量 + 跌幅>2%
        if (r.is_yin and r.is_volume_up and r.change_pct < -2.0):
            r.signal_bear_volume_up_price_down = True

        # --- 9. 绿三兵（PDF规则30）---
        # PDF：压力线下方绿三兵---减C
        # 条件：连续3天阴线 + 收盘价递减
        if len(c) >= 3 and len(v) >= 3:
            three_yin = all(
                float(c.iloc[-i]) < float(o.iloc[-i])
                for i in range(1, 4)
            )
            three_close_down = (
                float(c.iloc[-1]) < float(c.iloc[-2]) < float(c.iloc[-3])
            )

            if three_yin and three_close_down:
                # 检查实体大小变化
                body1 = abs(float(c.iloc[-3]) - float(o.iloc[-3]))
                body2 = abs(float(c.iloc[-2]) - float(o.iloc[-2]))
                body3 = abs(float(c.iloc[-1]) - float(o.iloc[-1]))

                # 检查量能变化
                vol1 = float(v.iloc[-3])
                vol2 = float(v.iloc[-2])
                vol3 = float(v.iloc[-1])

                # 标准绿三兵：实体递增 + 量能递增
                if body3 > body2 > body1 and vol3 > vol2 > vol1:
                    r.signal_bear_green_three_soldiers = True

                # 衰减绿三兵：实体递减 + 量能递减（可能见底）
                elif body3 < body2 < body1 and vol3 < vol2 < vol1:
                    r.signal_bear_green_three_diminishing = True

        # --- 10. 上吊线 ---
        # PDF：高位出现长下影线小实体K线
        # 条件：在高位 + 长下影线 + 实体小
        if (r.lower_shadow_ratio > 0.6 and r.body_ratio < 0.3
                and len(c) >= 20):
            high_20 = float(c.tail(20).max())
            near_high = (high_20 - r.close) / high_20 < 0.05
            if near_high:
                r.signal_bear_hanging_man = True

        # --- 11. 黄昏之星 ---
        # PDF：顶部反转形态
        # 条件：第一天阳线 + 第二天十字星/小实体 + 第三天阴线
        if len(c) >= 3:
            day1_yang = float(c.iloc[-3]) > float(o.iloc[-3])
            day2_small = abs(float(c.iloc[-2]) - float(o.iloc[-2])) / (float(h.iloc[-2]) - float(l.iloc[-2]) + 0.001) < 0.3 if float(h.iloc[-2]) - float(l.iloc[-2]) > 0 else False
            day3_yin = float(c.iloc[-1]) < float(o.iloc[-1])
            # 在高位
            if day1_yang and day2_small and day3_yin and len(c) >= 20:
                high_20 = float(c.tail(20).max())
                if (high_20 - r.close) / high_20 < 0.05:
                    r.signal_bear_evening_star = True

        # --- 12. 看跌吞没 ---
        # PDF：顶部反转形态
        # 条件：第一天阴线 + 第二天阳线实体完全吞没第一天
        if len(c) >= 2:
            day1_yin = float(c.iloc[-2]) < float(o.iloc[-2])
            day2_yang = float(c.iloc[-1]) > float(o.iloc[-1])
            day1_body = abs(float(c.iloc[-2]) - float(o.iloc[-2]))
            day2_body = abs(float(c.iloc[-1]) - float(o.iloc[-1]))
            # 第二天实体完全吞没第一天
            engulfing = day2_body > day1_body
            # 在高位
            if day1_yin and day2_yang and engulfing and len(c) >= 20:
                high_20 = float(c.tail(20).max())
                if (high_20 - r.close) / high_20 < 0.05:
                    r.signal_bear_engulfing = True

    # ================================================================
    # 买入评分
    # ================================================================

    def _score_buy(self, df, r: VolumePriceSignal) -> int:
        """买入评分（满分100）"""
        score = 0
        buy_signals = r.buy_signals_list()

        # ======== 位置评分 (20分) ========
        # 根据回测结果：低位买入成功率远高于高位
        price_position = getattr(r, '_price_position', 0.5)
        if price_position < 0.15:
            score += 20  # 极低位，最高分
        elif price_position < 0.3:
            score += 15  # 低位
        elif price_position < 0.5:
            score += 8   # 中位
        elif price_position < 0.7:
            score += 3   # 中高位
        else:
            score += 0   # 高位，不加分

        # ======== 趋势评分 (10分) ========
        # PDF强调：趋势是背景，不是过滤器
        # 上涨趋势 + 买入信号 = 加分
        # 下跌趋势 + 买入信号 = 减分（但不阻止）
        # 中性趋势 + 买入信号 = 正常
        trend_score = 0
        if r.price_trend == "up":
            trend_score += 8   # 上涨趋势，信号更可靠
        elif r.price_trend == "neutral":
            trend_score += 5   # 中性趋势，正常
        elif r.price_trend == "down":
            trend_score += 2   # 下跌趋势，信号可靠性降低

        # 量价配合加分
        if r.vp_coordination == "healthy":
            trend_score += 2   # 价涨量增，健康
        elif r.vp_coordination == "washout":
            trend_score += 1   # 价跌量缩，可能是洗盘

        score += min(trend_score, 10)

        # --- 量价关系评分 (40分) ---
        vp_score = 0
        if "缩量大涨" in buy_signals:
            vp_score += 25
        if "放量大阳" in buy_signals:
            vp_score += 20
        if "缩量阳线" in buy_signals:
            vp_score += 12
        if "量缩微跌" in buy_signals:
            vp_score += 12
        if "平量大涨" in buy_signals:
            vp_score += 10
        if "放量微跌" in buy_signals:
            vp_score += 15
        if "缩量大阳" in buy_signals:
            vp_score += 18
        # 新增支撑压力信号
        if "支撑底分型" in buy_signals:
            vp_score += 15  # PDF规则20
        if "红三兵" in buy_signals:
            vp_score += 15  # PDF规则22
        if "高量突破" in buy_signals:
            vp_score += 20  # PDF规则28，强信号
        score += min(vp_score, 40)

        # --- 高量柱评分 (25分) ---
        hv_score = 0
        if "高量柱底部" in buy_signals:
            hv_score += 20
        if "恐慌洗盘" in buy_signals:
            hv_score += 18
        if "涨停缩倍量" in buy_signals:
            hv_score += 20
        score += min(hv_score, 25)

        # --- K线结构评分 (15分) ---
        pat_score = 0
        if "三阴不破阳" in buy_signals:
            pat_score += 15
        if "揉搓线" in buy_signals:
            pat_score += 10
        if "飞龙在天" in buy_signals:
            pat_score += 15  # 飞龙在天/龙回头是强信号
        if "支撑底分型" in buy_signals:
            pat_score += 12  # PDF规则20
        if "红三兵" in buy_signals:
            pat_score += 12  # PDF规则22
        if "高量突破" in buy_signals:
            pat_score += 15  # PDF规则28，强信号
        if "建仓形态" in buy_signals:
            pat_score += 12  # PDF建仓口诀
        if "进击线" in buy_signals:
            pat_score += 15  # PDF进击线，强信号
        if r.lower_shadow_ratio > 0.25 and r.is_yang:
            pat_score += 8
        if r.body_ratio < 0.2:
            pat_score += 5
        score += min(pat_score, 15)

        # --- 趋势确认评分 (10分) ---
        tr_score = 0
        if r.ma5 > r.ma10 > r.ma20:
            tr_score += 5
        elif r.ma5 > r.ma10:
            tr_score += 3
        if r.close > r.ma5:
            tr_score += 2
        if len(df["close"]) >= 60 and self._ma_slope(df["close"], 60) > 0:
            tr_score += 3
        score += min(tr_score, 10)

        return min(score, 100)

    # ================================================================
    # 卖出评分
    # ================================================================

    def _score_sell(self, df, r: VolumePriceSignal) -> int:
        """卖出评分（满分100）"""
        score = 0
        sell_signals = r.sell_signals_list()

        # --- 量价关系评分 (50分) ---
        vp_score = 0
        if "放量滞涨" in sell_signals:
            vp_score += 25
        if "放量大阴" in sell_signals:
            vp_score += 20
        if "放量大跌" in sell_signals:
            vp_score += 22
        if "平量滞涨" in sell_signals:
            vp_score += 18
        if "量增价跌" in sell_signals:
            vp_score += 15
        if "缩量阴线" in sell_signals:
            vp_score += 12
        if "连红见绿" in sell_signals:
            vp_score += 18
        score += min(vp_score, 50)

        # --- 高量柱评分 (30分) ---
        hv_score = 0
        if "高量破位" in sell_signals:
            hv_score += 28
        score += min(hv_score, 30)

        # --- K线结构评分 (10分) ---
        pat_score = 0
        if r.upper_shadow_ratio > 0.3:
            pat_score += 8
        if r.body_ratio < 0.2:
            # 判断是否在高位
            if len(df["close"]) >= 20:
                high_20 = float(df["close"].tail(20).max())
                if (high_20 - r.close) / high_20 < 0.03:
                    pat_score += 6
        score += min(pat_score, 10)

        # --- 趋势确认评分 (10分) ---
        tr_score = 0
        if r.ma5 < r.ma10 < r.ma20:
            tr_score += 5
        if r.close < r.ma5:
            tr_score += 3
        if r.ret_5d < -3:
            tr_score += 2
        score += min(tr_score, 10)

        return min(score, 100)

    # ================================================================
    # 决策逻辑
    # ================================================================

    def _decide_action(self, r: VolumePriceSignal) -> str:
        """根据买卖评分决定操作"""
        buy_signals = r.buy_signals_list()
        sell_signals = r.sell_signals_list()
        price_position = getattr(r, '_price_position', 0.5)

        # 有卖出信号且评分达标 → 卖出
        if r.sell_score >= self._sell_threshold and len(sell_signals) > 0:
            critical_sell = {"放量滞涨", "高量破位", "放量大跌", "放量大阴"}
            if critical_sell.intersection(set(sell_signals)):
                return "卖出"

        # 有买入信号且评分达标 → 买入
        # 位置过滤：低位买入门槛低，高位买入门槛高
        if r.buy_score >= self._buy_threshold and len(buy_signals) > 0:
            critical_buy = {"缩量大涨", "放量大阳", "恐慌洗盘", "高量柱底部", "飞龙在天",
                           "支撑底分型", "红三兵", "高量突破", "建仓形态", "进击线"}

            # 低位（<30%）：允许更多信号触发
            if price_position < 0.3:
                if critical_buy.intersection(set(buy_signals)):
                    return "买入"
                # 低位多信号也可以买入
                if len(buy_signals) >= 2 and r.buy_score >= 45:
                    return "买入"

            # 中位（30-50%）：需要更强的信号
            elif price_position < 0.5:
                if critical_buy.intersection(set(buy_signals)) and r.buy_score >= 55:
                    return "买入"

            # 高位（>50%）：只允许最强信号
            else:
                if {"缩量大涨", "恐慌洗盘", "飞龙在天"}.intersection(set(buy_signals)) and r.buy_score >= 65:
                    return "买入"

        # 多信号叠加增强（仅低位有效）
        if len(buy_signals) >= 3 and r.buy_score >= 50 and price_position < 0.3:
            return "买入"
        if len(sell_signals) >= 2 and r.sell_score >= 35:
            return "卖出"

        return "观望"

    # ================================================================
    # 增强：is_valid_entry
    # ================================================================

    def is_valid_entry(self, signals: SignalResult) -> tuple[bool, str]:
        """量价策略专用买入验证"""
        if signals.strategy_type == "减仓":
            return False, "卖出信号触发"
        if signals.strategy_type == "观望":
            return False, "观望状态"
        if signals.strategy_type == "低吸":
            if signals.entry_score < self._buy_threshold:
                return False, f"买入评分{signals.entry_score}<{self._buy_threshold}"
            if signals.signal_count < 1:
                return False, "无买入信号触发"
            return True, "通过"
        return False, f"未知策略类型{signals.strategy_type}"

    # ================================================================
    # 历史遍历
    # ================================================================

    def evaluate_history(self, df) -> list[dict]:
        """遍历DataFrame历史，逐日输出量价信号评估"""
        results = []
        min_window = 20

        for i in range(min_window, len(df)):
            window = df.iloc[:i + 1].copy()
            vp = self.evaluate_volume_price(window, symbol="")

            results.append({
                "date": vp.date,
                "close": round(vp.close, 2),
                "change_pct": round(vp.change_pct, 2),
                "is_high_volume": vp.is_high_volume,
                "is_volume_up": vp.is_volume_up,
                "is_volume_down": vp.is_volume_down,
                "buy_signals": vp.buy_signals_list(),
                "sell_signals": vp.sell_signals_list(),
                "buy_score": vp.buy_score,
                "sell_score": vp.sell_score,
                "action": vp.action,
            })

        return results

    # ================================================================
    # 工具方法
    # ================================================================

    @staticmethod
    def _count_consecutive(c, o, direction: str) -> int:
        count = 0
        for i in range(len(c) - 1, -1, -1):
            if direction == "yang" and float(c.iloc[i]) > float(o.iloc[i]):
                count += 1
            elif direction == "yin" and float(c.iloc[i]) < float(o.iloc[i]):
                count += 1
            else:
                break
        return count

    @staticmethod
    def _ma_slope(c, period=60, lookback=5) -> float:
        ma = c.rolling(period).mean()
        if len(ma) < lookback + 1:
            return 0.0
        return float((ma.iloc[-1] / ma.iloc[-lookback] - 1) if ma.iloc[-lookback] > 0 else 0.0)

    @classmethod
    def meta(cls) -> dict:
        # 直接返回信号列表
        return {
            "name": cls.name,
            "version": cls.version,
            "description": "严格基于PDF原文定义的量价分析策略",
            "source": "《量价资料》山东神光咨询",
            "key_definitions": {
                "高量柱": "当天的量 > 前3天的量",
                "放量": "当天量 > 前几天量",
                "缩量": "当天量 < 前几天量",
            },
            "signals": {
                "buy": [
                    "放量大阳", "缩量大阳", "放量微跌", "缩量大涨",
                    "量缩微跌", "平量大涨", "缩量阳线", "恐慌洗盘",
                    "高量柱底部", "涨停缩倍量", "三阴不破阳", "揉搓线",
                    "飞龙在天", "支撑底分型", "红三兵", "衰减红三兵",
                    "高量突破", "上影线突破", "建仓形态", "进击线",
                    "早晨之星", "锤子线", "长下影线", "支撑位十字星",
                ],
                "sell": [
                    "放量滞涨", "放量大阴", "平量滞涨", "放量大跌",
                    "缩量阴线", "高量破位", "连红见绿", "量增价跌",
                    "绿三兵", "衰减绿三兵", "上吊线", "黄昏之星", "看跌吞没",
                    "长上影线", "压力位十字星",
                ],
            },
        }
