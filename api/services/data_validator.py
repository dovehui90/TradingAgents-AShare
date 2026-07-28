"""
数据验证器 - 确保进入分析的数据质量
"""

from typing import Tuple
import pandas as pd
from datetime import datetime


class DataValidator:
    """数据质量验证器"""

    @staticmethod
    def validate_tick_data(tick: pd.DataFrame, date: str) -> Tuple[bool, str]:
        """
        验证逐笔成交数据完整性

        Returns:
            (is_valid, error_message)
        """
        # 检查1：非空
        if tick is None or tick.empty:
            return False, "逐笔数据为空"

        # 检查2：成交量
        if tick['volume'].sum() == 0:
            return False, "总成交量为零"

        # 检查3：数据点数量
        if len(tick) < 100:
            return False, f"数据点过少({len(tick)}笔，正常应>1000笔)"

        # 检查4：时间序列单调性
        if 'time_dt' in tick.columns:
            if not tick['time_dt'].is_monotonic_increasing:
                return False, "时间序列非单调递增（数据乱序）"

        # 检查5：价格合理性
        if tick['price'].min() <= 0:
            return False, "价格包含非正值"

        price_range = tick['price'].max() - tick['price'].min()
        price_mean = tick['price'].mean()
        if price_range / price_mean > 0.15:  # 单日价格波动>15%
            return False, f"价格波动异常({price_range/price_mean*100:.1f}%)"

        # 检查6：日期匹配
        if 'time' in tick.columns and len(tick) > 0:
            # 提取第一个时间字符串的日期部分
            first_time = str(tick['time'].iloc[0])
            if len(first_time) >= 10:
                tick_date = first_time[:10]
                if tick_date != date:
                    return False, f"日期不匹配：期望{date}，实际{tick_date}"

        return True, "OK"

    @staticmethod
    def validate_moneyflow(mf: pd.DataFrame, date: str) -> Tuple[bool, str]:
        """验证资金流数据时效性"""
        if mf is None or mf.empty:
            return False, "资金流数据为空"

        # 检查日期
        latest_date = mf['trade_date'].max()
        expected_date = date.replace('-', '')

        if latest_date != expected_date:
            return False, f"数据不是最新（期望{expected_date}，实际{latest_date}）"

        # 检查必要字段
        required_fields = ['buy_sm_vol', 'sell_sm_vol', 'buy_lg_amount', 'sell_lg_amount']
        missing = [f for f in required_fields if f not in mf.columns]
        if missing:
            return False, f"缺少必要字段: {missing}"

        return True, "OK"

    @staticmethod
    def validate_k5(k5: pd.DataFrame, date: str) -> Tuple[bool, str]:
        """验证5分钟K线数据"""
        if k5 is None or k5.empty:
            return False, "5分钟K线数据为空"

        # 正常一天应有48根5分钟K线（240分钟 / 5）
        if len(k5) < 20:
            return False, f"K线数量过少({len(k5)}根，正常应>40根)"

        # 检查OHLC逻辑
        invalid_bars = (k5['high'] < k5['low']) | (k5['high'] < k5['close']) | (k5['low'] > k5['open'])
        if invalid_bars.any():
            return False, f"K线数据异常（{invalid_bars.sum()}根K线 high < low）"

        return True, "OK"


def validate_analysis_data(tick, mf_data, k5, date: str) -> dict:
    """
    综合验证所有数据源

    Returns:
        {
            'is_valid': bool,
            'errors': list,
            'warnings': list,
        }
    """
    errors = []
    warnings = []

    # 验证逐笔数据（关键）
    tick_valid, tick_msg = DataValidator.validate_tick_data(tick, date)
    if not tick_valid:
        errors.append(f"逐笔数据: {tick_msg}")

    # 验证资金流数据（重要但非关键）
    if mf_data is not None:
        mf_valid, mf_msg = DataValidator.validate_moneyflow(mf_data, date)
        if not mf_valid:
            warnings.append(f"资金流数据: {mf_msg}")

    # 验证K线数据（重要但非关键）
    if k5 is not None:
        k5_valid, k5_msg = DataValidator.validate_k5(k5, date)
        if not k5_valid:
            warnings.append(f"K线数据: {k5_msg}")

    return {
        'is_valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings,
    }
