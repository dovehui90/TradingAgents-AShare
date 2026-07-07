"""集成测试：对三只股票运行完整决策流程，验证 Phase 1-7 改动效果。

用法: python _run_integration_test.py
依赖: .env 中的 TA_API_KEY 已配置
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Load .env first
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                if val and key not in os.environ:
                    os.environ[key] = val
                    print(f"  [env] {key}={val[:20]}{'...' if len(val)>20 else ''}")

from tradingagents.dataflows.config import get_config
from tradingagents.graph.trading_graph import TradingAgentsGraph

STOCKS = [
    ("300476.SZ", "胜宏科技"),
    ("300265.SZ", "通光线缆"),
    ("301035.SZ", "润丰股份"),
]

OUT_DIR = Path(__file__).parent / "_integration_results"
OUT_DIR.mkdir(exist_ok=True)


async def analyze_one(symbol: str, name: str, trade_date: str) -> dict:
    print(f"\n{'='*60}")
    print(f"[{name}] {symbol} 开始分析...")
    print(f"{'='*60}")

    start = time.monotonic()
    ta = TradingAgentsGraph(selected_analysts=[
        "market", "news", "social", "fundamentals", "macro",
        "smart_money", "volume_price",
    ])

    result = await ta.propagate_async(symbol, trade_date)
    elapsed = time.monotonic() - start
    print(f"[{name}] 分析完成，耗时 {elapsed:.0f}s")

    # Extract key info
    short = result.get("short_term", {})
    final_decision = short.get("final_trade_decision", "")
    signal = ta.signal_processor.process_signal(final_decision)
    traces = short.get("analyst_traces", [])

    summary = {
        "symbol": symbol,
        "name": name,
        "trade_date": trade_date,
        "elapsed_s": round(elapsed, 1),
        "signal": signal,
        "final_decision_head": final_decision[:2000] if final_decision else "",
        "analyst_traces": [
            {"agent": t.get("agent"), "verdict": t.get("verdict"),
             "confidence": t.get("confidence"), "key_finding": t.get("key_finding")[:200]}
            for t in traces
        ],
        "investment_plan_head": short.get("investment_plan", "")[:1000],
    }

    return summary


async def main():
    trade_date = datetime.now().strftime("%Y-%m-%d")
    # Use latest trading day (today is Sunday, so use Friday)
    print(f"分析日期: {trade_date}")
    print(f"标的: {', '.join(f'{name}({sym})' for sym, name in STOCKS)}")

    all_results = []
    for symbol, name in STOCKS:
        try:
            summary = await analyze_one(symbol, name, trade_date)
            all_results.append(summary)
        except Exception as e:
            print(f"[{name}] 分析失败: {e}")
            import traceback
            traceback.print_exc()
            all_results.append({"symbol": symbol, "name": name, "error": str(e)})

    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"integration_test_{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out_path}")

    # Print comparison summary
    print(f"\n{'='*60}")
    print("对比摘要")
    print(f"{'='*60}")
    for r in all_results:
        if "error" in r:
            print(f"  {r['name']}({r['symbol']}): ERROR - {r['error']}")
        else:
            traces = r.get("analyst_traces", [])
            directions = ", ".join(
                f"{t['agent'].replace('_analyst','')}:{t.get('verdict','?')}"
                for t in traces
            )
            print(f"  {r['name']}({r['symbol']}): 信号={r.get('signal','?')}, 耗时={r.get('elapsed_s','?')}s")
            print(f"    分析师裁决: {directions}")
            # Show concept resonance if available
            decision_head = r.get("final_decision_head", "")
            if "概念共振" in decision_head:
                idx = decision_head.find("概念共振")
                print(f"    概念共振: {decision_head[idx:idx+200]}...")


if __name__ == "__main__":
    asyncio.run(main())
