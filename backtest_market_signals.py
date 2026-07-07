"""
大盘趋势判断 + 个股操作信号 回测脚本
数据源: Tushare Pro
回测区间: 2024-01-02 ~ 2026-06-08
"""
import tushare as ts
import pandas as pd
import numpy as np
from datetime import datetime

TUSHARE_TOKEN = "23651a8611b00bf491c7378d81d0bc6265543153530194be989e6ada"
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()


# ============================================================
# 数据获取
# ============================================================

def fetch_index_daily():
    """上证指数日K线"""
    df = pro.index_daily(ts_code='000001.SH', start_date='20230601', end_date='20260608')
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    for col in ['open', 'high', 'low', 'close', 'vol', 'amount']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.sort_values('trade_date').reset_index(drop=True)
    return df


def fetch_northbound_flow():
    """北向资金净流入"""
    df = pro.moneyflow_hsgt(start_date='20230601', end_date='20260608')
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values('trade_date').reset_index(drop=True)
    # north_money 单位万元，转为亿元
    df['north_money'] = pd.to_numeric(df['north_money'], errors='coerce')
    df['north_net'] = df['north_money'] / 10000
    return df[['trade_date', 'north_net']]


def fetch_margin_data():
    """融资融券余额（上交所+深交所合计）"""
    df = pro.margin(start_date='20230601', end_date='20260608')
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    # 合并沪深
    for col in ['rzye', 'rzmre', 'rzche']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    agg = df.groupby('trade_date').agg(
        rzye=('rzye', 'sum'),      # 融资余额
        rzmre=('rzmre', 'sum'),    # 融资买入额
        rzche=('rzche', 'sum'),    # 融资偿还额
    ).reset_index()
    agg = agg.sort_values('trade_date').reset_index(drop=True)
    return agg


def fetch_limit_counts():
    """涨跌停家数（逐日获取，有速率限制所以取样）"""
    dates = pro.trade_cal(exchange='SSE', start_date='20240101', end_date='20260608')
    trade_dates = dates[dates['is_open'] == 1]['cal_date'].tolist()

    results = []
    for d in trade_dates:
        try:
            ll = pro.limit_list_d(trade_date=d)
            if ll is not None and len(ll) > 0:
                up = len(ll[ll['limit'] == 'U'])
                down = len(ll[ll['limit'] == 'D'])
            else:
                up, down = 0, 0
            results.append({'trade_date': pd.to_datetime(d), 'limit_up': up, 'limit_down': down})
        except Exception:
            results.append({'trade_date': pd.to_datetime(d), 'limit_up': 0, 'limit_down': 0})
        # tushare限流：每分钟约200次，稳妥起见不加sleep（采样够用）

    return pd.DataFrame(results)


# ============================================================
# 信号计算
# ============================================================

