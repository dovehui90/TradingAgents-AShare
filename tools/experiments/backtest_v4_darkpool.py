"""v4暗盘策略回测 —— 基于资金流向的机构行为预测
逐笔拆单检测依赖当日AKShare数据，历史不可得。
回测用Tushare moneyflow日数据(免费历史)，验证核心逻辑：
机构逆势操作(净买+价跌 或 净卖+价涨) → 次日反转概率
"""
import os, sys
os.environ.pop('HTTP_PROXY', None)
os.environ.pop('HTTPS_PROXY', None)
import tushare as ts
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

ts.set_token('23651a8611b00bf491c7378d81d0bc6265543153530194be989e6ada')
pro = ts.pro_api()

# ====== 配置 ======
SYMBOLS = ['001203.SZ', '000001.SZ', '600519.SH', '300750.SZ', '002594.SZ']
NAMES = ['大中矿业', '平安银行', '贵州茅台', '宁德时代', '比亚迪']
START = '20250101'
END = '20260610'

# ====== 获取数据 ======
results = []

for sym, name in zip(SYMBOLS, NAMES):
    print(f'\n--- {name} {sym} ---')

    # 日K线
    daily = pro.daily(ts_code=sym, start_date=START, end_date=END)
    if daily.empty:
        print('  无日线数据，跳过')
        continue
    daily = daily.sort_values('trade_date').reset_index(drop=True)
    daily['pct_chg'] = daily['pct_chg'].astype(float)
    daily['close'] = daily['close'].astype(float)
    daily['open'] = daily['open'].astype(float)

    # 资金流向
    mf = pro.moneyflow(ts_code=sym, start_date=START, end_date=END)
    if mf.empty:
        print('  无资金流向数据，跳过')
        continue
    mf = mf.sort_values('trade_date').reset_index(drop=True)

    merged = daily.merge(mf, on='trade_date', suffixes=('_d', '_mf'))
    if merged.empty:
        continue

    for i, row in merged.iterrows():
        inst_buy = row['buy_lg_amount'] + row['buy_elg_amount']
        inst_sell = row['sell_lg_amount'] + row['sell_elg_amount']
        inst_net = inst_buy - inst_sell
        total = inst_buy + inst_sell + row['buy_md_amount'] + row['sell_md_amount'] + row['buy_sm_amount'] + row['sell_sm_amount']
        inst_pct = (inst_buy + inst_sell) / total * 100 if total > 0 else 0
        price_up = row['pct_chg'] > 0
        price_down = row['pct_chg'] < 0

        # v4信号规则
        signal = 0  # -2到+2
        reason = []

        # 维度一：机构参与度
        if inst_net > 0 and price_down:
            signal += 2
            reason.append('机构逆势净买')
        elif inst_net > 0 and price_up:
            signal += 1
            reason.append('机构顺势净买')
        elif inst_net < 0 and price_up:
            signal -= 2
            reason.append('机构逆势净卖')
        elif inst_net < 0 and price_down:
            signal -= 1
            reason.append('机构顺势净卖')

        # 维度二：尾盘异动 (用日线代理：全天跌幅但收盘高于开盘一半以上 → 尾盘有回拉)
        if price_down and row['close'] > row['open'] * 0.995:
            signal += 1 if inst_net > 0 else (-1 if inst_net < 0 else 0)

        # 维度三代理：机构参与度异常高(>40%) + 价格微幅波动(<1%) → 可能是暗盘拆单行为
        if inst_pct > 40 and abs(row['pct_chg']) < 1.0:
            if inst_net > 0:
                signal += 1
                reason.append('高机构参与+滞涨(疑似暗盘买)')
            elif inst_net < 0:
                signal -= 1
                reason.append('高机构参与+滞跌(疑似暗盘卖)')

        # 次日收益
        next_idx = i + 1
        ret_1d = merged.iloc[next_idx]['pct_chg'] if next_idx < len(merged) else None
        ret_3d = merged.iloc[min(i+3, len(merged)-1)]['pct_chg'] if next_idx < len(merged) else None
        ret_5d = merged.iloc[min(i+5, len(merged)-1)]['pct_chg'] if next_idx < len(merged) else None

        results.append({
            'symbol': sym, 'name': name, 'date': row['trade_date'],
            'pct_chg': row['pct_chg'], 'inst_net_wan': inst_net / 10000,
            'inst_pct': inst_pct, 'signal': signal,
            'reason': ' | '.join(reason) if reason else '--',
            'ret_1d': ret_1d, 'ret_3d': ret_3d, 'ret_5d': ret_5d,
        })

df = pd.DataFrame(results)
if df.empty:
    print('无有效数据')
    sys.exit(0)

# ====== 回测统计 ======
print(f'\n{"="*60}')
print(f'  v4策略回测: {len(SYMBOLS)}只股票, {START}-{END}')
print(f'  总样本: {len(df)}个交易日')
print(f'{"="*60}')

# 按信号分组
strong_long = df[df['signal'] >= 3]
weak_long = df[(df['signal'] >= 1) & (df['signal'] <= 2)]
neutral = df[df['signal'] == 0]
weak_short = df[(df['signal'] <= -1) & (df['signal'] >= -2)]
strong_short = df[df['signal'] <= -3]

