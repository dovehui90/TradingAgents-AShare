import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 获取大中矿业数据
symbol = "001260.SZ"
end_date = datetime.now().strftime('%Y-%m-%d')
start_date = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')

print(f"获取 {symbol} 数据 ({start_date} ~ {end_date})...")
ticker = yf.Ticker(symbol)
df = ticker.history(start=start_date, end=end_date)

if df.empty:
    print("无法获取数据，尝试使用yfinance直接下载...")
    df = yf.download(symbol, start=start_date, end=end_date)

print(f"获取到 {len(df)} 条数据")
print(df.head())

# 公式参数
N = 10

# 计算指标
df['MA10'] = df['Close'].rolling(window=N).mean()

# X_1: 距离上次收盘价上穿10日均线的天数
cross_above = (df['Close'] > df['MA10']) & (df['Close'].shift(1) <= df['MA10'].shift(1))
df['X_1'] = 0
last_cross_idx = -1
for i in range(len(df)):
    if cross_above.iloc[i]:
        last_cross_idx = i
    if last_cross_idx >= 0:
        df.iloc[i, df.columns.get_loc('X_1')] = i - last_cross_idx

# X_2: 缩量洗盘条件
# VOL<=HHV(VOL,6)/2 AND EVERY(CLOSE>MA(CLOSE,N),X_1) AND LLV(CLOSE,1)>MA(CLOSE,N)
df['HHV_VOL_6'] = df['Volume'].rolling(window=6).max()
df['X_2'] = False
for i in range(N, len(df)):
    x1 = df['X_1'].iloc[i]
    if x1 > 0:
        # 检查EVERY(CLOSE>MA(CLOSE,N),X_1) - 从i-x1到i的所有收盘价都在均线上方
        check_range = range(max(0, i-x1), i+1)
        every_above = all(df['Close'].iloc[j] > df['MA10'].iloc[j] for j in check_range)
        # LLV(CLOSE,1) > MA(CLOSE,N) - 前一日最低价在均线上方
        prev_low_above = df['Low'].iloc[i-1] > df['MA10'].iloc[i] if i > 0 else False
        # VOL<=HHV(VOL,6)/2
        vol_shrink = df['Volume'].iloc[i] <= df['HHV_VOL_6'].iloc[i] / 2

        df.iloc[i, df.columns.get_loc('X_2')] = vol_shrink and every_above and prev_low_above

# X_3: VOL>REF(VOL,1) AND VOL<LLV(VOL,5)*5 AND CLOSE>OPEN
df['LLV_VOL_5'] = df['Volume'].rolling(window=5).min()
df['X_3'] = (df['Volume'] > df['Volume'].shift(1)) & \
            (df['Volume'] < df['LLV_VOL_5'] * 5) & \
            (df['Close'] > df['Open'])

# X_4: VOL>=LLV(VOL,5)*5 AND CLOSE>OPEN
df['X_4'] = (df['Volume'] >= df['LLV_VOL_5'] * 5) & (df['Close'] > df['Open'])

# 信号统计
print("\n=== 信号统计 ===")
print(f"缩量洗盘(X_2): {df['X_2'].sum()} 次")
print(f"温和放量阳线(X_3): {df['X_3'].sum()} 次")
print(f"大阳线(X_4): {df['X_4'].sum()} 次")

# 回测缩量洗盘信号
print("\n=== 缩量洗盘信号回测 ===")
wash_signals = df[df['X_2']].copy()

if len(wash_signals) > 0:
    print(f"\n找到 {len(wash_signals)} 个缩量洗盘信号：")
    print("-" * 80)

    results = []
    for idx in wash_signals.index:
        signal_date = idx
        signal_price = df.loc[idx, 'Close']

        # 计算信号后5日、10日、20日收益
        signal_pos = df.index.get_loc(idx)
        returns = {}
        for days in [5, 10, 20]:
            if signal_pos + days < len(df):
                future_price = df['Close'].iloc[signal_pos + days]
                returns[days] = (future_price / signal_price - 1) * 100
            else:
                returns[days] = None

        results.append({
            '日期': signal_date.strftime('%Y-%m-%d'),
            '收盘价': round(signal_price, 2),
            '成交量': int(df.loc[idx, 'Volume']),
            '5日收益%': round(returns[5], 2) if returns[5] is not None else 'N/A',
            '10日收益%': round(returns[10], 2) if returns[10] is not None else 'N/A',
            '20日收益%': round(returns[20], 2) if returns[20] is not None else 'N/A',
        })

    results_df = pd.DataFrame(results)
    print(results_df.to_string(index=False))

    # 统计胜率
    valid_5d = [r for r in results if r['5日收益%'] != 'N/A']
    valid_10d = [r for r in results if r['10日收益%'] != 'N/A']
    valid_20d = [r for r in results if r['20日收益%'] != 'N/A']

    if valid_5d:
        win_5d = sum(1 for r in valid_5d if r['5日收益%'] > 0)
        print(f"\n5日胜率: {win_5d}/{len(valid_5d)} = {win_5d/len(valid_5d)*100:.1f}%")
        avg_5d = np.mean([r['5日收益%'] for r in valid_5d])
        print(f"5日平均收益: {avg_5d:.2f}%")

    if valid_10d:
        win_10d = sum(1 for r in valid_10d if r['10日收益%'] > 0)
        print(f"10日胜率: {win_10d}/{len(valid_10d)} = {win_10d/len(valid_10d)*100:.1f}%")
        avg_10d = np.mean([r['10日收益%'] for r in valid_10d])
        print(f"10日平均收益: {avg_10d:.2f}%")

    if valid_20d:
        win_20d = sum(1 for r in valid_20d if r['20日收益%'] > 0)
        print(f"20日胜率: {win_20d}/{len(valid_20d)} = {win_20d/len(valid_20d)*100:.1f}%")
        avg_20d = np.mean([r['20日收益%'] for r in valid_20d])
        print(f"20日平均收益: {avg_20d:.2f}%")
else:
    print("未找到缩量洗盘信号")

# 显示最近的信号
print("\n=== 最近信号位置 ===")
recent_signals = df[df['X_2'] | df['X_3'] | df['X_4']].tail(10)
print(recent_signals[['Close', 'Volume', 'X_2', 'X_3', 'X_4']].to_string())