def calculate_signals(idx_df, north_df, margin_df):
    """
    构建5信号系统

    数据对齐后，计算以下指标:
    - MA5, MA20, MA60: 均线系统
    - HV20, HV60: 历史波动率
    - 主力净流入趋势 (用北向资金替代)
    - 融资余额变化率
    - 涨跌比 (用指数涨跌幅近似)
    """
    df = idx_df.copy()

    # === 均线 ===
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()

    # === 均线方向 ===
    df['ma20_up'] = df['ma20'] > df['ma20'].shift(5)
    df['ma5_flat'] = (df['ma5'] - df['ma5'].shift(3)).abs() / df['ma5'].shift(3) < 0.005

    # === 波动率 ===
    df['ret'] = df['close'].pct_change()
    df['hv20'] = df['ret'].rolling(20).std() * np.sqrt(252)
    df['hv60'] = df['ret'].rolling(60).std() * np.sqrt(252)
    df['vol_expansion'] = df['hv20'] > df['hv60']

    # === 成交量 ===
    df['vol_ma20'] = df['vol'].rolling(20).mean()
    df['vol_shrink'] = df['vol'] < df['vol_ma20'] * 0.6  # 地量
    df['vol_surge'] = df['vol'] > df['vol_ma20'] * 1.3    # 放量

    # === OBV ===
    df['obv'] = (np.sign(df['ret']) * df['vol']).cumsum()
    df['obv_ma20'] = df['obv'].rolling(20).mean()

    # === OBV底背离 ===
    df['price_new_low'] = df['close'] < df['close'].rolling(20).min().shift(1)
    df['obv_not_new_low'] = df['obv'] > df['obv'].rolling(20).min().shift(1)
    df['obv_divergence'] = df['price_new_low'] & df['obv_not_new_low']

    # === 涨跌幅 ===
    df['pct_chg'] = df['close'].pct_change() * 100

    # === 融资余额变化 ===
    if margin_df is not None and len(margin_df) > 0:
        margin_df = margin_df.copy()
        margin_df['rzye_chg'] = margin_df['rzye'].pct_change()
        margin_df['rzye_ma5'] = margin_df['rzye_chg'].rolling(5).mean()
        df = df.merge(margin_df[['trade_date', 'rzye', 'rzye_chg', 'rzye_ma5']],
                      on='trade_date', how='left')
    else:
        df['rzye'] = np.nan
        df['rzye_chg'] = np.nan
        df['rzye_ma5'] = np.nan

    # === 北向资金 ===
    if north_df is not None and len(north_df) > 0:
        north_df = north_df.copy()
        north_df['north_ma5'] = north_df['north_net'].rolling(5).mean()
        north_df['north_sum5'] = north_df['north_net'].rolling(5).sum()
        df = df.merge(north_df[['trade_date', 'north_net', 'north_ma5', 'north_sum5']],
                      on='trade_date', how='left')
    else:
        df['north_net'] = np.nan
        df['north_ma5'] = np.nan
        df['north_sum5'] = np.nan

    # === 综合信号评分 (0-100, 越高越看多) ===
    score = pd.Series(50.0, index=df.index)  # 基准50

    # 均线趋势 (±15)
    score += np.where(df['ma20_up'], 8, -8)
    score += np.where(df['close'] > df['ma20'], 4, -4)
    score += np.where(df['close'] > df['ma60'], 3, -3)

    # 波动率 (±8)
    score += np.where(df['vol_expansion'], -5, 4)

    # 成交量 (±10)
    score += np.where(df['vol_shrink'] & (score < 45), 8, 0)  # 低位地量=看多
    score += np.where(df['vol_surge'] & (score > 65), -8, 0)  # 高位放量=看空
    score += np.where(df['vol_surge'] & (score < 45), 6, 0)   # 低位放量=止跌

    # OBV背离 (±8)
    score += np.where(df['obv_divergence'], 8, 0)

    # 北向资金 (±12)
    score += np.where(df['north_sum5'] > 30, 6, 0)    # 5日净流入>30亿
    score += np.where(df['north_sum5'] < -30, -6, 0)   # 5日净流出>30亿

    # 融资余额 (±6)
    score += np.where(df['rzye_ma5'] > 0.0005, 4, 0)
    score += np.where(df['rzye_ma5'] < -0.0005, -4, 0)

    # 限制在0-100
    df['score'] = score.clip(0, 100)

    # === 5信号判定 ===
    df['signal'] = '中性'

    # 避险: score < 30
    df.loc[df['score'] < 30, 'signal'] = '避险'

    # 减仓: score 30-42
    df.loc[(df['score'] >= 30) & (df['score'] < 42), 'signal'] = '减仓'

    # 止跌: score 42-52 且 (OBV背离 或 地量 或 均线走平)
    df.loc[(df['score'] >= 42) & (df['score'] < 52) &
           (df['obv_divergence'] | df['vol_shrink'] | df['ma5_flat']), 'signal'] = '止跌'

    # 低吸: score 52-68 且北向5日净流入
    df.loc[(df['score'] >= 52) & (df['score'] < 68) &
           (df['north_sum5'] > 0), 'signal'] = '低吸'

    # 反弹: score > 68 且 (放量 或 北向大幅流入)
    df.loc[(df['score'] > 68) & (df['vol_surge'] | (df['north_sum5'] > 50)), 'signal'] = '反弹'

    return df


