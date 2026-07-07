"""
胜宏科技(300476) 39条规则回测脚本

对近1个月每个交易日运行LLM决策，对比次日&3日后实际走势，计算准确率。
"""

import os
import sys
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tradingagents.strategy.fact_engine import compute_facts
from tradingagents.strategy.llm_decision import run_decision


def fetch_data(symbol: str = "300476", days: int = 80) -> pd.DataFrame:
    """获取日K数据"""
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
    import tushare as ts
    token = os.environ.get("TUSHARE_TOKEN", "23651a8611b00bf491c7378d81d0bc6265543153530194be989e6ada")
    ts.set_token(token)
    pro = ts.pro_api()
    ts_code = f"{symbol}.{'SH' if symbol.startswith(('6','9')) else 'SZ'}"
    raw = pro.daily(ts_code=ts_code, start_date=start, end_date=end)
    raw["trade_date"] = pd.to_datetime(raw["trade_date"], format="%Y%m%d")
    raw = raw.set_index("trade_date").sort_index()
    df = raw[["open", "high", "low", "close", "vol"]].rename(columns={"vol": "volume"})
    df["volume"] = df["volume"] * 100
    print(f"[数据] {symbol} {len(df)}条 ({df.index[0].date()} ~ {df.index[-1].date()})")
    return df


def decision_to_direction(decision: str) -> int:
    """将决策文本映射为方向: +1看多, -1看空, 0中性"""
    bullish = {"加仓", "机会进场"}
    bearish = {"减仓", "清仓", "风险回避"}
    neutral = {"观望"}
    if decision in bullish:
        return 1
    if decision in bearish:
        return -1
    return 0


