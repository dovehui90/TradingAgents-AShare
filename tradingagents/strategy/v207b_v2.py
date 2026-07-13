"""
V207b_v2 短线交易策略

核心：6个回调结束信号 + 硬过滤 + 三维评分 + 形态→策略映射
只关注买点质量，不管理仓位/止盈止损。
"""

import numpy as np
import pandas as pd
from .base_strategy import BaseStrategy, SignalResult


class V207bV2Strategy(BaseStrategy):
    name = "短线策略"
    version = "2.0"

    # 20日K线形态 → 策略类型映射
    PATTERN_MAP = {
        "V型反转": "抄底", "圆弧底": "抄底", "复合筑底": "抄底", "加速下跌": "抄底",
        "加速上涨": "追涨", "关键突破": "追涨",
        "单边上涨": "低吸", "震荡上行": "低吸", "上涨中继": "低吸",
        "旗形整理": "低吸", "箱体震荡": "低吸", "宽幅震荡": "低吸",
        "单边下跌": "观望", "震荡下行": "观望", "下跌中继": "观望",
        "窄幅震荡": "观望", "发散三角": "观望", "脉冲走势": "观望",
        "圆弧顶": "减仓", "高位见顶": "减仓",
    }

    # 看涨形态 (信号6升级用)
    BULLISH_PATTERNS = {"低位放量大阳线", "低位旭日东升", "杯柄突破回踩", "缩量止跌"}
    # 看跌形态 (信号6否决用)
    BEARISH_PATTERNS = {"高位放量大阴线", "高位黄昏之星", "高位弃婴", "高位三只乌鸦"}

    def __init__(self, config_path: str | None = None):
        super().__init__(config_path)
        self._score_thresholds = self.config.get("score_thresholds", {
            "追涨": 65, "低吸": 55, "抄底": 55,
        })
        self._optimal_signal_range = self.config.get("entry_rules", {}).get(
            "optimal_signal_range", [3, 4])
        self._signal_weights = self.config.get("signal_weights", {
            "signal_1": 1.0, "signal_2": 0.8, "signal_3": 1.0,
            "signal_4": 0.6, "signal_5": 0.4,
        })

    # ==================================================================
    # 公共入口
    # ==================================================================

    def evaluate_signals(self, df, symbol: str = "") -> SignalResult:
        """输入OHLCV DataFrame，输出完整信号评估"""
        if len(df) < 60:
            return SignalResult(symbol=symbol, date=str(df.index[-1])[:10])

        o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]

        result = SignalResult(symbol=symbol, date=str(df.index[-1])[:10])
        result.close = float(c.iloc[-1])

        # 均线
        result.ma5 = float(c.rolling(5).mean().iloc[-1])
        result.ma10 = float(c.rolling(10).mean().iloc[-1])
        result.ma20 = float(c.rolling(20).mean().iloc[-1])
        result.ma60 = float(c.rolling(60).mean().iloc[-1])

        # ATR + RSI
        result.atr_14 = self._calc_atr(h, l, c, 14)
        result.rsi_6 = self._calc_rsi(c, 6)

        # 量能
        result.volume_5d_mean = float(v.tail(5).mean())
        result.volume_3d_mean = float(v.tail(3).mean())
        result.volume_10d_mean = float(v.tail(10).mean())
        result.volume_ratio = (float(v.iloc[-1]) / result.volume_5d_mean
                               if result.volume_5d_mean > 0 else 1.0)

        # 近5日涨幅
        if len(c) >= 5:
            result.ret_5d = float((c.iloc[-1] / c.iloc[-5] - 1))

        # ---- 核心：计算6个信号 ----
        self._eval_6_signals(df, result)
        result.signal_count = len(result.triggered_signals())

        # ---- 信号6形态判定 ----
        self._eval_signal6_pattern(df, result)

        # ---- 过热判断 ----
        result.ma5_deviation = (float(c.iloc[-1] / result.ma5 - 1)
                                if result.ma5 > 0 else 0.0)
        if result.signal_count >= 6:
            result.is_overheated = True
        elif result.signal_count >= 5 and result.ma5_deviation > 0.06:
            result.is_overheated = True

        # ---- 硬过滤 ----
        result.ma60_slope_positive = self._ma_slope(c, 60) > 0
        result.above_ma10 = float(c.iloc[-1]) > result.ma10

        # ---- 形态→策略 ----
        result.strategy_type = self._classify_pattern(df)

        # ---- 评分 ----
        result.entry_score = self._score_entry(df, result)

        return result

    # ==================================================================
    # 6个回调结束信号
    # ==================================================================

    def _eval_6_signals(self, df, r: SignalResult):
        c, l, v = df["close"], df["low"], df["volume"]

        # 信号1：近3日不创新低
        if len(l) >= 3:
            r.signal_1_no_new_low = float(l.iloc[-1]) >= float(l.tail(3).min())

        # 信号2：收盘站上MA5
        r.signal_2_above_ma5 = r.close > r.ma5

        # 信号3：缩量企稳（近3日均量 < 近10日均量）
        r.signal_3_volume_shrink = r.volume_3d_mean < r.volume_10d_mean

        # 信号4：近5日涨幅>0
        r.signal_4_5d_positive = r.ret_5d > 0

        # 信号5：距20日高点<3%
        if len(c) >= 20:
            high_20d = float(c.tail(20).max())
            r.signal_5_near_high = (high_20d - r.close) / high_20d < 0.03

    # ==================================================================
    # 信号6：形态确认/否决
    # ==================================================================

    def _eval_signal6_pattern(self, df, r: SignalResult):
        """识别K08形态，升级或否决信号3"""
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        price = float(c.iloc[-1])

        # 位置判断
        if len(c) < 20:
            return
        high_20 = float(c.tail(20).max())
        low_20 = float(c.tail(20).min())
        near_high = (high_20 - price) / high_20 < 0.03 if high_20 > 0 else False
        near_low = (price - low_20) / low_20 < 0.05 if low_20 > 0 else False

        # 量比
        vol_ratio = r.volume_ratio

        # 阴阳
        is_yang = float(c.iloc[-1]) > float(df["open"].iloc[-1])

        # 看涨形态检查
        if self._is_bullish_low_volume_yang(df, near_low, vol_ratio, is_yang):
            r.signal_6_pattern_action = "upgrade"
        # 看跌形态检查
        elif self._is_bearish_high_volume_yin(df, near_high, vol_ratio, is_yang):
            r.signal_6_pattern_action = "veto"

    def _is_bullish_low_volume_yang(self, df, near_low, vol_ratio, is_yang) -> bool:
        """低位放量大阳线 / 低位旭日东升 / 缩量止跌"""
        c = df["close"]
        o = df["open"]

        # 低位放量大阳线
        if near_low and vol_ratio > 1.5 and is_yang:
            return True
        # 低位旭日东升（前阴后阳 + 开盘>前收）
        if near_low and len(c) >= 2:
            prev_yin = float(c.iloc[-2]) < float(o.iloc[-2])
            today_open = float(o.iloc[-1])
            prev_close = float(c.iloc[-2])
            if prev_yin and is_yang and today_open > prev_close:
                return True
        # 缩量止跌（低位+缩量+量比<0.7）
        if near_low and vol_ratio < 0.7:
            return True
        return False

    def _is_bearish_high_volume_yin(self, df, near_high, vol_ratio, is_yang) -> bool:
        """高位放量大阴线 / 高位黄昏之星 / 高位三只乌鸦"""
        c = df["close"]
        o = df["open"]
        is_yin = not is_yang

        # 高位放量大阴线
        if near_high and vol_ratio > 1.2 and is_yin:
            return True
        # 高位三只乌鸦（三连阴 + 收盘递减）
        if near_high and len(c) >= 3:
            yin_3 = all(float(c.iloc[-i]) < float(o.iloc[-i]) for i in range(1, 4))
            dec_3 = float(c.iloc[-1]) < float(c.iloc[-2]) < float(c.iloc[-3])
            if yin_3 and dec_3:
                return True
        return False

    # ==================================================================
    # 形态→策略分类
    # ==================================================================

    def _classify_pattern(self, df) -> str:
        """基于趋势+均线+Wyckoff信号推断形态→策略映射"""
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        if len(c) < 20:
            return "观望"

        price = float(c.iloc[-1])
        ma5 = float(c.rolling(5).mean().iloc[-1])
        ma10 = float(c.rolling(10).mean().iloc[-1])
        ma20 = float(c.rolling(20).mean().iloc[-1])
        low_20 = float(c.tail(20).min())
        high_20 = float(c.tail(20).max())
        price_position = (price - low_20) / (high_20 - low_20 + 0.001)

        # 先检查抄底条件（不依赖均线排列，在下跌段中也能触发）
        if self._is_bottom_fishing_setup(df):
            return "抄底"

        # 均线空头 → 观望
        if ma5 < ma10 < ma20:
            return "观望"

        # 均线多头
        if ma5 > ma10 > ma20:
            if price_position > 0.85:
                ret_3d = float((c.iloc[-1] / c.iloc[-3] - 1)) if len(c) >= 3 else 0
                if ret_3d < 0.01:
                    return "减仓"
                if self._is_chasing_setup(df):
                    return "追涨"
                return "低吸" if self._is_dip_buying_setup(df) else "观望"
            if self._is_chasing_setup(df):
                return "追涨"
            return "低吸" if self._is_dip_buying_setup(df) else "观望"

        # 非标准多头但短期强势 → 也可能追涨
        if self._is_chasing_setup(df):
            return "追涨"

        # 震荡格局
        if price_position < 0.3:
            return "抄底"
        # 低吸需要趋势结构支撑，否则降级为观望
        if self._is_dip_buying_setup(df):
            return "低吸"
        return "观望"

    def _is_dip_buying_setup(self, df) -> bool:
        """低吸趋势结构验证：区分真回调 vs 下跌中继"""
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        if len(c) < 20:
            return False

        price = float(c.iloc[-1])
        ma20 = c.rolling(20).mean()
        ma20_now = float(ma20.iloc[-1])
        ma20_5d_ago = float(ma20.iloc[-6])

        # 条件1：MA20不能持续下行（趋势未破坏）
        ma20_slope = (ma20_now / ma20_5d_ago - 1) if ma20_5d_ago > 0 else 0
        if ma20_slope < -0.03:  # MA20加速下行 = 下跌趋势
            return False

        # 条件2：近20日内有上升波段（打过阶段性高点）
        high_20 = float(c.tail(20).max())
        high_20_pos = c.tail(20).values.argmax()
        # 高点不能在最近3天（否则可能是假突破后直接跌）
        if high_20_pos >= len(c.tail(20)) - 3:
            # 高点在最末端，可能还在高位，检查是不是刚开始跌
            ret_3d = float((c.iloc[-1] / c.iloc[-3] - 1)) if len(c) >= 3 else 0
            if ret_3d < -0.05:  # 近3日已跌超5%，可能是顶部反转
                return False

        # 条件3：近10日有过高点和低点，形成基本波动结构
        if len(c) >= 10:
            high_10 = float(c.tail(10).max())
            low_10 = float(c.tail(10).min())
            swing_range = (high_10 - low_10) / low_10 if low_10 > 0 else 0
            # 振幅太小（<3%）= 横盘无方向，低吸无意义
            if swing_range < 0.03:
                return False

        # 条件4：当前回调是缩量的（不是放量下跌）
        if len(v) >= 5:
            recent_vol = float(v.tail(3).mean())
            prior_vol = float(v.iloc[-8:-3].mean()) if len(v) >= 8 else float(v.head(5).mean())
            # 回调段量能应小于前段（缩量回调=洗盘，放量回调=出货）
            vol_expanding_on_dip = recent_vol > prior_vol * 1.3 and float((c.iloc[-1] / c.iloc[-5] - 1)) < -0.02
            if vol_expanding_on_dip:
                return False

        # 条件5：MA60斜率不能崩盘
        if self._ma_slope(c, 60) < -0.05:
            return False

        return True

    def _find_swing_highs(self, df, lookback: int = 60) -> list[float]:
        """找出近期波峰压力位（价格由升转跌的转折点），从近到远排列"""
        h = df["high"]
        if len(h) < lookback:
            lookback = len(h)
        recent = h.tail(lookback)
        swings = []
        for i in range(3, len(recent) - 1):
            # 波峰：当前高点 > 前后各3根K线的高点
            left = recent.iloc[i-3:i].max()
            right = recent.iloc[i+1:i+4].max()
            if recent.iloc[i] > left and recent.iloc[i] > right:
                swings.append(float(recent.iloc[i]))
        swings.sort(reverse=True)
        return swings

    def _get_resistance_levels(self, df) -> tuple[float | None, float | None]:
        """返回最近两个压力位：(第一压力位, 第二压力位)"""
        price = float(df["close"].iloc[-1])
        swings = self._find_swing_highs(df)
        r1 = None
        r2 = None
        for s in swings:
            if s > price:
                if r1 is None:
                    r1 = s
                elif r2 is None:
                    r2 = s
                    break
        return r1, r2

    def _is_chasing_setup(self, df) -> bool:
        """追涨识别：蓄力→放量突破→站稳 链条，用波峰判断压力位"""
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        o = df["open"]
        if len(c) < 20:
            return False

        price = float(c.iloc[-1])
        ma5 = float(c.rolling(5).mean().iloc[-1])
        ma10 = float(c.rolling(10).mean().iloc[-1])
        r1, _ = self._get_resistance_levels(df)

        # ---- 否决条件 ----

        # 1. 近5日涨幅>15% → 已透支
        ret_5d = float((c.iloc[-1] / c.iloc[-5] - 1)) if len(c) >= 5 else 0
        if ret_5d > 0.15:
            return False

        # 2. 连阳≥5日 → 情绪过热
        consecutive_yang = 0
        for i in range(len(o) - 1, max(0, len(o) - 6) - 1, -1):
            if float(c.iloc[i]) > float(o.iloc[i]):
                consecutive_yang += 1
            else:
                break
        if consecutive_yang >= 5:
            return False

        # 3. 当日冲高回落（长上影）→ 抛压重
        amp = float(h.iloc[-1] - l.iloc[-1])
        upper_shadow = float(h.iloc[-1] - max(o.iloc[-1], c.iloc[-1]))
        if amp > 0 and upper_shadow / amp > 0.30:
            return False

        # 4. 收盘在当日振幅下半区 → 空头主导，假突破
        if amp > 0:
            close_pos = (price - float(l.iloc[-1])) / amp
            if close_pos < 0.45:
                return False

        # ---- 触发条件（满足任一） ----

        vol_ratio = float(v.iloc[-1]) / float(v.tail(5).mean()) if float(v.tail(5).mean()) > 0 else 1

        # A. 突破压力位型：价格已突破最近波峰压力位 + 放量
        if r1 and price > r1 and vol_ratio > 1.0:
            return True

        # B. 紧贴压力位型：价格在压力位2%内 + 短期加速 + 量能配合
        if r1 and (r1 - price) / r1 < 0.02:
            ret_3d = float((c.iloc[-1] / c.iloc[-3] - 1)) if len(c) >= 3 else 0
            if ret_3d > 0.02 and vol_ratio > 1.1:
                return True

        # C. 加速型：均线多头 + 放量 + 价格在MA5上方 + MA5加速
        if ma5 > ma10 and price > ma5 and vol_ratio > 1.1:
            ma5_slope_now = float((c.iloc[-1] / c.iloc[-3] - 1)) if len(c) >= 3 else 0
            ma5_slope_prev = float((c.iloc[-4] / c.iloc[-6] - 1)) if len(c) >= 6 else 0
            if ma5_slope_now > ma5_slope_prev:  # 动量在加速
                return True

        return False

    def _is_bottom_fishing_setup(self, df) -> bool:
        """真底识别：恐慌抛售→缩量回踩→不创新低 链条检测"""
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        o = df["open"]
        if len(c) < 15:
            return False

        price = float(c.iloc[-1])
        low_20 = float(c.tail(20).min())
        price_position = (price - low_20) / (low_20 + 0.001)

        # 前置条件：价格在20日低位区域（距低点<8%）或 20日跌幅>10%
        ret_20d = float((c.iloc[-1] / c.iloc[-20] - 1)) if len(c) >= 20 else 0
        near_low = price_position < 0.08
        deep_drop = ret_20d < -0.10
        if not (near_low or deep_drop):
            return False

        # 条件1：近15日内有恐慌抛售痕迹
        sc_found = self._detect_sc(df)
        if not sc_found:
            return False

        # 条件2：近5日量能萎缩（卖方力竭）
        vol_tail = v.tail(5)
        vol_declining = float(vol_tail.iloc[-1]) < float(vol_tail.iloc[0]) * 0.85

        # 条件3：近3日不创新低 或 低点抬高
        if len(l) >= 3:
            recent_low = float(l.tail(3).min())
            prior_low = float(l.iloc[-6:-3].min()) if len(l) >= 6 else float(l.tail(3).max())
            no_new_low = recent_low >= prior_low * 0.98
        else:
            no_new_low = False

        # 条件4：均线不处于崩盘式空头（MA60斜率 > -5%）
        ma60_slope = self._ma_slope(c, 60)
        not_crashing = ma60_slope > -0.05

        return sc_found and (vol_declining or no_new_low) and not_crashing

    def _detect_sc(self, df) -> bool:
        """检测近15日内是否有恐慌抛售（SC）：放量+大跌+下影线回收"""
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        o = df["open"]
        ma20_v = v.rolling(20).mean()

        for i in range(max(0, len(df) - 15), len(df)):
            if i < 1:
                continue
            chg = float((c.iloc[i] / c.iloc[i-1] - 1))
            vol_ratio_vs_ma20 = float(v.iloc[i] / ma20_v.iloc[i]) if ma20_v.iloc[i] > 0 else 1
            amp = float(h.iloc[i] - l.iloc[i])
            lower_shadow = float(min(o.iloc[i], c.iloc[i]) - l.iloc[i])
            lower_ratio = lower_shadow / amp if amp > 0 else 0

            # SC条件：放量(>1.3倍均量) + 跌幅>3% + 下影线>振幅25%（盘中恐慌被接回）
            if vol_ratio_vs_ma20 > 1.3 and chg < -0.03 and lower_ratio > 0.25:
                return True

            # 或：连续2日放量下跌后出现长下影止跌
            if i >= 2:
                chg_1 = float((c.iloc[i-1] / c.iloc[i-2] - 1))
                vol_both = (float(v.iloc[i-1]) > ma20_v.iloc[i-1] * 1.2 and
                           float(v.iloc[i]) > ma20_v.iloc[i] * 1.2)
                if vol_both and chg_1 < -0.03 and chg > -0.01 and lower_ratio > 0.20:
                    return True

        return False

    def _detect_st(self, df) -> bool:
        """检测是否出现二次测试：回踩SC低点附近+缩量+不破"""
        c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
        o = df["open"]
        ma20_v = v.rolling(20).mean()

        # 找到最近一次SC的位置和低点
        sc_low = None
        sc_vol = None
        for i in range(max(0, len(df) - 20), len(df)):
            if i < 1:
                continue
            chg = float((c.iloc[i] / c.iloc[i-1] - 1))
            vol_ratio_vs_ma20 = float(v.iloc[i] / ma20_v.iloc[i]) if ma20_v.iloc[i] > 0 else 1
            amp = float(h.iloc[i] - l.iloc[i])
            lower_shadow = float(min(o.iloc[i], c.iloc[i]) - l.iloc[i])
            lower_ratio = lower_shadow / amp if amp > 0 else 0

            if vol_ratio_vs_ma20 > 1.3 and chg < -0.03 and lower_ratio > 0.25:
                sc_low = float(l.iloc[i])
                sc_vol = float(v.iloc[i])

        if sc_low is None:
            return False

        # SC之后是否出现缩量回踩
        today_low = float(l.iloc[-1])
        today_vol = float(v.iloc[-1])
        near_sc_low = abs(today_low - sc_low) / sc_low < 0.04
        vol_lower = sc_vol and today_vol < sc_vol * 0.8
        # 收盘价不能有效跌破SC低点（>2%）
        not_broken = float(c.iloc[-1]) > sc_low * 0.98

        return near_sc_low and vol_lower and not_broken

    # ==================================================================
    # 评分系统
    # ==================================================================

    def _score_entry(self, df, r: SignalResult) -> int:
        stype = r.strategy_type
        if stype == "低吸":
            return self._score_dip_buying(df, r)
        elif stype == "抄底":
            return self._score_bottom_fishing(df, r)
        elif stype == "追涨":
            return self._score_chasing(df, r)
        return 0

    def _score_dip_buying(self, df, r: SignalResult) -> int:
        """低吸评分（满分100）：回踩质量+缩量确认+趋势结构"""
        score = 0
        c, v, l = df["close"], df["volume"], df["low"]
        price = float(c.iloc[-1])

        # D1 回踩均线质量 30分
        ma_distance = 0
        if r.ma20 > 0:
            dist_to_ma20 = abs(price - r.ma20) / r.ma20
            if dist_to_ma20 < 0.03:
                score += 30  # 精准回踩MA20
                ma_distance = dist_to_ma20
            elif dist_to_ma20 < 0.05:
                score += 20  # 接近MA20
            elif price > r.ma20 and dist_to_ma20 < 0.10:
                score += 10  # 在MA20上方不远
        if r.ma10 > 0:
            dist_to_ma10 = abs(price - r.ma10) / r.ma10
            if dist_to_ma10 < 0.02 and score < 25:
                score += 15  # 回踩MA10也是好位置

        # D2 缩量确认 25分：回调缩量=洗盘
        if len(v) >= 5:
            v_recent_3 = float(v.tail(3).mean())
            v_prior_5 = float(v.iloc[-8:-3].mean()) if len(v) >= 8 else float(v.head(5).mean())
            vol_contraction = v_recent_3 / v_prior_5 if v_prior_5 > 0 else 1.0
            if vol_contraction < 0.6:   # 大幅缩量
                score += 25
            elif vol_contraction < 0.8:
                score += 18  # 明显缩量
            elif vol_contraction < 0.95:
                score += 10  # 轻微缩量

        # D3 趋势结构 25分
        ma20_rising = r.ma20 > float(c.rolling(20).mean().iloc[-6]) if len(c) >= 26 else False
        if ma20_rising and r.ma5 > r.ma10:
            score += 25  # MA20上行+短期均线不乱
        elif ma20_rising:
            score += 18
        elif r.ma5 > r.ma10 > r.ma20:
            score += 15  # 均线多头但MA20可能走平
        elif r.ma5 > r.ma10:
            score += 8

        # D4 RSI甜点区 20分：40-60最佳（不超卖不超买）
        if 40 <= r.rsi_6 <= 60:
            score += 20
        elif 35 <= r.rsi_6 <= 65:
            score += 12
        elif r.rsi_6 < 35:
            score += 5  # 太低 = 弱势，不是正常回调

        return score

    def _score_bottom_fishing(self, df, r: SignalResult) -> int:
        """抄底评分（满分100）：SC→ST→缩量→不创新低 四维验证"""
        score = 0
        c, v, l = df["close"], df["volume"], df["low"]

        # F1 恐慌抛售确认 25分
        if self._detect_sc(df):
            score += 25
            # SC后缩量二次测试 → 加分
            if self._detect_st(df):
                score += 10  # SC+ST 双重确认 = 35分
        else:
            # 无SC但有放量下跌+止跌迹象 → 部分得分
            if r.rsi_6 < 40 and r.volume_ratio < 0.8:
                score += 10

        # F2 量能萎缩趋势 25分：卖方力竭
        if len(v) >= 5:
            v_recent = v.tail(5)
            # 连续萎缩（每3日均量递减）
            v_3d_1 = float(v_recent.iloc[-3:].mean())
            v_3d_0 = float(v_recent.iloc[:3].mean())
            if v_3d_1 < v_3d_0 * 0.75:  # 明显萎缩
                score += 25
            elif v_3d_1 < v_3d_0 * 0.9:  # 轻微萎缩
                score += 15
            elif r.volume_ratio < 0.7:  # 单日地量
                score += 10

        # F3 底部结构 25分：不创新低+低点抬高
        if len(l) >= 6:
            recent_min = float(l.tail(3).min())
            prior_min = float(l.iloc[-6:-3].min())
            if recent_min > prior_min * 1.01:  # 低点明显抬高
                score += 25
            elif recent_min >= prior_min * 0.99:  # 基本不创新低
                score += 15
        elif r.signal_1_no_new_low:
            score += 15

        # F4 超卖+支撑共振 25分
        has_oversold = r.rsi_6 < 45
        near_low_20 = False
        if len(c) >= 20:
            low_20_val = float(c.tail(20).min())
            near_low_20 = (float(c.iloc[-1]) - low_20_val) / low_20_val < 0.05
        if has_oversold and near_low_20:
            score += 25
        elif has_oversold or near_low_20:
            score += 12

        return score

    def _score_chasing(self, df, r: SignalResult) -> int:
        """追涨评分（满分100）：突破压力位+量能确认+站稳度+MA5加速+趋势共振"""
        score = 0
        c, v, h, l = df["close"], df["volume"], df["high"], df["low"]
        price = float(c.iloc[-1])
        r1, r2 = self._get_resistance_levels(df)
        amp = float(h.iloc[-1] - l.iloc[-1])

        # C1 突破压力位 30分
        if r1:
            if price > r1:
                score += 30  # 已突破第一压力位
                if r2 and price > r2:
                    score += 5  # 连破两层 → 空间打开
            elif (r1 - price) / r1 < 0.02:
                # 紧贴压力位，当日放量+站稳 → 即将突破
                close_pos = (price - float(l.iloc[-1])) / amp if amp > 0 else 0.5
                if close_pos > 0.5 and r.volume_ratio > 1.2:
                    score += 22
                else:
                    score += 12
            elif (r1 - price) / r1 < 0.05:
                score += 5  # 接近压力位
        else:
            score += 10  # 无上方压力（新高区域）

        # C2 量能确认 25分
        if r.volume_ratio > 1.5:
            score += 25
        elif r.volume_ratio > 1.2:
            score += 18
        elif r.volume_ratio > 1.0:
            score += 10

        # C3 收盘站稳度 20分（替换RSI：多头控盘程度）
        if amp > 0:
            close_pos = (price - float(l.iloc[-1])) / amp
            if close_pos > 0.65:
                score += 20  # 收在振幅上1/3，多头绝对控盘
            elif close_pos > 0.50:
                score += 12  # 收在上半区
            else:
                score += 0   # 收在下半区，不追
        else:
            score += 10

        # C4 MA5加速度 15分（替换RSI：动量是否在增强）
        if len(c) >= 6:
            ma5_now = float(c.tail(3).mean())
            ma5_mid = float(c.iloc[-5:-2].mean()) if len(c) >= 5 else ma5_now
            ma5_prev = float(c.iloc[-8:-5].mean()) if len(c) >= 8 else ma5_mid
            if ma5_now > ma5_mid > ma5_prev:
                score += 15  # MA5持续加速
            elif ma5_now > ma5_mid:
                score += 10  # MA5仍在加速但前段减速
            elif ma5_now > ma5_prev:
                score += 5   # 总体还在向上
        else:
            score += 5

        # C5 趋势共振 10分
        if r.ma5 > r.ma10 > r.ma20:
            score += 10
        elif r.ma5 > r.ma10:
            score += 5

        return score

    # ==================================================================
    # 入口验证（覆盖基类，加入策略特有逻辑）
    # ==================================================================

    def is_valid_entry(self, signals: SignalResult) -> tuple[bool, str]:
        # 信号6否决（所有策略通用）
        if signals.signal_6_pattern_action == "veto":
            return False, "信号6形态否决"

        # 过热（所有策略通用）
        if signals.signal_count >= 5 and signals.ma5_deviation > 0.06:
            return False, f"真过热：信号{signals.signal_count}+乖离{signals.ma5_deviation:.1%}"
        if signals.signal_count >= 6:
            return False, "信号全触发，绝对过热"

        # --- 抄底专用过滤 ---
        if signals.strategy_type == "抄底":
            return self._validate_bottom_fishing(signals)

        # --- 低吸专用过滤 ---
        if signals.strategy_type == "低吸":
            return self._validate_dip_buying(signals)

        # --- 追涨专用过滤 ---
        if signals.strategy_type == "追涨":
            return self._validate_chasing(signals)

        # 观望/减仓等不应进入买入
        if signals.strategy_type in ("观望", "减仓", "none"):
            return False, f"形态判定为{signals.strategy_type}"

        return False, f"未知策略类型{signals.strategy_type}"

    def _validate_chasing(self, r: SignalResult) -> tuple[bool, str]:
        """追涨专用验证：放量确认+突破压力位+动量加速+多头控盘"""
        # 1. 量能必须确认（追涨必须有量）
        if r.volume_ratio < 1.0:
            return False, f"量比{r.volume_ratio:.2f}<1.0，无量不追"

        # 2. MA60斜率>0（中期趋势向上）
        if not r.ma60_slope_positive:
            return False, "MA60斜率≤0"

        # 3. 均线至少短期多头
        if not (r.ma5 > r.ma10):
            return False, "短期均线未多头"

        # 4. 信号数≤4（追涨不等缩量，但过热不行）
        if r.signal_count > 4:
            return False, f"信号{r.signal_count}>4，接近过热"

        # 5. 评分门槛
        if r.entry_score < 60:
            return False, f"追涨评分{r.entry_score}<60"

        return True, "通过"

    def _validate_dip_buying(self, r: SignalResult) -> tuple[bool, str]:
        """低吸专用验证：趋势完整+缩量回调+支撑有效"""
        # 1. MA60斜率必须>0（低吸需要中期趋势向上）
        if not r.ma60_slope_positive:
            return False, "MA60斜率≤0，中期趋势不支撑低吸"

        # 2. 必须站上MA10
        if not r.above_ma10:
            return False, "未站上MA10"

        # 3. 近5日不能是持续下跌（动能要求）
        if r.ret_5d < -0.05:
            return False, f"近5日跌幅{r.ret_5d:.1%}过大，可能是下跌趋势"

        # 4. 信号数≥3
        if r.signal_count < 3:
            return False, f"回调结束信号仅{r.signal_count}个"

        # 5. RSI≥70超买（低吸不适合追高）
        if r.rsi_6 >= 70:
            return False, f"RSI{r.rsi_6:.0f}≥70，超买不低吸"

        # 6. 缩量是加分不是否决：只否决严重无量（量比<0.4无意义）
        if r.volume_ratio < 0.4:
            return False, f"量比{r.volume_ratio:.2f}<0.4，严重无量"

        # 7. 评分门槛
        if r.entry_score < 45:
            return False, f"低吸评分{r.entry_score}<45"

        return True, "通过"

    def _validate_bottom_fishing(self, r: SignalResult) -> tuple[bool, str]:
        """抄底专用验证：放行下跌段中的底部信号，拦截下跌中继"""
        # 1. MA60斜率不能崩盘式下跌（<-5%才否决）
        ma60_slope = r.ma60_slope_positive  # 基类计算的>0标记
        if not ma60_slope:
            # 斜率<=0时，进一步判断是否崩盘（需要访问原始数据）
            # 用ma20作为替代判断：ma20不能持续加速下跌
            pass  # 主判断在 _is_bottom_fishing_setup 已完成

        # 2. 信号数：抄底至少需要信号1(不创新低)+信号3(缩量)同时触发
        if not (r.signal_1_no_new_low and r.signal_3_volume_shrink):
            return False, "抄底需要信号1+信号3同时触发（不创新低+缩量企稳）"

        # 3. 信号数≥2即可（抄底不需要等5个信号）
        if r.signal_count < 2:
            return False, f"抄底信号仅{r.signal_count}个"

        # 4. 评分门槛（抄底放宽至50）
        if r.entry_score < 50:
            return False, f"抄底评分{r.entry_score}<50"

        # 5. 信号6否决
        if r.signal_6_pattern_action == "veto":
            return False, "抄底形态否决"

        return True, "通过"

    # ==================================================================
    # 工具方法
    # ==================================================================

    @staticmethod
    def _calc_atr(h, l, c, period=14) -> float:
        if len(c) < period + 1:
            return 0.0
        high = h.iloc[-period:]
        low = l.iloc[-period:]
        close_prev = c.shift(1).iloc[-period:]
        tr = pd.concat([high - low, (high - close_prev).abs(),
                        (low - close_prev).abs()], axis=1).max(axis=1)
        return float(tr.mean())

    @staticmethod
    def _calc_rsi(c, period=6) -> float:
        if len(c) < period + 1:
            return 50.0
        delta = c.diff()
        gain = delta.clip(lower=0).tail(period).mean()
        loss = (-delta.clip(upper=0)).tail(period).mean()
        if loss == 0:
            return 100.0
        if gain == 0:
            return 0.0
        return float(100 - 100 / (1 + gain / loss))

    @staticmethod
    def _ma_slope(c, period=60, lookback=5) -> float:
        """均线斜率（近N日变化率）"""
        ma = c.rolling(period).mean()
        if len(ma) < lookback + 1:
            return 0.0
        return float((ma.iloc[-1] / ma.iloc[-lookback] - 1) if ma.iloc[-lookback] > 0 else 0.0)

    # ==================================================================
    # 历史信号遍历（用于回测）
    # ==================================================================

    def evaluate_history(self, df) -> list[dict]:
        """遍历DataFrame历史，逐日输出信号评估"""
        results = []
        for i in range(60, len(df)):
            window = df.iloc[:i+1].copy()
            sr = self.evaluate_signals(window, symbol="")
            results.append({
                "date": str(df.index[i])[:10],
                "signal_count": sr.signal_count,
                "signals": sr.triggered_signals(),
                "entry_score": sr.entry_score,
                "strategy_type": sr.strategy_type,
                "is_valid": self.is_valid_entry(sr)[0],
                "reason": self.is_valid_entry(sr)[1] if not self.is_valid_entry(sr)[0] else "通过",
                "rsi_6": round(sr.rsi_6, 1),
                "ma5_deviation": round(sr.ma5_deviation * 100, 1),
                "volume_ratio": round(sr.volume_ratio, 2),
            })
        return results