# ============================================================
# 回测引擎
# ============================================================

def backtest(df, initial_capital=1000000):
    """
    回测逻辑:
    - 低吸/反弹信号 → 次日开盘买入
    - 减仓/避险信号 → 次日开盘卖出
    - 止跌信号 → 观望（等待低吸确认）
    - 持仓期间每日计算浮动盈亏
    """
    df = df.copy()
    df['next_open'] = df['open'].shift(-1)

    capital = initial_capital
    position = 0  # 持有股数
    entry_price = 0
    trades = []
    equity_curve = []

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        date = row['trade_date']
        price = row['close']

        # 当前权益
        equity = capital + position * price
        equity_curve.append({'date': date, 'equity': equity, 'signal': prev['signal']})

        # 执行交易（基于前一日信号）
        if prev['signal'] in ('低吸', '反弹') and position == 0:
            # 买入: 次日开盘价，全仓
            buy_price = row['open']
            shares = int(capital / buy_price / 100) * 100  # 整百股
            if shares > 0:
                cost = shares * buy_price
                capital -= cost
                position = shares
                entry_price = buy_price
                trades.append({
                    'date': date, 'action': '买入', 'price': buy_price,
                    'shares': shares, 'signal': prev['signal']
                })

        elif prev['signal'] in ('减仓', '避险') and position > 0:
            # 卖出: 次日开盘价，全部卖出
            sell_price = row['open']
            revenue = position * sell_price
            capital += revenue
            pnl = (sell_price - entry_price) / entry_price * 100
            trades.append({
                'date': date, 'action': '卖出', 'price': sell_price,
                'shares': position, 'signal': prev['signal'],
                'pnl_pct': round(pnl, 2)
            })
            position = 0
            entry_price = 0

    # 最终清仓
    if position > 0:
        final_price = df.iloc[-1]['close']
        capital += position * final_price
        pnl = (final_price - entry_price) / entry_price * 100
        trades.append({
            'date': df.iloc[-1]['trade_date'], 'action': '清仓', 'price': final_price,
            'shares': position, 'signal': '到期', 'pnl_pct': round(pnl, 2)
        })
        position = 0

    return pd.DataFrame(trades), pd.DataFrame(equity_curve)


# ============================================================
# 绩效分析
# ============================================================

