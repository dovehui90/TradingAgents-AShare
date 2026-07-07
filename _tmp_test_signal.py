"""
测试布林乖离反转信号：对比 LLB / LB / 自定义阈值 下 is_cross_lp 触发的次数和位置
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np
from tradingagents.indicators import fetch_realtime_data
from tradingagents.indicators.bollinger_deviation import calculate_bollinger_deviation

def test_signals(symbol: str, days: int = 250):
    print(f"=== {symbol} 布林乖离信号测试 ===\n")
    df = fetch_realtime_data(symbol, days=days, period="daily")
    print(f"数据范围: {df.index[0]} ~ {df.index[-1]}, 共 {len(df)} 条")

    result = calculate_bollinger_deviation(df)

    close = result['close'].astype(float)
    open_ = result['open'].astype(float)
    mccd = result['mccd'].values
    llb = result['llb'].values
    lb = result['lb'].values
    ub = result['ub'].values
    uub = result['uub'].values

    # 当前逻辑：MCCD 上穿 LLB
    cross_llb = (mccd > llb) & (np.roll(mccd, 1) <= np.roll(llb, 1))
    cross_llb[0] = False

    # 改为上穿 LB
    cross_lb = (mccd > lb) & (np.roll(mccd, 1) <= np.roll(lb, 1))
    cross_lb[0] = False

    # 新增：MCCD 从负值区回穿到中线上方 (中线约=0 即MA20附近)
    cross_zero = (mccd > 0) & (np.roll(mccd, 1) <= 0)
    cross_zero[0] = False

    # 顶部警示（不变）
    is_warning = (mccd > uub) & ((close < open_) | (close < np.roll(close, 1)))
    is_warning[0] = False

    dates = result.index

    # === 汇总 ===
    print(f"\n{'阈值':<22} {'触发次数':>8}")
    print("-" * 32)
    print(f"{'LLB (2.33x极端下轨)':<22} {np.sum(cross_llb):>8}")
    print(f"{'LB (1.618x斐波下轨)':<22} {np.sum(cross_lb):>8}")
    print(f"{'零线 (MCCD>0)':<22} {np.sum(cross_zero):>8}")
    print(f"{'顶部警示 (MCCD>UUB)':<22} {np.sum(is_warning):>8}")

    # === 最近触发点对比 ===
    print(f"\n{'日期':<14} {'close':>8} {'MCCD/万':>12} {'LB/万':>10} {'LLB/万':>10} {'cross_LLB':>9} {'cross_LB':>9}")
    print("-" * 82)
    for i in range(max(0, len(result) - 60), len(result)):
        d = str(dates[i])[:10]
        cl = f"{close.iloc[i]:.2f}"
        mv = mccd[i] / 1e4
        lv = lb[i] / 1e4
        lv2 = llb[i] / 1e4 if not np.isnan(llb[i]) else np.nan
        mv_s = f"{mv:>10.1f}" if not np.isnan(mv) else "       NaN"
        lv_s = f"{lv:>8.1f}" if not np.isnan(lv) else "     NaN"
        lv2_s = f"{lv2:>8.1f}" if not np.isnan(lv2) else "     NaN"
        flags = ""
        if cross_llb[i]: flags += " ⬆LLB"
        if cross_lb[i]: flags += " ⬆LB"
        if cross_zero[i]: flags += " ⬆ZERO"
        if is_warning[i]: flags += " ⚠"
        print(f"{d:<14} {cl:>8} {mv_s:>12} {lv_s:>10} {lv2_s:>10} {'  Y' if cross_llb[i] else '   ':<9} {'  Y' if cross_lb[i] else '   ':<9}{flags}")

    # === 找到所有触发 cross_lb 但未触发 cross_llb 的点（这些就是 LLB 太严漏掉的） ===
    missed = [(i, dates[i]) for i in range(len(result)) if cross_lb[i] and not cross_llb[i]]
    if missed:
        print(f"\nLB 触发而 LLB 未触发的点（共 {len(missed)} 个，最近 10 个）：")
        for i, d in missed[-10:]:
            mv = mccd[i] / 1e4
            lv = lb[i] / 1e4
            lv2 = llb[i] / 1e4
            print(f"  {str(d)[:10]}  MCCD={mv:.1f}万  LB={lv:.1f}万  LLB={lv2:.1f}万  close={close.iloc[i]:.2f}")

if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "000815.SZ"
    test_signals(sym)
