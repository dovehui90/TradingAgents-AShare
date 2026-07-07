"""
大盘智能分析系统 - 金银手指 + 智能图谱 还原测试
用 tushare moneyflow 近似替代 TDX Level-2 数据
标的：大中矿业 (600938) + 上证指数 (1A0001)
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


# ============================================================
# 数据获取
# ============================================================
def fetch_stock_moneyflow(symbol: str, days: int = 730) -> pd.DataFrame:
    """获取个股资金流向（小单/中单/大单/超大单）"""
    import tushare as ts
    token = "23651a8611b00bf491c7378d81d0bc6265543153530194be989e6ada"
    ts.set_token(token)
    pro = ts.pro_api()

    if not symbol.endswith(('.SH', '.SZ')):
        suffix = '.SH' if symbol.startswith(('5', '6', '9')) else '.SZ'
        ts_code = symbol + suffix
    else:
        ts_code = symbol

    end = datetime.now().strftime('%Y%m%d')
    start = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')

    df = pro.moneyflow(ts_code=ts_code, start_date=start, end_date=end)
    if df is None or df.empty:
        print(f"无法获取 {symbol} 资金流数据")
        sys.exit(1)

    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values('trade_date').set_index('trade_date')
    return df


def fetch_index_kline(days: int = 730) -> pd.DataFrame:
    """获取上证指数日K"""
    import tushare as ts
    token = "23651a8611b00bf491c7378d81d0bc6265543153530194be989e6ada"
    ts.set_token(token)
    pro = ts.pro_api()

    end = datetime.now().strftime('%Y%m%d')
    start = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')

    df = pro.index_daily(ts_code='000001.SH', start_date=start, end_date=end)
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values('trade_date').set_index('trade_date')
    return df[['open', 'high', 'low', 'close', 'vol']]


def fetch_stock_kline(symbol: str, days: int = 730) -> pd.DataFrame:
    """获取个股前复权日K"""
    import tushare as ts
    token = "23651a8611b00bf491c7378d81d0bc6265543153530194be989e6ada"
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
        print(f"无法获取 {symbol} K线数据")
        sys.exit(1)
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values('trade_date').set_index('trade_date')
    if 'vol' in df.columns and 'volume' not in df.columns:
        df = df.rename(columns={'vol': 'volume'})
    return df[['open', 'high', 'low', 'close', 'volume']]


# ============================================================
# 指标计算
# ============================================================
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calc_gold_silver_finger(mf: pd.DataFrame) -> pd.DataFrame:
    """
    金银手指：基于小单买卖量交叉
    B1 = 小单买入量 (buy_sm_vol)
    B2 = 小单卖出量 (sell_sm_vol)
    金手指: B1<B2 且前一日 B1>B2 (小单从净流入→净流出, 散户不再抄底)
    银手指: B1>B2 且前一日 B1<B2 (小单从净流出→净流入, 散户开始接盘)
    """
    b1 = mf['buy_sm_vol']
    b2 = mf['sell_sm_vol']

    gold = (b1 < b2) & (b1.shift(1) >= b2.shift(1))
    silver = (b1 > b2) & (b1.shift(1) <= b2.shift(1))

    # 净流入判断: b1 > b2 → 净流入
    net_inflow = b1 > b2

    return pd.DataFrame({
        'b1': b1, 'b2': b2,
        'net_inflow': net_inflow,
        'gold_finger': gold,
        'silver_finger': silver,
    }, index=mf.index)


def calc_smart_chart(idx_df: pd.DataFrame) -> pd.DataFrame:
    """
    智能图谱：基于大盘价格和资金流综合打分
    还原 az 评分体系
    """
    c1 = idx_df['close']
    m34 = c1.rolling(34).mean()
    m5 = c1.rolling(5).mean()

    # 用大盘资金流的净流入天数近似 r5, r6
    # r5:=COUNT(大单净差BB>0,5) — 这里用收盘价>开盘价近似
    bullish_day = (c1 > idx_df['open']).astype(int)
    r5 = bullish_day.rolling(5).sum()
    r6 = bullish_day.rolling(6).sum()

    # 评分体系还原
    a1 = (c1 < c1.shift(2) * 1.0200).astype(int)
    a2 = (c1 < c1.shift(2) * 1.0050).astype(int)
    a3 = (c1 < c1.shift(2) * 0.985).astype(int)   # 修正 0.0985 → 0.985
    a4 = (c1 < c1.shift(2) * 0.970).astype(int)   # 修正 0.0970 → 0.970

    # DIFF/DIFF2 用 r5 近似
    diff_approx = r5.rolling(2).mean() - r5.rolling(4).mean()
    diff2_approx = r5.rolling(6).mean() - r5.rolling(12).mean()

    a5 = (diff_approx > 0).astype(int) * 2
    a6 = (diff2_approx > 0).astype(int) * 2
    a7 = (c1 > m34).astype(int) * 2
    a8 = (c1 > m5).astype(int) * 2
    a9 = (r5 > 3).astype(int) * 2
    a10 = (r6 > 3).astype(int)

    az = a1 + a2 + a3 + a4 + a5 + a6 + a7 + a8 + a9 + a10

    green = pd.Series(0, index=idx_df.index, dtype=int)
    red = pd.Series(0, index=idx_df.index, dtype=int)

    for i in range(len(idx_df)):
        if c1.iloc[i] < m5.iloc[i]:
            green.iloc[i] = 1
        elif az.iloc[i] > 2.5:
            red.iloc[i] = 1
        else:
            green.iloc[i] = 1

    # 阳谱/阴谱: 滚动窗口内红区占比 vs 绿区占比
    window = 20
    yang_pct = red.rolling(window).sum() / window * 100
    yin_pct = green.rolling(window).sum() / window * 100

    return pd.DataFrame({
        'close': c1, 'm5': m5, 'm34': m34,
        'az': az, 'red': red, 'green': green,
        'yang_pct': yang_pct, 'yin_pct': yin_pct,
    }, index=idx_df.index)


def calc_signals(idx_df, smart_chart, gs_finger):
    """计算交易信号：止跌、低吸、反弹"""
    c1 = smart_chart['close']
    green = smart_chart['green']
    red = smart_chart['red']
    gold = gs_finger['gold_finger']
    silver = gs_finger['silver_finger']
    silver_qj = gs_finger['net_inflow']  # 银手指区间: b1>b2

    # szcl/szch/szzl/szzh
    szcl = (green.shift(1) == 1) & (green == 1)
    szch = (red.shift(1) == 1) & (red == 1)
    szzl = (red.shift(1) == 1) & (green == 1)  # 转绿
    szzh = (green.shift(1) == 1) & (red == 1)   # 转红

    # 为绿天数
    zlts = pd.Series(0, index=idx_df.index, dtype=int)
    for i in range(1, len(idx_df)):
        if szzh.iloc[i] or szch.iloc[i]:
            count = 0
            for j in range(i - 1, -1, -1):
                if green.iloc[j] == 1:
                    count += 1
                else:
                    break
            zlts.iloc[i] = count
        elif green.iloc[i] == 1:
            zlts.iloc[i] = zlts.iloc[i - 1] + 1

    # 止跌: 简化版（无法获取 HZC，用 r5 近似吸筹）
    bullish_ratio = (c1 > c1.rolling(5).mean()).rolling(5).sum() / 5
    stop_decline = (szzl) & (bullish_ratio > 0.3) & (silver)
    # 进一步过滤：价格确实有下跌
    price_down = c1 < c1.shift(1)
    stop_decline = stop_decline & price_down

    # 低吸：转红 + 金银手指
    buy_low = (szzh) & (gold | silver)

    # 反弹：转绿后持续绿且有企稳迹象
    green_days = zlts
    bounce = szcl & (green_days >= 3) & (green_days <= 12) & (c1.pct_change() > -0.005)

    return pd.DataFrame({
        'szcl': szcl, 'szch': szch, 'szzl': szzl, 'szzh': szzh,
        'stop_decline': stop_decline, 'buy_low': buy_low, 'bounce': bounce,
        'zlts': zlts,
    }, index=idx_df.index)


# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 65)
    print("大盘智能分析系统还原测试 — 大中矿业 (600938)")
    print("=" * 65)

    # 获取数据
    print("\n获取数据中...")
    stock_mf = fetch_stock_moneyflow('600938', days=730)
    print(f"  个股资金流: {len(stock_mf)} 条")

    idx_df = fetch_index_kline(days=730)
    print(f"  上证指数: {len(idx_df)} 条")

    stock_kline = fetch_stock_kline('600938', days=730)
    print(f"  个股K线: {len(stock_kline)} 条")

    # 对齐日期
    common_dates = stock_mf.index.intersection(idx_df.index).intersection(stock_kline.index)
    stock_mf = stock_mf.loc[common_dates]
    idx_df = idx_df.loc[common_dates]
    stock_kline = stock_kline.loc[common_dates]
    print(f"  对齐后: {len(common_dates)} 个交易日")

    # 计算指标
    gs = calc_gold_silver_finger(stock_mf)
    sc = calc_smart_chart(idx_df)
    sig = calc_signals(idx_df, sc, gs)

    # === 统计 ===
    gold_count = gs['gold_finger'].sum()
    silver_count = gs['silver_finger'].sum()

    print(f"\n{'=' * 65}")
    print("金银手指统计 (2年)")
    print(f"{'=' * 65}")
    print(f"  金手指: {gold_count} 次")
    print(f"  银手指: {silver_count} 次")
    print(f"  净流入天数: {gs['net_inflow'].sum()} ({gs['net_inflow'].mean()*100:.1f}%)")

    # === 逐条金银手指 ===
    print(f"\n{'=' * 65}")
    print("金手指明细")
    print(f"{'=' * 65}")
    for d in gs[gs['gold_finger']].index:
        price = stock_kline.loc[d, 'close']
        b1 = gs.loc[d, 'b1']
        b2 = gs.loc[d, 'b2']
        print(f"  {d.date()}  个股收盘={price:.2f}  买={b1} 卖={b2}")

    print(f"\n{'=' * 65}")
    print("银手指明细")
    print(f"{'=' * 65}")
    for d in gs[gs['silver_finger']].index:
        price = stock_kline.loc[d, 'close']
        b1 = gs.loc[d, 'b1']
        b2 = gs.loc[d, 'b2']
        print(f"  {d.date()}  个股收盘={price:.2f}  买={b1} 卖={b2}")

    # === 金银手指后N日涨跌 ===
    print(f"\n{'=' * 65}")
    print("金银手指后N日涨跌统计")
    print(f"{'=' * 65}")
    for hold_days in [1, 3, 5]:
        for finger_type, finger_mask in [('金手指', gs['gold_finger']), ('银手指', gs['silver_finger'])]:
            returns = []
            for d in gs[finger_mask].index:
                idx = stock_kline.index.get_loc(d)
                if idx + hold_days < len(stock_kline):
                    future_p = stock_kline['close'].iloc[idx + hold_days]
                    curr_p = stock_kline['close'].iloc[idx]
                    returns.append((future_p / curr_p - 1) * 100)
            if returns:
                avg_r = np.mean(returns)
                win_rate = sum(1 for r in returns if (r > 0 if finger_type == '金手指' else r < 0)) / len(returns) * 100
                print(f"  {finger_type} → {hold_days}日: 平均{'涨' if avg_r>0 else '跌'}{abs(avg_r):.2f}%  "
                      f"{'上涨' if finger_type=='金手指' else '下跌'}率={win_rate:.1f}% ({len(returns)}次)")

    # === 智能图谱 ===
    print(f"\n{'=' * 65}")
    print("智能图谱统计")
    print(f"{'=' * 65}")
    print(f"  红区天数: {sc['red'].sum()} ({sc['red'].mean()*100:.1f}%)")
    print(f"  绿区天数: {sc['green'].sum()} ({sc['green'].mean()*100:.1f}%)")

    # 阳谱/阴谱（最近20日滚动占比）
    print(f"\n  阳谱/阴谱 (最近17个交易日，20日窗口):")
    recent = sc.dropna(subset=['yang_pct']).tail(17)
    dates_str = "  日期    "
    yang_str = "  阳谱    "
    yin_str = "  阴谱    "
    for d in recent.index:
        dates_str += f" {d.strftime('%m%d')}"
        yang_str += f" {recent.loc[d, 'yang_pct']:4.0f}%"
        yin_str += f" {recent.loc[d, 'yin_pct']:4.0f}%"
    print(dates_str)
    print(yang_str)
    print(yin_str)

    # === 交易信号 ===
    print(f"\n{'=' * 65}")
    print("交易信号统计")
    print(f"{'=' * 65}")
    print(f"  止跌信号: {sig['stop_decline'].sum()} 次")
    print(f"  低吸信号: {sig['buy_low'].sum()} 次")
    print(f"  反弹信号: {sig['bounce'].sum()} 次")

    for signal_name, mask in [('止跌', sig['stop_decline']), ('低吸', sig['buy_low']), ('反弹', sig['bounce'])]:
        signal_dates = sig[mask].index
        if len(signal_dates) > 0:
            print(f"\n  {signal_name}信号明细:")
            for d in signal_dates:
                price = stock_kline.loc[d, 'close']
                idx_pos = stock_kline.index.get_loc(d)
                # 5日后涨跌
                if idx_pos + 5 < len(stock_kline):
                    future = stock_kline['close'].iloc[idx_pos + 5]
                    pnl = (future / price - 1) * 100
                    print(f"    {d.date()}  价格={price:.2f}  5日后={future:.2f} ({'+' if pnl>0 else ''}{pnl:.2f}%)")
                else:
                    print(f"    {d.date()}  价格={price:.2f}")

    # === 信号配对回测 ===
    print(f"\n{'=' * 65}")
    print("信号回测（金手指买→银手指卖）")
    print(f"{'=' * 65}")
    trades = []
    position = None
    for i in range(len(stock_kline)):
        date = stock_kline.index[i]
        close = stock_kline['close'].iloc[i]

        if gs['gold_finger'].iloc[i] and position is None:
            position = {'entry_date': date, 'entry_price': close}
        elif gs['silver_finger'].iloc[i] and position is not None:
            pnl = (close / position['entry_price'] - 1) * 100
            trades.append({
                'entry_date': position['entry_date'],
                'entry_price': position['entry_price'],
                'exit_date': date,
                'exit_price': close,
                'pnl_pct': round(pnl, 2),
                'holding_days': (date - position['entry_date']).days,
            })
            position = None

    if trades:
        wins = [t for t in trades if t['pnl_pct'] > 0]
        losses = [t for t in trades if t['pnl_pct'] <= 0]
        win_rate = len(wins) / len(trades) * 100

        for t in trades:
            tag = "+" if t['pnl_pct'] > 0 else ""
            print(f"  {t['entry_date'].date()} → {t['exit_date'].date()}  "
                  f"买{t['entry_price']:.2f}→卖{t['exit_price']:.2f}  "
                  f"{tag}{t['pnl_pct']}%  持{t['holding_days']}天")

        print(f"\n  共{len(trades)}笔  胜率={win_rate:.1f}% ({len(wins)}胜/{len(losses)}负)")
        avg_pnl = np.mean([t['pnl_pct'] for t in trades])
        print(f"  平均盈亏={'+' if avg_pnl>0 else ''}{avg_pnl:.2f}%  平均持仓{np.mean([t['holding_days'] for t in trades]):.0f}天")
    else:
        print("  无完整配对交易")

    # === 当前状态 ===
    print(f"\n{'=' * 65}")
    print("当前状态 (最新交易日)")
    print(f"{'=' * 65}")
    last_date = stock_kline.index[-1]
    last_sc = sc.iloc[-1]
    last_gs = gs.iloc[-1]
    print(f"  日期: {last_date.date()}")
    print(f"  上证收盘: {last_sc['close']:.2f}")
    print(f"  智能图谱: {'红区(偏多)' if last_sc['red'] else '绿区(偏空)'} az={last_sc['az']:.1f}")
    print(f"  个股收盘: {stock_kline['close'].iloc[-1]:.2f}")
    print(f"  小单净流入: {'是' if last_gs['net_inflow'] else '否'} (买{last_gs['b1']:.0f} 卖{last_gs['b2']:.0f})")
    if last_gs['gold_finger']:
        print(f"  >>> 今日出现金手指！")
    elif last_gs['silver_finger']:
        print(f"  >>> 今日出现银手指！")


if __name__ == '__main__':
    main()
