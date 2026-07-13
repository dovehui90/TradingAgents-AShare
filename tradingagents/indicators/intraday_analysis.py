"""
分时图量价分析工具

基于PDF分时图形态：
- 脉冲建仓
- 冲击建仓
- 攻击建仓
- 试盘（向上/向下）
- 诱多（早盘/盘中/尾盘）
- 洗盘（强势/弱势）
- 承接/护盘
- 诱空
- 抢筹
- 拉升/出货

数据源：akshare stock_zh_a_hist_min_em（东方财富1分钟K线）
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class IntradaySignal:
    """分时图信号结果"""
    symbol: str = ""
    date: str = ""
    close: float = 0.0
    avg_price: float = 0.0
    change_pct: float = 0.0

    # 量能
    volume_up: bool = False       # 放量
    volume_down: bool = False     # 缩量
    volume_flat: bool = False     # 平量
    is_high_volume: bool = False  # 高量

    # 形态信号
    signal_pulse_accumulation: bool = False    # 脉冲建仓
    signal_impact_accumulation: bool = False   # 冲击建仓
    signal_attack_accumulation: bool = False   # 攻击建仓
    signal_test_up: bool = False               # 向上试盘
    signal_test_down: bool = False             # 向下试盘
    signal_lure_up_early: bool = False         # 早盘诱多
    signal_lure_up_mid: bool = False           # 盘中诱多
    signal_lure_up_end: bool = False           # 尾盘诱多
    signal_washout_strong: bool = False        # 强势洗盘
    signal_washout_weak: bool = False          # 弱势洗盘
    signal_support: bool = False               # 承接
    signal_protect: bool = False               # 护盘
    signal_lure_down: bool = False             # 诱空
    signal_snatch: bool = False                # 抢筹
    signal_rally: bool = False                 # 拉升
    signal_distribute: bool = False            # 出货

    # 评分
    buy_score: int = 0
    sell_score: int = 0
    action: str = "观望"  # "买入" / "卖出" / "观望"

    # 辅助
    avg_price_position: float = 0.5  # 当前价vs均价位置
    volume_ratio: float = 1.0        # 量比
    price_trend: str = "neutral"     # 价格趋势

    def to_dict(self) -> dict:
        return asdict(self)

    def buy_signals_list(self) -> list[str]:
        signals = []
        mapping = {
            "signal_pulse_accumulation": "脉冲建仓",
            "signal_impact_accumulation": "冲击建仓",
            "signal_attack_accumulation": "攻击建仓",
            "signal_test_up": "向上试盘",
            "signal_test_down": "向下试盘",
            "signal_lure_up_early": "早盘诱多",
            "signal_lure_up_mid": "盘中诱多",
            "signal_lure_up_end": "尾盘诱多",
            "signal_washout_strong": "强势洗盘",
            "signal_washout_weak": "弱势洗盘",
            "signal_support": "承接",
            "signal_protect": "护盘",
            "signal_lure_down": "诱空",
            "signal_snatch": "抢筹",
            "signal_rally": "拉升",
            "signal_distribute": "出货",
        }
        for attr, name in mapping.items():
            if getattr(self, attr, False):
                signals.append(name)
        return signals


def fetch_intraday_data(symbol: str, date: str = None) -> pd.DataFrame:
    """
    获取分时数据

    Args:
        symbol: 股票代码，如 '002051'
        date: 日期，如 '2026-07-10'，默认今天

    Returns:
        DataFrame with columns: 时间, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 均价
    """
    import akshare as ak

    if date is None:
        from datetime import datetime
        date = datetime.now().strftime('%Y-%m-%d')

    try:
        df = ak.stock_zh_a_hist_min_em(
            symbol=symbol,
            period='1',
            start_date=f'{date} 09:30:00',
            end_date=f'{date} 15:00:00'
        )
        if df is not None and len(df) > 0:
            df['时间'] = pd.to_datetime(df['时间'])
            return df
    except Exception as e:
        print(f"获取{symbol}分时数据失败: {e}")

    return pd.DataFrame()


def analyze_intraday(df: pd.DataFrame, symbol: str = "") -> IntradaySignal:
    """
    分析分时图量价关系

    Args:
        df: 分时数据DataFrame
        symbol: 股票代码

    Returns:
        IntradaySignal 信号结果
    """
    if df is None or len(df) < 10:
        return IntradaySignal(symbol=symbol)

    result = IntradaySignal(symbol=symbol)

    # 基础数据
    result.close = float(df['收盘'].iloc[-1])
    result.avg_price = float(df['均价'].iloc[-1]) if '均价' in df.columns else result.close

    # 涨跌幅（基于开盘价）
    open_price = float(df['开盘'].iloc[0])
    result.change_pct = (result.close / open_price - 1) * 100 if open_price > 0 else 0

    # 均价位置
    if result.avg_price > 0:
        result.avg_price_position = (result.close - result.avg_price) / result.avg_price * 100

    # 量能分析
    _analyze_volume(df, result)

    # 形态识别
    _detect_patterns(df, result)

    # 评分
    _score_signal(result)

    # 决策
    _decide_action(result)

    return result


def _analyze_volume(df: pd.DataFrame, r: IntradaySignal):
    """分析量能"""
    vol = df['成交量'].values

    if len(vol) < 10:
        return

    # 计算量能趋势
    vol_first_half = np.mean(vol[:len(vol)//2])
    vol_second_half = np.mean(vol[len(vol)//2:])

    if vol_second_half > vol_first_half * 1.2:
        r.volume_up = True
    elif vol_second_half < vol_first_half * 0.8:
        r.volume_down = True
    else:
        r.volume_flat = True

    # 判断是否高量
    vol_avg = np.mean(vol)
    if vol[-1] > vol_avg * 2:
        r.is_high_volume = True

    # 量比
    r.volume_ratio = vol[-1] / vol_avg if vol_avg > 0 else 1.0


def _detect_patterns(df: pd.DataFrame, r: IntradaySignal):
    """识别分时图形态"""
    close = df['收盘'].values
    high = df['最高'].values
    low = df['最低'].values
    vol = df['成交量'].values
    n = len(close)

    if n < 20:
        return

    # 计算关键指标
    open_price = close[0]
    current_price = close[-1]
    max_price = np.max(high)
    min_price = np.min(low)
    avg_price = np.mean(close)

    # 价格位置
    price_range = max_price - min_price
    if price_range > 0:
        current_position = (current_price - min_price) / price_range
    else:
        current_position = 0.5

    # ======== 建仓形态 ========

    # 1. 脉冲建仓：开盘后快速拉升，呈现脉冲结构
    if (current_price > open_price * 1.02 and  # 涨幅>2%
        np.std(np.diff(close[:n//3])) > np.std(np.diff(close)) * 1.5):  # 前1/3波动大
        r.signal_pulse_accumulation = True

    # 2. 冲击建仓：快速拉升后横盘，不破均价线
    if (current_price > open_price * 1.02 and  # 涨幅>2%
        np.min(close[n//2:]) > avg_price * 0.99):  # 后半段在均价线上方
        r.signal_impact_accumulation = True

    # 3. 攻击建仓：持续稳定拉升
    if (current_price > open_price * 1.03 and  # 涨幅>3%
        all(close[i] <= close[i+1] * 1.01 for i in range(n-10, n-1))):  # 尾盘稳定
        r.signal_attack_accumulation = True

    # ======== 试盘形态 ========

    # 4. 向上试盘：瞬间拉升后回落
    if (np.max(high[:n//3]) > avg_price * 1.03 and  # 前1/3有冲高
        current_price < np.max(high[:n//3]) * 0.98):  # 当前低于高点
        r.signal_test_up = True

    # 5. 向下试盘：瞬间打压后回升
    if (np.min(low[:n//3]) < avg_price * 0.97 and  # 前1/3有下探
        current_price > np.min(low[:n//3]) * 1.02):  # 当前高于低点
        r.signal_test_down = True

    # ======== 诱多形态 ========

    # 6. 早盘诱多：开盘拉升后回落
    if (n > 30 and
        np.max(close[:30]) > open_price * 1.02 and  # 开盘30分钟内冲高
        current_price < np.max(close[:30]) * 0.98):  # 当前回落
        r.signal_lure_up_early = True

    # 7. 盘中诱多：盘中突然拉升后回落
    mid_start = n // 3
    mid_end = 2 * n // 3
    if (mid_end - mid_start > 20 and
        np.max(close[mid_start:mid_end]) > avg_price * 1.02 and
        current_price < np.max(close[mid_start:mid_end]) * 0.98):
        r.signal_lure_up_mid = True

    # 8. 尾盘诱多：尾盘拉升
    if (n > 30 and
        close[-1] > close[-30] * 1.02 and  # 尾盘拉升>2%
        np.mean(vol[-10:]) > np.mean(vol) * 1.5):  # 尾盘放量
        r.signal_lure_up_end = True

    # ======== 洗盘形态 ========

    # 9. 强势洗盘：高开后持续回落，不破均价线
    if (open_price > avg_price * 1.01 and  # 高开
        np.min(close) > avg_price * 0.99):  # 不破均价线
        r.signal_washout_strong = True

    # 10. 弱势洗盘：平缓回落，缩量
    if (current_price < open_price * 0.99 and  # 下跌
        r.volume_down and  # 缩量
        np.max(high) - np.min(low) < avg_price * 0.03):  # 振幅小
        r.signal_washout_weak = True

    # ======== 承接/护盘 ========

    # 11. 承接：V型反转
    if (np.min(low) < avg_price * 0.97 and  # 有下探
        current_price > avg_price * 0.99 and  # 收回
        current_price > np.min(low) * 1.02):  # 反弹>2%
        r.signal_support = True

    # 12. 护盘：尾盘护住均价线
    if (current_price > avg_price * 0.99 and  # 在均价线上方
        np.min(close[-10:]) > avg_price * 0.99):  # 尾盘不破均价线
        r.signal_protect = True

    # ======== 诱空 ========

    # 13. 诱空：盘中下探后快速拉起
    if (np.min(low[n//3:2*n//3]) < avg_price * 0.97 and  # 盘中下探
        current_price > avg_price * 0.99 and  # 收回
        r.volume_up):  # 放量
        r.signal_lure_down = True

    # ======== 抢筹 ========

    # 14. 抢筹：持续放量上涨
    if (current_price > open_price * 1.02 and  # 涨幅>2%
        r.volume_up and  # 放量
        all(close[i] < close[i+1] for i in range(n-20, n-1))):  # 持续上涨
        r.signal_snatch = True

    # ======== 拉升/出货 ========

    # 15. 拉升：放量突破
    if (current_price > max_price * 0.98 and  # 接近最高点
        r.volume_up and  # 放量
        current_price > avg_price * 1.01):  # 在均价线上方
        r.signal_rally = True

    # 16. 出货：高位放量滞涨
    if (current_price < max_price * 0.98 and  # 不在最高点
        r.volume_up and  # 放量
        current_price < avg_price and  # 在均价线下方
        np.max(high) - current_price > price_range * 0.3):  # 回落幅度大
        r.signal_distribute = True


def _score_signal(r: IntradaySignal):
    """评分"""
    score = 0

    # 买入信号评分
    buy_signals = r.buy_signals_list()

    # 建仓形态
    if "脉冲建仓" in buy_signals:
        score += 15
    if "冲击建仓" in buy_signals:
        score += 20
    if "攻击建仓" in buy_signals:
        score += 25

    # 试盘形态
    if "向下试盘" in buy_signals:
        score += 15

    # 诱空
    if "诱空" in buy_signals:
        score += 20

    # 承接/护盘
    if "承接" in buy_signals:
        score += 15
    if "护盘" in buy_signals:
        score += 10

    # 抢筹
    if "抢筹" in buy_signals:
        score += 20

    # 拉升
    if "拉升" in buy_signals:
        score += 15

    # 量能加分
    if r.volume_up:
        score += 5
    if r.is_high_volume:
        score += 5

    # 均价线位置加分
    if r.avg_price_position > 0:
        score += 5

    r.buy_score = min(score, 100)

    # 卖出信号评分
    sell_score = 0
    if "早盘诱多" in buy_signals:
        sell_score += 20
    if "盘中诱多" in buy_signals:
        sell_score += 20
    if "尾盘诱多" in buy_signals:
        sell_score += 15
    if "出货" in buy_signals:
        sell_score += 25
    if "强势洗盘" in buy_signals and r.avg_price_position < 0:
        sell_score += 10

    r.sell_score = min(sell_score, 100)


def _decide_action(r: IntradaySignal):
    """决策"""
    buy_signals = r.buy_signals_list()

    # 买入条件
    if r.buy_score >= 40:
        critical_buy = {"冲击建仓", "攻击建仓", "诱空", "抢筹", "拉升"}
        if critical_buy.intersection(set(buy_signals)):
            r.action = "买入"
            return

    # 卖出条件
    if r.sell_score >= 30:
        critical_sell = {"出货", "早盘诱多", "盘中诱多"}
        if critical_sell.intersection(set(buy_signals)):
            r.action = "卖出"
            return

    r.action = "观望"


def analyze_stock_intraday(symbol: str, date: str = None) -> IntradaySignal:
    """分析单只股票分时图"""
    df = fetch_intraday_data(symbol, date)
    return analyze_intraday(df, symbol)


def analyze_multiple_stocks(symbols: list[str], date: str = None) -> list[IntradaySignal]:
    """批量分析多只股票"""
    results = []
    for symbol in symbols:
        signal = analyze_stock_intraday(symbol, date)
        results.append(signal)
    return results


def print_analysis_result(signal: IntradaySignal):
    """打印分析结果"""
    print(f"\n{'='*60}")
    print(f"{signal.symbol} 分时图分析")
    print(f"{'='*60}")
    print(f"收盘价: {signal.close:.2f}  均价: {signal.avg_price:.2f}  涨幅: {signal.change_pct:+.2f}%")
    print(f"均价位置: {signal.avg_price_position:+.2f}%  量比: {signal.volume_ratio:.2f}")

    print(f"\n【量能】")
    print(f"  放量: {'是' if signal.volume_up else '否'}  缩量: {'是' if signal.volume_down else '否'}  平量: {'是' if signal.volume_flat else '否'}")

    print(f"\n【信号】")
    buy_signals = signal.buy_signals_list()
    if buy_signals:
        print(f"  买入信号: {', '.join(buy_signals)}")
    else:
        print(f"  买入信号: 无")

    print(f"\n【评分】")
    print(f"  买入评分: {signal.buy_score}  卖出评分: {signal.sell_score}")
    print(f"  操作建议: {signal.action}")