def main():
    symbol = "300476"
    name = "胜宏科技"

    # 获取市场状态
    from tradingagents.strategy.market_state import fetch_sh_index_data, classify_market_state, get_current_market_state
    sh_df = fetch_sh_index_data()
    sh_df = classify_market_state(sh_df)
    ms = get_current_market_state(sh_df)["state"]
    print(f"[市场] {ms}")

    # 获取股票数据
    df = fetch_data(symbol, days=80)
    facts_all = compute_facts(df, market_state=ms)

    # 回测参数
    lookback = 15       # 每次LLM看到的K线条数
    # 近1个月约22个交易日
    max_idx = len(facts_all) - 4  # 留3天验证远期收益
    min_idx = max(20, max_idx - 22)  # 最近22个交易日

    results = []
    total = max_idx - min_idx
    print(f"\n[回测] {symbol} {name} | 交易日 {facts_all.index[min_idx].date()} ~ {facts_all.index[max_idx-1].date()} | 共{total}天\n")

    for i in range(min_idx, max_idx):
        eval_date = facts_all.index[i]
        window = facts_all.iloc[i - lookback + 1 : i + 1].copy()
        next_day = facts_all.iloc[i + 1]
        day3 = facts_all.iloc[min(i + 3, len(facts_all) - 1)]

        # 跑LLM决策
        try:
            result = run_decision(window, symbol, name, lookback=lookback)
            decision = result.get("final_action", "未知")
            confidence = result.get("confidence", "?")
        except Exception as e:
            print(f"  {eval_date.date()} LLM错误: {e}")
            time.sleep(2)
            continue

        direction = decision_to_direction(decision)

        # 次日收益
        ret_1d = (next_day["close"] - window["close"].iloc[-1]) / window["close"].iloc[-1] * 100
        # 3日收益
        ret_3d = (day3["close"] - window["close"].iloc[-1]) / window["close"].iloc[-1] * 100

        # 方向是否正确
        correct_1d = (direction == 1 and ret_1d > 0) or (direction == -1 and ret_1d < 0)
        correct_3d = (direction == 1 and ret_3d > 0) or (direction == -1 and ret_3d < 0)

        results.append({
            "date": eval_date.date(),
            "close": window["close"].iloc[-1],
            "decision": decision,
            "direction": direction,
            "confidence": confidence,
            "ret_1d": round(ret_1d, 2),
            "ret_3d": round(ret_3d, 2),
            "correct_1d": correct_1d if direction != 0 else None,
            "correct_3d": correct_3d if direction != 0 else None,
            "triggered_count": len(result.get("triggered_rules", [])),
        })

        icon = "Y" if correct_1d else ("N" if correct_1d is False else "~")
        print(f"  {eval_date.date()} | price {window['close'].iloc[-1]:.1f} | {decision:<8} | dir {direction:+d} | "
              f"1d {ret_1d:+.1f}% {icon} | 3d {ret_3d:+.1f}% | rules {len(result.get('triggered_rules',[]))} | c {confidence}")

        time.sleep(0.5)  # API速率限制

    # ============================================================
    # 统计
    # ============================================================
    print(f"\n{'='*70}")
    print(f"回测统计: {symbol} {name}")
    print(f"{'='*70}")

    rdf = pd.DataFrame(results)

    # 1日准确率
    dir_mask_1d = rdf["correct_1d"].notna()
    acc_1d = rdf.loc[dir_mask_1d, "correct_1d"].sum() / dir_mask_1d.sum() * 100 if dir_mask_1d.sum() > 0 else 0

    # 3日准确率
    dir_mask_3d = rdf["correct_3d"].notna()
    acc_3d = rdf.loc[dir_mask_3d, "correct_3d"].sum() / dir_mask_3d.sum() * 100 if dir_mask_3d.sum() > 0 else 0

    # 按决策类型统计
    print(f"\n决策分布:")
    for d in ["加仓", "减仓", "清仓", "观望", "机会进场", "风险回避"]:
        subset = rdf[rdf["decision"] == d]
        if len(subset) == 0:
            continue
        correct_1d_count = subset["correct_1d"].dropna().sum()
        correct_1d_total = subset["correct_1d"].notna().sum()
        acc = correct_1d_count / correct_1d_total * 100 if correct_1d_total > 0 else 0
        print(f"  {d}: {len(subset)}次, 1日准确率 {acc:.0f}% ({int(correct_1d_count)}/{correct_1d_total})")

    # 按置信度统计
    print(f"\n按置信度:")
    for conf in ["高", "中", "低"]:
        subset = rdf[rdf["confidence"] == conf]
        if len(subset) == 0:
            continue
        correct_count = subset["correct_1d"].dropna().sum()
        correct_total = subset["correct_1d"].notna().sum()
        acc = correct_count / correct_total * 100 if correct_total > 0 else 0
        print(f"  {conf}置信度: {len(subset)}次, 准确率 {acc:.0f}% ({int(correct_count)}/{correct_total})")

    print(f"\n全天准确率:")
    print(f"  1日方向: {acc_1d:.1f}% ({int(rdf.loc[dir_mask_1d,'correct_1d'].sum())}/{dir_mask_1d.sum()}次)")
    print(f"  3日方向: {acc_3d:.1f}% ({int(rdf.loc[dir_mask_3d,'correct_3d'].sum())}/{dir_mask_3d.sum()}次)")

    # 观望比例
    watch_pct = len(rdf[rdf["direction"] == 0]) / len(rdf) * 100
    print(f"  观望比例: {watch_pct:.0f}% ({len(rdf[rdf['direction']==0])}/{len(rdf)}天)")

    # 平均收益率（按决策）
    print(f"\n按决策平均收益:")
    for d in ["加仓", "减仓", "清仓", "观望", "机会进场", "风险回避"]:
        subset = rdf[rdf["decision"] == d]
        if len(subset) == 0:
            continue
        print(f"  {d}: 次日平均 {subset['ret_1d'].mean():+.2f}%, 3日平均 {subset['ret_3d'].mean():+.2f}%")


if __name__ == "__main__":
    main()
