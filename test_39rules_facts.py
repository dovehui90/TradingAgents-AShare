"""
39条规则验证脚本 - 事实引擎 + LLM决策

用法：
  python test_39rules_facts.py                    # 默认验证大中矿业+胜宏科技
  python test_39rules_facts.py 001203             # 单只股票
  python test_39rules_facts.py 001203 300476      # 多只股票
  python test_39rules_facts.py --no-llm           # 只看事实层，不调LLM
"""

import os
import sys
import pandas as pd
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# 数据获取
# ---------------------------------------------------------------------------

STOCK_NAMES = {
    "001203": "大中矿业",
    "300476": "胜宏科技",
}


def fetch_stock_data(symbol: str, days: int = 120) -> pd.DataFrame:
    """获取股票日K数据（akshare → tushare 回退）"""
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")

    # 尝试 akshare
    try:
        import akshare as ak
        raw = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                                 start_date=start_date, end_date=end_date,
                                 adjust="qfq")
        if raw is not None and not raw.empty:
            df = pd.DataFrame({
                "open": raw["开盘"].astype(float),
                "high": raw["最高"].astype(float),
                "low": raw["最低"].astype(float),
                "close": raw["收盘"].astype(float),
                "volume": raw["成交量"].astype(float),
            })
            df.index = pd.to_datetime(raw["日期"])
            df = df.sort_index()
            print(f"[数据] akshare: {symbol} {len(df)}条 ({df.index[0].date()} ~ {df.index[-1].date()})")
            return df.tail(days)
    except Exception as e:
        print(f"[回退] akshare失败 ({e})，尝试tushare...")

    # 回退 tushare
    try:
        import tushare as ts
        token = os.environ.get("TUSHARE_TOKEN",
                               "23651a8611b00bf491c7378d81d0bc6265543153530194be989e6ada")
        ts.set_token(token)
        pro = ts.pro_api()
        ts_code = f"{symbol}.{'SH' if symbol.startswith(('6','9')) else 'SZ'}"
        raw = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        if raw is not None and not raw.empty:
            raw["trade_date"] = pd.to_datetime(raw["trade_date"], format="%Y%m%d")
            raw = raw.set_index("trade_date").sort_index()
            df = raw[["open", "high", "low", "close", "vol"]].rename(columns={"vol": "volume"})
            df["volume"] = df["volume"] * 100  # tushare vol 单位是手
            print(f"[数据] tushare: {symbol} {len(df)}条")
            return df.tail(days)
    except Exception as e:
        print(f"[错误] tushare也失败: {e}")
        raise RuntimeError(f"无法获取 {symbol} 的数据")


def fetch_market_state() -> str:
    """获取当前市场状态（牛市/熊市）"""
    try:
        from tradingagents.strategy.market_state import fetch_sh_index_data, classify_market_state, get_current_market_state
        df = fetch_sh_index_data()
        df = classify_market_state(df)
        state = get_current_market_state(df)
        print(f"[市场] 上证{state['close']} vs 牛线{state['bull_line']} → {state['state']}")
        return state["state"]
    except Exception as e:
        print(f"[警告] 获取市场状态失败: {e}")
        return "未知"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    no_llm = "--no-llm" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if not args:
        symbols = ["001203", "300476"]
    else:
        symbols = args

    # 获取市场状态（一次性）
    market_state = fetch_market_state()

    for symbol in symbols:
        name = STOCK_NAMES.get(symbol, symbol)
        print(f"\n{'=' * 60}")
        print(f"  {symbol} {name}")
        print(f"{'=' * 60}")

        # 1. 获取数据
        df = fetch_stock_data(symbol)

        # 2. 计算事实层
        from tradingagents.strategy.fact_engine import compute_facts, format_fact_text
        facts = compute_facts(df, market_state=market_state)

        # 3. 打印事实层
        fact_text = format_fact_text(facts, lookback=15)
        print(fact_text)

        # 统计
        hv_count = facts["is_high_volume"].sum()
        print(f"\n[统计] 近{len(facts)}日高量柱: {hv_count}次 ({hv_count/len(facts)*100:.0f}%)")
        print(f"[统计] 当前支撑位: {facts['support_level'].iloc[-1]:.2f}" if not pd.isna(facts["support_level"].iloc[-1]) else "[统计] 支撑位: 无")
        rh = facts["resistance_high"].iloc[-1]
        rl = facts["resistance_low"].iloc[-1]
        print(f"[统计] 当前压力位: {rl:.2f} - {rh:.2f}" if not pd.isna(rh) else "[统计] 压力位: 无")

        # 4. LLM决策
        if not no_llm:
            print(f"\n--- LLM 决策中 ---")
            try:
                from tradingagents.strategy.llm_decision import run_decision
                result = run_decision(facts, symbol, name, lookback=15)

                if "error" in result:
                    print(f"[LLM错误] {result['error']}")
                    if "raw" in result:
                        print(f"[原始输出] {result['raw']}")
                else:
                    print(f"\n  市场状态: {result.get('market_state', '?')}")
                    print(f"  趋势: {result.get('trend', '?')}")
                    print(f"  最终决策: {result.get('final_action', '?')}")
                    print(f"  置信度: {result.get('confidence', '?')}")
                    print(f"  综合判断: {result.get('summary', '?')}")
                    print(f"\n  触发规则 ({len(result.get('triggered_rules', []))}条):")
                    for r in result.get("triggered_rules", []):
                        print(f"    规则{r['id']} {r['name']}: {r['decision']}")
                        print(f"      {r['reasoning']}")
            except Exception as e:
                print(f"[LLM调用失败] {e}")
        else:
            print("\n(跳过LLM决策，仅事实层)")

    print(f"\n{'=' * 60}")
    print("验证完成")


if __name__ == "__main__":
    main()
