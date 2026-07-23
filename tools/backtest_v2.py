"""
牛熊线量化信号策略回测 V2
调整：放宽条件 + 趋势雷达 + 位置指标 + 动态出场
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ============================================================
# 1. 获取数据
# ============================================================
def fetch_data(symbol: str, days: int = 365) -> pd.DataFrame:
    import tushare as ts
    token = os.environ.get("TUSHARE_TOKEN", "")
    ts.set_token(token)
    pro = ts.pro_api()

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
    df = df.rename(columns={'vol': 'volume'})
    return df[['open', 'high', 'low', 'close', 'volume']]


# ============================================================
# 2. 指标计算
# ============================================================
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calc_orbit_line(df):
    sg1 = ema(df['high'], 5)
    xg1 = ema(df['low'], 5)
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

    # 轨道线方向（上升/下降）
    orbit_dir = orbit.diff()

    return orbit, dqzt, orbit_dir


def calc_decision_line(df):
    x1 = (df['high'] + df['low'] + df['open'] + 2 * df['close']) / 5
    return ema(x1, 39)


def calc_bull_bear_line(df):
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
    hhv = df['high'].rolling(period).max()
    llv = df['low'].rolling(period).min()
    pos = (df['close'] - llv) / (hhv - llv) * 100
    return pos.ewm(span=5, adjust=False).mean()


def calc_boll(close, period=20, std_dev=2):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return mid, upper, lower


def calc_radar(df):
    """主力趋势雷达"""
    df = df.reset_index(drop=True)
    h = np.array(df['high'], dtype=np.float64)
    l = np.array(df['low'], dtype=np.float64)
    c = np.array(df['close'], dtype=np.float64)
    v = np.array(df['volume'], dtype=np.float64) if 'volume' in df.columns else np.ones(len(c))
    n = len(c)

    min_val = np.full(n, np.nan)
    max_val = np.full(n, np.nan)
    for i in range(9, n):
        min_val[i] = np.nanmin(l[i-9:i+1])
    for i in range(24, n):
        max_val[i] = np.nanmax(h[i-24:i+1])

    range_val = max_val - min_val
    range_val[range_val == 0] = np.nan

    raw_wave = ((c - min_val) / range_val) * 4
    wave = _ema_np(raw_wave, 4)
    avg = _ema_np(wave, 3)

    info = np.zeros(n, dtype=int)
    info[1:] = (avg[1:] >= avg[:-1]).astype(int)
    strong = np.zeros(n, dtype=int)
    weak = np.zeros(n, dtype=int)
    vol_up = np.zeros(n, dtype=int)
    for i in range(19, n):
        strong[i] = 1 if c[i] > np.nanmean(c[i-19:i+1]) and c[i] > np.nanmean(c[i-4:i+1]) else 0
    for i in range(9, n):
        weak[i] = 1 if c[i] < np.nanmean(c[i-9:i+1]) and c[i] < np.nanmean(c[i-4:i+1]) else 0
    for i in range(4, n):
        vol_up[i] = 1 if v[i] > np.nanmean(v[i-4:i+1]) else 0

    info_prev1 = np.zeros(n, dtype=int); info_prev1[1:] = info[:-1]
    info_prev2 = np.zeros(n, dtype=int); info_prev2[2:] = info[:-2]
    info_prev3 = np.zeros(n, dtype=int); info_prev3[3:] = info[:-3]
    strong_prev1 = np.zeros(n, dtype=int); strong_prev1[1:] = strong[:-1]

    radar_buy = (
        (info == 1) & (info_prev1 == 0) &
        ((info_prev2 + info_prev3) == 0) &
        (avg < 0.5)
    )
    radar_sell = (
        (info == 1) & (info_prev1 == 0) &
        ((info_prev2 + info_prev3) == 0) &
        (strong == 1) & (strong_prev1 == 0) &
        (vol_up == 1)
    )
    radar_top = (
        (avg > 2) &
        (info == 0) & (info_prev1 == 1) &
        (info_prev2 == 1)
    )
    radar_down = (
        (info == 0) & (info_prev1 == 1) &
        (info_prev2 == 1) &
        (weak == 1) &
        (avg > 1)
    )

    return pd.DataFrame({
        'radar_buy': radar_buy,
        'radar_sell': radar_sell,
        'radar_top': radar_top,
        'radar_down': radar_down,
        'radar_avg': avg,
    }, index=df.index)


def _ema_np(arr, period):
    alpha = 2 / (period + 1)
    result = np.copy(arr)
    for i in range(1, len(arr)):
        if np.isnan(result[i]):
            continue
        if np.isnan(result[i-1]):
            continue
        result[i] = alpha * arr[i] + (1 - alpha) * result[i-1]
    return result


def detect_stop_kline(df):
    """止跌K线"""
    body = (df['close'] - df['open']).abs()
    lower_shadow = df[['open', 'close']].min(axis=1) - df['low']
    amplitude = df['high'] - df['low']
    long_lower = lower_shadow > body * 2
    doji = amplitude > 0.01 * df['close']
    doji = doji & (body < amplitude * 0.3)
    today_bullish = df['close'] > df['open']
    prev_bearish = df['close'].shift(1) < df['open'].shift(1)
    engulf = today_bullish & prev_bearish & \
             (df['close'] > df['open'].shift(1)) & \
             (df['open'] < df['close'].shift(1))
    return long_lower | doji | engulf


def detect_stop_up_kline(df):
    """止涨K线"""
    body = (df['close'] - df['open']).abs()
    upper_shadow = df['high'] - df[['open', 'close']].max(axis=1)
    amplitude = df['high'] - df['low']
    long_upper = upper_shadow > body * 2
    doji = amplitude > 0.01 * df['close']
    doji = doji & (body < amplitude * 0.3)
    today_bearish = df['close'] < df['open']
    prev_bullish = df['close'].shift(1) > df['open'].shift(1)
    engulf = today_bearish & prev_bullish & \
             (df['open'] > df['close'].shift(1)) & \
             (df['close'] < df['open'].shift(1))
    return long_upper | doji | engulf


# ============================================================
# 3. 信号生成 V2
# ============================================================
def generate_signals(df):
    df = df.copy()

    # 计算指标
    df['orbit'], df['orbit_dqzt'], df['orbit_dir'] = calc_orbit_line(df)
    df['decision'] = calc_decision_line(df)
    df['bull_bear'] = calc_bull_bear_line(df)
    df['rsi'] = calc_rsi(df['close'])
    df['atr'] = calc_atr(df)
    df['pos_idx'] = calc_position_index(df)
    df['boll_mid'], df['boll_ub'], df['boll_lb'] = calc_boll(df['close'])
    df['stop_kline'] = detect_stop_kline(df)
    df['stop_up_kline'] = detect_stop_up_kline(df)

    # 趋势雷达
    radar = calc_radar(df)
    df['radar_buy'] = radar['radar_buy'].values
    df['radar_sell'] = radar['radar_sell'].values
    df['radar_top'] = radar['radar_top'].values
    df['radar_down'] = radar['radar_down'].values
    df['radar_avg'] = radar['radar_avg'].values

    # 成交量
    df['vol_ma5'] = df['volume'].rolling(5).mean()
    df['vol_shrink'] = df['volume'] < df['vol_ma5'] * 0.7

    # 距轨道线距离
    df['dist_orbit'] = (df['close'] - df['orbit']).abs()
    df['near_orbit'] = df['dist_orbit'] <= df['atr'] * 1.5  # V2: 放宽到1.5倍ATR

    # 近5日是否靠近轨道线
    df['near_orbit_5d'] = df['near_orbit'].rolling(5).max().fillna(0).astype(bool)

    # 近20日高低点
    df['high_20'] = df['high'].rolling(20).max()
    df['low_20'] = df['low'].rolling(20).min()

    # 信号
    df['buy_signal'] = False
    df['sell_signal'] = False
    df['confidence'] = 0
    df['signal_type'] = ''

    for i in range(3, len(df)):
        row = df.iloc[i]

        # ========== BUY 触发 ==========
        buy触发 = False
        信号类型 = ""

        # A. 顺势低吸：价格在轨道线上方 + 回踩到轨道线附近（放宽）
        if row['close'] > row['orbit'] and row['near_orbit_5d']:
            buy触发 = True
            信号类型 = "顺势低吸"

        # B. 超跌反弹：价格在轨道线下方 + 止跌K线 + 缩量 + 超卖
        elif row['close'] < row['orbit'] and row['stop_kline'] and row['vol_shrink'] and row['rsi'] < 35:
            buy触发 = True
            信号类型 = "超跌反弹"

        # C. 趋势雷达底信号 + 价格在决策线上方
        elif row['radar_buy'] and row['close'] > row['decision']:
            buy触发 = True
            信号类型 = "雷达底部"

        # ========== SELL 触发 ==========
        sell触发 = False

        # A. 顺势卖出：价格在轨道线下方 + 反弹到轨道线附近
        if row['close'] < row['orbit'] and row['near_orbit_5d']:
            sell触发 = True
            信号类型 = "顺势卖出"

        # B. 超涨回落：价格在轨道线上方 + 止涨K线 + 超买
        elif row['close'] > row['orbit'] and row['stop_up_kline'] and row['rsi'] > 70:
            sell触发 = True
            信号类型 = "超涨回落"

        # C. 趋势雷达顶信号 + 价格在决策线下方
        elif row['radar_top'] and row['close'] < row['decision']:
            sell触发 = True
            信号类型 = "雷达顶部"

        # ========== 位置指标过滤 ==========
        if buy触发 and row['pos_idx'] >= 80:
            buy触发 = False  # 超买区不出BUY
        if sell触发 and row['pos_idx'] <= 20:
            sell触发 = False  # 超卖区不出SELL

        # ========== 置信度评分 ==========
        if buy触发 or sell触发:
            score = 50

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

            # RSI
            if buy触发 and row['rsi'] < 30: score += 10
            if buy触发 and row['rsi'] > 70: score -= 10
            if sell触发 and row['rsi'] > 70: score += 10
            if sell触发 and row['rsi'] < 30: score -= 10

            # 信号类型
            if 信号类型 in ("顺势低吸", "顺势卖出"): score += 10
            if 信号类型 in ("超跌反弹", "超涨回落"): score -= 5
            if 信号类型 in ("雷达底部", "雷达顶部"): score += 5

            # 成交量确认
            if buy触发 and row['vol_shrink']: score += 5
            if sell触发 and row['vol_shrink']: score += 5

            # 趋势雷达共振
            if buy触发 and row['radar_buy']: score += 10
            if sell触发 and row['radar_top']: score += 10

            score = max(0, min(100, score))

            if buy触发:
                df.iloc[i, df.columns.get_loc('buy_signal')] = True
                df.iloc[i, df.columns.get_loc('confidence')] = score
                df.iloc[i, df.columns.get_loc('signal_type')] = 信号类型
            if sell触发:
                df.iloc[i, df.columns.get_loc('sell_signal')] = True
                df.iloc[i, df.columns.get_loc('confidence')] = score
                df.iloc[i, df.columns.get_loc('signal_type')] = 信号类型

    return df


# ============================================================
# 4. 动态出场回测
# ============================================================
def backtest_dynamic(df, max_hold=10):
    """动态出场：BUY后跌破轨道线出，SELL后站上轨道线出，最多持有max_hold天"""
    trades = []
    i = 0
    while i < len(df):
        if df['buy_signal'].iloc[i]:
            entry_date = df.index[i]
            entry_price = df['close'].iloc[i]
            stop_loss = entry_price - 2 * df['atr'].iloc[i]

            # 动态出场：跌破轨道线 或 达到最大持仓天数
            exit_idx = i + 1
            while exit_idx < min(i + max_hold + 1, len(df)):
                row = df.iloc[exit_idx]
                # 止损
                if row['low'] <= stop_loss:
                    exit_price = stop_loss
                    exit_date = df.index[exit_idx]
                    break
                # 跌破轨道线
                if row['close'] < row['orbit'] and exit_idx > i + 1:
                    exit_price = row['close']
                    exit_date = df.index[exit_idx]
                    break
                exit_idx += 1
            else:
                exit_idx = min(exit_idx, len(df) - 1)
                exit_price = df['close'].iloc[exit_idx]
                exit_date = df.index[exit_idx]

            ret = (exit_price - entry_price) / entry_price * 100
            hold_days = (exit_date - entry_date).days

            trades.append({
                'type': 'BUY',
                'entry_date': entry_date.strftime('%Y-%m-%d'),
                'entry_price': round(entry_price, 2),
                'exit_date': exit_date.strftime('%Y-%m-%d'),
                'exit_price': round(exit_price, 2),
                'return_pct': round(ret, 2),
                'confidence': df['confidence'].iloc[i],
                'signal_type': df['signal_type'].iloc[i],
                'hold_days': hold_days,
            })
            i = exit_idx + 1

        elif df['sell_signal'].iloc[i]:
            entry_date = df.index[i]
            entry_price = df['close'].iloc[i]
            stop_loss = entry_price + 2 * df['atr'].iloc[i]

            # 动态出场：站上轨道线 或 达到最大持仓天数
            exit_idx = i + 1
            while exit_idx < min(i + max_hold + 1, len(df)):
                row = df.iloc[exit_idx]
                # 止损
                if row['high'] >= stop_loss:
                    exit_price = stop_loss
                    exit_date = df.index[exit_idx]
                    break
                # 站上轨道线
                if row['close'] > row['orbit'] and exit_idx > i + 1:
                    exit_price = row['close']
                    exit_date = df.index[exit_idx]
                    break
                exit_idx += 1
            else:
                exit_idx = min(exit_idx, len(df) - 1)
                exit_price = df['close'].iloc[exit_idx]
                exit_date = df.index[exit_idx]

            ret = (entry_price - exit_price) / entry_price * 100  # 做空收益
            hold_days = (exit_date - entry_date).days

            trades.append({
                'type': 'SELL',
                'entry_date': entry_date.strftime('%Y-%m-%d'),
                'entry_price': round(entry_price, 2),
                'exit_date': exit_date.strftime('%Y-%m-%d'),
                'exit_price': round(exit_price, 2),
                'return_pct': round(ret, 2),
                'confidence': df['confidence'].iloc[i],
                'signal_type': df['signal_type'].iloc[i],
                'hold_days': hold_days,
            })
            i = exit_idx + 1
        else:
            i += 1

    return trades


# ============================================================
# 5. 主程序
# ============================================================
if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else '600938'
    max_hold = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    start_date = sys.argv[3] if len(sys.argv) > 3 else '2025-12-11'

    print(f"=== 回测标的: {symbol} | 最大持仓: {max_hold}天 | 起始: {start_date} ===\n")

    df = fetch_data(symbol, days=500)
    df = generate_signals(df)
    df = df[df.index >= start_date]

    print(f"数据范围: {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"共 {len(df)} 个交易日\n")

    buy_count = df['buy_signal'].sum()
    sell_count = df['sell_signal'].sum()
    print(f"BUY 信号: {buy_count} 次")
    print(f"SELL 信号: {sell_count} 次\n")

    trades = backtest_dynamic(df, max_hold=max_hold)

    if not trades:
        print("无交易记录")
    else:
        buy_trades = [t for t in trades if t['type'] == 'BUY']
        sell_trades = [t for t in trades if t['type'] == 'SELL']

        print(f'--- BUY 交易 ({len(buy_trades)}笔) ---')
        if buy_trades:
            print(f'{"#":<3} {"入场日":<12} {"入场价":<8} {"出场日":<12} {"出场价":<8} {"收益%":<8} {"持仓天":<6} {"类型":<10} {"置信度":<6}')
            print('-' * 90)
            for idx, t in enumerate(buy_trades, 1):
                print(f'{idx:<3} {t["entry_date"]:<12} {t["entry_price"]:<8} {t["exit_date"]:<12} {t["exit_price"]:<8} {t["return_pct"]:<8} {t["hold_days"]:<6} {t["signal_type"]:<10} {t["confidence"]:<6}')

        print(f'\n--- SELL 交易 ({len(sell_trades)}笔) ---')
        if sell_trades:
            print(f'{"#":<3} {"入场日":<12} {"入场价":<8} {"出场日":<12} {"出场价":<8} {"收益%":<8} {"持仓天":<6} {"类型":<10} {"置信度":<6}')
            print('-' * 90)
            for idx, t in enumerate(sell_trades, 1):
                print(f'{idx:<3} {t["entry_date"]:<12} {t["entry_price"]:<8} {t["exit_date"]:<12} {t["exit_price"]:<8} {t["return_pct"]:<8} {t["hold_days"]:<6} {t["signal_type"]:<10} {t["confidence"]:<6}')

        print(f'\n=== 汇总 ===')
        if buy_trades:
            buy_rets = [t['return_pct'] for t in buy_trades]
            buy_wins = sum(1 for r in buy_rets if r > 0)
            buy_hold = [t['hold_days'] for t in buy_trades]
            print(f'BUY: {len(buy_trades)}笔 | 胜率: {buy_wins/len(buy_trades)*100:.1f}% | 平均收益: {np.mean(buy_rets):.2f}% | 总收益: {sum(buy_rets):.2f}%')
            print(f'     最大盈: {max(buy_rets):.2f}% | 最大亏: {min(buy_rets):.2f}% | 平均持仓: {np.mean(buy_hold):.1f}天')
        if sell_trades:
            sell_rets = [t['return_pct'] for t in sell_trades]
            sell_wins = sum(1 for r in sell_rets if r > 0)
            sell_hold = [t['hold_days'] for t in sell_trades]
            print(f'SELL: {len(sell_trades)}笔 | 胜率: {sell_wins/len(sell_trades)*100:.1f}% | 平均收益: {np.mean(sell_rets):.2f}% | 总收益: {sum(sell_rets):.2f}%')
            print(f'     最大盈: {max(sell_rets):.2f}% | 最大亏: {min(sell_rets):.2f}% | 平均持仓: {np.mean(sell_hold):.1f}天')