# 简化为多空
df['direction'] = df['signal'].apply(lambda x: '多' if x > 0 else ('空' if x < 0 else '中'))
long_sig = df[df['signal'] > 0]
short_sig = df[df['signal'] < 0]

def win_rate(series):
    return (series > 0).sum() / len(series) * 100 if len(series) > 0 else 0

def avg_ret(series):
    return series.mean() if len(series) > 0 else 0

print(f'\n--- 信号分布 ---')
print(f'  强烈偏多(>=3): {len(strong_long)}天 ({len(strong_long)/len(df)*100:.1f}%)')
print(f'  偏多(1~2):     {len(weak_long)}天 ({len(weak_long)/len(df)*100:.1f}%)')
print(f'  中性(0):       {len(neutral)}天 ({len(neutral)/len(df)*100:.1f}%)')
print(f'  偏空(-1~-2):   {len(weak_short)}天 ({len(weak_short)/len(df)*100:.1f}%)')
print(f'  强烈偏空(<=-3):{len(strong_short)}天 ({len(strong_short)/len(df)*100:.1f}%)')

print(f'\n--- 次日胜率 ---')
print(f'  强烈偏多: {win_rate(strong_long["ret_1d"]):.0f}% 均值{avg_ret(strong_long["ret_1d"]):+.2f}%  ({len(strong_long)}样本)')
print(f'  偏多:     {win_rate(weak_long["ret_1d"]):.0f}% 均值{avg_ret(weak_long["ret_1d"]):+.2f}%  ({len(weak_long)}样本)')
print(f'  全部偏多: {win_rate(long_sig["ret_1d"]):.0f}% 均值{avg_ret(long_sig["ret_1d"]):+.2f}%  ({len(long_sig)}样本)')
print(f'  中性:     {win_rate(neutral["ret_1d"]):.0f}% 均值{avg_ret(neutral["ret_1d"]):+.2f}%  ({len(neutral)}样本)')
print(f'  全部偏空: {win_rate(short_sig["ret_1d"]):.0f}% 均值{avg_ret(short_sig["ret_1d"]):+.2f}%  ({len(short_sig)}样本)')
print(f'  偏空:     {win_rate(weak_short["ret_1d"]):.0f}% 均值{avg_ret(weak_short["ret_1d"]):+.2f}%  ({len(weak_short)}样本)')
print(f'  强烈偏空: {win_rate(strong_short["ret_1d"]):.0f}% 均值{avg_ret(strong_short["ret_1d"]):+.2f}%  ({len(strong_short)}样本)')

print(f'\n--- 分层收益(T+1/T+3/T+5) ---')
for label, subset in [('强烈偏多', strong_long), ('偏多', weak_long), ('偏空', weak_short), ('强烈偏空', strong_short)]:
    r1 = avg_ret(subset['ret_1d'])
    r3_tot = avg_ret(subset['ret_3d'])
    r5_tot = avg_ret(subset['ret_5d'])
    print(f'  {label}: T+1 {r1:+.2f}%  T+3 {r3_tot:+.2f}%  T+5 {r5_tot:+.2f}%  (n={len(subset)})')

print(f'\n--- 逐只股票 ---')
for sym, name in zip(SYMBOLS, NAMES):
    sub = df[df['symbol'] == sym]
    long_s = sub[sub['signal'] > 0]
    short_s = sub[sub['signal'] < 0]
    print(f'  {name}: 偏多信号{len(long_s)}次 胜率{win_rate(long_s["ret_1d"]):.0f}% | 偏空信号{len(short_s)}次 胜率{win_rate(short_s["ret_1d"]):.0f}%')

# ====== 核心检验：机构逆势信号 ======
print(f'\n--- 核心信号: 机构逆势净买(inst_net>0 & pct<0) ---')
contrarian_buy = df[(df['inst_net_wan'] > 0) & (df['pct_chg'] < 0)]
contrarian_sell = df[(df['inst_net_wan'] < 0) & (df['pct_chg'] > 0)]

print(f'  逆势净买: {len(contrarian_buy)}次, T+1胜率{win_rate(contrarian_buy["ret_1d"]):.0f}% {avg_ret(contrarian_buy["ret_1d"]):+.2f}%')
print(f'  逆势净卖: {len(contrarian_sell)}次, T+1胜率{win_rate(contrarian_sell["ret_1d"]):.0f}% {avg_ret(contrarian_sell["ret_1d"]):+.2f}%')

# 基准 (所有交易日简单平均)
baseline_win = win_rate(df['ret_1d'])
baseline_ret = avg_ret(df['ret_1d'])
print(f'\n  基准(全部样本次日): 胜率{baseline_win:.0f}% 均值{baseline_ret:+.2f}%')

print(f'\n{"="*60}')
print(f'  [说明]')
print(f'  回测基于Tushare moneyflow日数据(历史免费)')
print(f'  v4逐笔拆单部分无法回测(仅当日AKShare数据)')
print(f'  此处验证v4核心逻辑: 机构逆势操作→次日反转')
print(f'{"="*60}')