def analyze_performance(trades_df, equity_df, initial_capital=1000000):
    """计算回测绩效指标"""
    sell_trades = trades_df[trades_df['action'].isin(['卖出', '清仓'])].copy()

    if len(sell_trades) == 0:
        return "无交易记录"

    total_trades = len(sell_trades)
    win_trades = len(sell_trades[sell_trades['pnl_pct'] > 0])
    lose_trades = len(sell_trades[sell_trades['pnl_pct'] <= 0])
    win_rate = win_trades / total_trades * 100

    avg_win = sell_trades[sell_trades['pnl_pct'] > 0]['pnl_pct'].mean() if win_trades > 0 else 0
    avg_lose = sell_trades[sell_trades['pnl_pct'] <= 0]['pnl_pct'].mean() if lose_trades > 0 else 0
    profit_loss_ratio = abs(avg_win / avg_lose) if avg_lose != 0 else float('inf')

    total_return = (sell_trades['pnl_pct'] / 100 + 1).prod() - 1
    max_pnl = sell_trades['pnl_pct'].max()
    min_pnl = sell_trades['pnl_pct'].min()

    # 最大回撤
    if len(equity_df) > 0:
        equity_df['peak'] = equity_df['equity'].cummax()
        equity_df['drawdown'] = (equity_df['equity'] - equity_df['peak']) / equity_df['peak']
        max_drawdown = equity_df['drawdown'].min() * 100
    else:
        max_drawdown = 0

    # 年化收益
    if len(equity_df) > 0:
        days = (equity_df['date'].iloc[-1] - equity_df['date'].iloc[0]).days
        annual_return = ((1 + total_return) ** (365 / max(days, 1)) - 1) * 100
    else:
        annual_return = 0

    # 基准收益（买入持有）
    benchmark_return = (trades_df.iloc[-1]['price'] if len(trades_df) > 0 else 0)
    # 用equity曲线的首尾计算
    if len(equity_df) > 0:
        # 找到第一次买入前的资金
        first_buy_idx = equity_df[equity_df['signal'].isin(['低吸', '反弹'])].index
        if len(first_buy_idx) > 0:
            benchmark_start = equity_df.iloc[0]['equity']
            benchmark_end = equity_df.iloc[-1]['equity']
            # 简单基准：起始资金到最后权益
            bench_return = (benchmark_end - initial_capital) / initial_capital * 100
        else:
            bench_return = 0
    else:
        bench_return = 0

    # 按信号分组统计
    signal_stats = sell_trades.groupby('signal').agg(
        count=('pnl_pct', 'count'),
        avg_pnl=('pnl_pct', 'mean'),
        win_rate=('pnl_pct', lambda x: (x > 0).sum() / len(x) * 100)
    ).round(2)

    report = f"""
{'='*60}
                大盘趋势信号 回测绩效报告
{'='*60}

【基本信息】
  回测区间: {equity_df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {equity_df['date'].iloc[-1].strftime('%Y-%m-%d')}
  初始资金: {initial_capital:,.0f} 元
  最终权益: {equity_df['equity'].iloc[-1]:,.0f} 元

【交易统计】
  总交易次数: {total_trades}
  盈利次数:   {win_trades}
  亏损次数:   {lose_trades}
  胜率:       {win_rate:.1f}%

【收益指标】
  平均盈利:   {avg_win:.2f}%
  平均亏损:   {avg_lose:.2f}%
  盈亏比:     {profit_loss_ratio:.2f}
  累计收益:   {total_return*100:.2f}%
  年化收益:   {annual_return:.2f}%
  最大单笔盈利: {max_pnl:.2f}%
  最大单笔亏损: {min_pnl:.2f}%

【风险指标】
  最大回撤:   {max_drawdown:.2f}%

【按信号分组】
{signal_stats.to_string()}

【交易明细】
{sell_trades[['date','action','price','signal','pnl_pct']].to_string(index=False)}
{'='*60}
"""
    return report


# ============================================================
# 主程序
# ============================================================

if __name__ == '__main__':
    print("正在获取数据...")

    # 1. 获取数据
    idx_df = fetch_index_daily()
    print(f"  上证指数: {len(idx_df)} 行 ({idx_df['trade_date'].iloc[0].date()} ~ {idx_df['trade_date'].iloc[-1].date()})")

    north_df = fetch_northbound_flow()
    print(f"  北向资金: {len(north_df)} 行")

    margin_df = fetch_margin_data()
    print(f"  融资融券: {len(margin_df)} 行")

    # 2. 计算信号
    print("\n正在计算信号...")
    df = calculate_signals(idx_df, north_df, margin_df)

    # 信号分布
    signal_counts = df['signal'].value_counts()
    print("\n信号分布:")
    for sig, cnt in signal_counts.items():
        print(f"  {sig}: {cnt} 天 ({cnt/len(df)*100:.1f}%)")

    # 3. 回测
    print("\n正在回测...")
    trades_df, equity_df = backtest(df)
    print(f"  交易次数: {len(trades_df[trades_df['action'].isin(['卖出','清仓'])])}")

    # 4. 绩效分析
    report = analyze_performance(trades_df, equity_df)
    print(report)

    # 5. 保存详细数据
    df.to_csv('backtest_signals.csv', index=False, encoding='utf-8-sig')
    trades_df.to_csv('backtest_trades.csv', index=False, encoding='utf-8-sig')
    print("详细数据已保存: backtest_signals.csv, backtest_trades.csv")
