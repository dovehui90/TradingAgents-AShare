"""
牛熊线量化信号策略回测（独立脚本，不依赖项目代码）
测试标的：大中矿业
策略：三层滤网 + 回踩/反弹触发
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ============================================================
# 1. 获取数据（直接用 tushare）
# ============================================================
def fetch_data(symbol: str, days: int = 365) -> pd.DataFrame:
    """获取前复权日K数据"""
    import tushare as ts
    token = "23651a8611b00bf491c7378d81d0bc6265543153530194be989e6ada"
    ts.set_token(token)
    pro = ts.pro_api()

    # 转换代码
    if not symbol.endswith(('.SH', '.SZ')):
        suffix = '.SH' if symbol.startswith(('5', '6', '9')) else '.SZ'
        ts_code = symbol + suffix
    else:
        ts_code = symbol

    end = datetime.now().strftime('%Y%m%d')
    start = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')

    df = ts.pro_bar(ts_code=ts_code, adj='qfq', start_date=start, end_date=end)
    if df is None or df.empty:
        print(f"无法获取 {symbol} 数据")
        sys.exit(1)

    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values('trade_date').set_index('trade_date')
    df = df.rename(columns={
        'open': 'open', 'high': 'high', 'low': 'low',
        'close': 'close', 'vol': 'volume'
    })
    return df[['open', 'high', 'low', 'close', 'volume']]


# ============================================================
# 2. 指标计算（从项目代码移植，独立运行）
# ============================================================
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calc_orbit_line(df):
    """轨道线：自适应 EMA5"""
    sg1 = ema(df['high'], 5)   # 上轨
    xg1 = ema(df['low'], 5)    # 下轨

    close = df['close']
    cross_up = (close > sg1) & (close.shift(1) <= sg1.shift(1))
    cross_dn = (xg1 > close) & (xg1.shift(1) <= close.shift(1))

    cs = pd.Series(np.nan, index=df.index)
    cx = pd.Series(np.nan, index=df.index)
    last_up = np.nan
    last_dn = np.nan
    for i in range(len(df)):
        if cross_up.iloc[i]: last_up = 0
        if cross_dn.iloc[i]: last_dn = 0
        if not np.isnan(last_up):
            cs.iloc[i] = last_up
            last_up += 1
        if not np.isnan(last_dn):
            cx.iloc[i] = last_dn
            last_dn += 1

    dqzt = pd.Series(0, index=df.index)
    valid = cs.notna() & cx.notna()
    dqzt[valid] = np.where(cs[valid] < cx[valid], 1, np.where(cx[valid] < cs[valid], -1, 0))
    dqzt[cs.notna() & cx.isna()] = 1
    dqzt[cx.notna() & cs.isna()] = -1

    orbit = pd.Series(np.nan, index=df.index)
    orbit[dqzt < 0] = sg1[dqzt < 0]
    orbit[dqzt >= 0] = xg1[dqzt >= 0]

    return orbit, dqzt


def calc_decision_line(df):
    """决策线：EMA(X1, 39)"""
    x1 = (df['high'] + df['low'] + df['open'] + 2 * df['close']) / 5
    return ema(x1, 39)


def calc_bull_bear_line(df):
    """牛熊线：EMA(X1, 99)"""
    x1 = (df['high'] + df['low'] + df['open'] + 2 * df['close']) / 5
    return ema(x1, 99)


def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_atr(df, period=14):
    high = df['high']
    low = df['low']
    close = df['close']
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_position_index(df, period=14):
    """位置指标：滚动百分位"""
    hhv = df['high'].rolling(period).max()
    llv = df['low'].rolling(period).min()
    pos = (df['close'] - llv) / (hhv - llv) * 100
    return pos.ewm(span=5, adjust=False).mean()


def calc_boll(close, period=20, std_dev=2):
    """布林带"""
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return mid, upper, lower


def detect_stop_kline(df):
    """止跌K线：长下影/十字星/阳包阴"""
    body = (df['close'] - df['open']).abs()
    lower_shadow = df[['open', 'close']].min(axis=1) - df['low']
    upper_shadow = df['high'] - df[['open', 'close']].max(axis=1)
    amplitude = df['high'] - df['low']

    # 长下影：下影 > 实体×2
    long_lower = lower_shadow > body * 2
    # 十字星：实体 < 振幅×0.3
    doji = amplitude > 0.01 * df['close']  # 避免除零
    doji = doji & (body < amplitude * 0.3)
    # 阳包阴：今日阳线实体完全覆盖昨日阴线实体
    today_bullish = df['close'] > df['open']
    prev_bearish = df['close'].shift(1) < df['open'].shift(1)
    engulf = today_bullish & prev_bearish & \
             (df['close'] > df['open'].shift(1)) & \
             (df['open'] < df['close'].shift(1))

    return long_lower | doji | engulf


def detect_stop_up_kline(df):
    """止涨K线：长上影/阴包阳/十字星"""
    body = (df['close'] - df['open']).abs()
    upper_shadow = df['high'] - df[['open', 'close']].max(axis=1)
    amplitude = df['high'] - df['low']

    # 长上影：上影 > 实体×2
    long_upper = upper_shadow > body * 2
    # 十字星
    doji = amplitude > 0.01 * df['close']
    doji = doji & (body < amplitude * 0.3)
    # 阴包阳
    today_bearish = df['close'] < df['open']
    prev_bullish = df['close'].shift(1) > df['open'].shift(1)
    engulf = today_bearish & prev_bullish & \
             (df['open'] > df['close'].shift(1)) & \
             (df['close'] < df['open'].shift(1))

    return long_upper | doji | engulf


# ============================================================
# 3. 信号生成
# ============================================================
def generate_signals(df):
    """生成 BUY/SELL 信号"""
    df = df.copy()

    # 计算指标
    df['orbit'], df['orbit_dir'] = calc_orbit_line(df)
    df['decision'] = calc_decision_line(df)
    df['bull_bear'] = calc_bull_bear_line(df)
    df['rsi'] = calc_rsi(df['close'])
    df['atr'] = calc_atr(df)
    df['pos_idx'] = calc_position_index(df)
    df['boll_mid'], df['boll_ub'], df['boll_lb'] = calc_boll(df['close'])
    df['stop_kline'] = detect_stop_kline(df)
    df['stop_up_kline'] = detect_stop_up_kline(df)

    # 成交量
    df['vol_ma5'] = df['volume'].rolling(5).mean()
    df['vol_shrink'] = df['volume'] < df['vol_ma5'] * 0.7  # 缩量

    # 价格距轨道线
    df['dist_orbit'] = df['close'] - df['orbit']
    df['near_orbit'] = df['dist_orbit'].abs() <= df['atr'] * 1  # 距离 ≤ 1×ATR

    # 近3日是否回踩/反弹到轨道线附近
    df['near_orbit_3d'] = df['near_orbit'].rolling(3).max().fillna(0).astype(bool)

    # 近N日最高/最低
    df['high_20'] = df['high'].rolling(20).max()
    df['low_20'] = df['low'].rolling(20).min()
    df['pullback_pct'] = (df['high_20'] - df['close']) / df['high_20'] * 100

    # 信号
    df['buy_signal'] = False
    df['sell_signal'] = False
    df['confidence'] = 0

    for i in range(3, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]

        # ========== BUY 触发 ==========
        buy触发 = False
        信号类型 = ""

        # A. 顺势低吸：价格在轨道线上方 + 回踩到轨道线附近 + 止跌K线
        if (row['close'] > row['orbit'] and
            row['near_orbit_3d'] and
            row['stop_kline']):
            buy触发 = True
            信号类型 = "顺势低吸"

        # B. 超跌反弹：价格在轨道线下方 + 到支撑位 + 止跌K线 + 缩量 + 超卖
        elif (row['close'] < row['orbit'] and
              row['close'] <= row['decision'] * 1.02 and  # 接近决策线（支撑）
              row['stop_kline'] and
              row['vol_shrink'] and
              row['rsi'] < 35):
            buy触发 = True
            信号类型 = "超跌反弹"

        # ========== SELL 触发 ==========
        sell触发 = False

        # A. 顺势卖出：价格在轨道线下方 + 反弹到轨道线附近 + 止涨K线
        if (row['close'] < row['orbit'] and
            row['near_orbit_3d'] and
            row['stop_up_kline']):
            sell触发 = True
            信号类型 = "顺势卖出"

        # B. 超涨回落：价格在轨道线上方 + 到阻力位 + 止涨K线 + 超买
        elif (row['close'] > row['orbit'] and
              row['close'] >= row['boll_ub'] * 0.98 and  # 接近布林上轨
              row['stop_up_kline'] and
              row['rsi'] > 70):
            sell触发 = True
            信号类型 = "超涨回落"

        # ========== 置信度评分 ==========
        if buy触发 or sell触发:
            score = 50  # 基础分

            # 牛熊线层
            if buy触发:
                if row['close'] > row['bull_bear']: score += 15
                else: score -= 10
            else:
                if row['close'] < row['bull_bear']: score += 15
                else: score -= 10

            # 决策线层
            if buy触发:
                if row['close'] > row['decision']: score += 15
                else: score -= 10
            else:
                if row['close'] < row['decision']: score += 15
                else: score -= 10

            # 轨道线层
            if buy触发:
                if row['close'] > row['orbit']: score += 10
                else: score -= 5
            else:
                if row['close'] < row['orbit']: score += 10
                else: score -= 5

            # RSI 加减分
            if buy触发 and row['rsi'] < 30: score += 10
            if buy触发 and row['rsi'] > 70: score -= 10
            if sell触发 and row['rsi'] > 70: score += 10
            if sell触发 and row['rsi'] < 30: score -= 10

            # 信号类型加减分
            if 信号类型 in ("顺势低吸", "顺势卖出"): score += 10
            if 信号类型 in ("超跌反弹", "超涨回落"): score -= 10

            score = max(0, min(100, score))

            if buy触发:
                df.iloc[i, df.columns.get_loc('buy_signal')] = True
                df.iloc[i, df.columns.get_loc('confidence')] = score
            if sell触发:
                df.iloc[i, df.columns.get_loc('sell_signal')] = True
                df.iloc[i, df.columns.get_loc('confidence')] = score

    return df


# ============================================================
# 4. 回测
# ============================================================
def backtest(df, hold_days=5):
    """简单回测：BUY后持有N天，SELL后观望N天"""
    trades = []
    i = 0
    while i < len(df):
        if df['buy_signal'].iloc[i]:
            buy_date = df.index[i]
            buy_price = df['close'].iloc[i]
            target_idx = min(i + hold_days, len(df) - 1)
            sell_price = df['close'].iloc[target_idx]
            ret = (sell_price - buy_price) / buy_price * 100

            # 止损检查：期间最低价是否触发止损（buy_price - 2×ATR）
            atr = df['atr'].iloc[i]
            stop_loss = buy_price - 2 * atr
            min_low = df['low'].iloc[i+1:target_idx+1].min()
            stopped = min_low <= stop_loss

            trades.append({
                'type': 'BUY',
                'date': buy_date.strftime('%Y-%m-%d'),
                'price': round(buy_price, 2),
                'exit_price': round(sell_price, 2),
                'return_pct': round(ret, 2),
                'confidence': df['confidence'].iloc[i],
                'stopped': stopped,
            })
            i = target_idx + 1
        elif df['sell_signal'].iloc[i]:
            sell_date = df.index[i]
            sell_price = df['close'].iloc[i]
            target_idx = min(i + hold_days, len(df) - 1)
            buy_price = df['close'].iloc[target_idx]
            ret = (sell_price - buy_price) / sell_price * 100  # 做空收益

            trades.append({
                'type': 'SELL',
                'date': sell_date.strftime('%Y-%m-%d'),
                'price': round(sell_price, 2),
                'exit_price': round(buy_price, 2),
                'return_pct': round(ret, 2),
                'confidence': df['confidence'].iloc[i],
                'stopped': False,
            })
            i = target_idx + 1
        else:
            i += 1
    return trades


# ============================================================
# 5. 主程序
# ============================================================
if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else '600938'  # 大中矿业
    hold_days = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    print(f"=== 回测标的: {symbol} | 持仓周期: {hold_days}天 ===\n")

    # 获取数据
    df = fetch_data(symbol, days=500)
    print(f"数据范围: {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"共 {len(df)} 个交易日\n")

    # 生成信号
    df = generate_signals(df)

    # 统计信号
    buy_count = df['buy_signal'].sum()
    sell_count = df['sell_signal'].sum()
    print(f"BUY 信号: {buy_count} 次")
    print(f"SELL 信号: {sell_count} 次\n")

    # 回测
    trades = backtest(df, hold_days=hold_days)

    if not trades:
        print("无交易记录")
    else:
        print(f"{'类型':<6} {'日期':<12} {'价格':<10} {'出场价':<10} {'收益%':<10} {'置信度':<8} {'止损':<6}")
        print('-' * 70)
        for t in trades:
            stopped = '是' if t['stopped'] else '否'
            print(f"{t['type']:<6} {t['date']:<12} {t['price']:<10} {t['exit_price']:<10} {t['return_pct']:<10} {t['confidence']:<8} {stopped:<6}")

        # 统计
        buy_trades = [t for t in trades if t['type'] == 'BUY']
        sell_trades = [t for t in trades if t['type'] == 'SELL']

        print(f"\n=== 统计 ===")
        if buy_trades:
            buy_rets = [t['return_pct'] for t in buy_trades]
            buy_wins = sum(1 for r in buy_rets if r > 0)
            print(f"BUY: {len(buy_trades)}笔 | 胜率: {buy_wins/len(buy_trades)*100:.1f}% | 平均收益: {np.mean(buy_rets):.2f}% | 最大盈: {max(buy_rets):.2f}% | 最大亏: {min(buy_rets):.2f}%")
        if sell_trades:
            sell_rets = [t['return_pct'] for t in sell_trades]
            sell_wins = sum(1 for r in sell_rets if r > 0)
            print(f"SELL: {len(sell_trades)}笔 | 胜率: {sell_wins/len(sell_trades)*100:.1f}% | 平均收益: {np.mean(sell_rets):.2f}% | 最大盈: {max(sell_rets):.2f}% | 最大亏: {min(sell_rets):.2f}%")
