"""信号准确率回测：对历史日期跑完整决策流程，对比信号方向 vs 后续实际走势。

用法: python _backtest_signal.py

输出: _backtest_results.json（每条记录的信号+实际收益+是否正确）
"""
import asyncio
import io
import json
import os
import sys

# 强制UTF-8输出，防止LLM返回的Unicode字符导致GBK编码崩溃
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# Load .env
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                if val and key not in os.environ:
                    os.environ[key] = val

from tradingagents.graph.trading_graph import TradingAgentsGraph

# ── 回测配置 ──
STOCKS = [
    ("300476.SZ", "胜宏科技"),
    ("300265.SZ", "通光线缆"),
]
# 历史回测日期：每周选1天，覆盖近3周（避开今天，因为还没有后续走势）
BACKTEST_DATES = ["2026-06-15", "2026-06-22", "2026-06-29"]
FORWARD_DAYS = [1, 3, 5, 10]  # 验证未来N个交易日的方向

OUT_FILE = Path(__file__).parent / "_backtest_results.json"


def fetch_forward_prices(symbol: str, from_date: str) -> dict:
    """获取指定日期之后N个交易日的收盘价，复用项目provider链路。"""
    try:
        from tradingagents.dataflows.interface import route_to_vendor

        end_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        raw = route_to_vendor("get_stock_data", symbol, from_date, end_date)
        if not raw or len(raw) < 50:
            return {"error": "无数据"}

        # provider返回格式: # 注释行\n# 注释行\n\nDate,Open,High,Low,Close,Volume,Dividends,Stock Splits
        lines = raw.strip().split("\n")
        csv_lines = [l for l in lines if not l.startswith("#")]
        if not csv_lines:
            return {"error": "无有效数据行"}
        df = pd.read_csv(io.StringIO("\n".join(csv_lines)))
        if df.empty:
            return {"error": "无数据"}
        df.columns = [c.strip().lower() for c in df.columns]
        close_col = "close"
        date_col = "date" if "date" in df.columns else "trade_date"
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.sort_values(date_col)

        base_close = float(df[close_col].iloc[0])
        result = {"base_close": base_close, "base_date": str(df[date_col].iloc[0].date())}
        for d in FORWARD_DAYS:
            if d < len(df):
                future_close = float(df[close_col].iloc[d])
                ret = (future_close - base_close) / base_close * 100
                result[f"ret_{d}d"] = round(ret, 2)
                result[f"close_{d}d"] = future_close
            else:
                result[f"ret_{d}d"] = None
        return result
    except Exception as e:
        return {"error": str(e)}


def signal_to_direction(signal: str) -> int:
    """信号文本 → 方向数值。+1=看多, -1=看空, 0=中性。"""
    s = (signal or "").strip().upper()
    if s in ("BUY", "买入"):
        return 1
    if s in ("SELL", "卖出"):
        return -1
    return 0


def check_correct(direction: int, ret: float) -> bool | None:
    """检查方向是否正确。中性方向不参与统计。"""
    if direction == 0 or ret is None:
        return None
    if direction == 1 and ret > 0:
        return True
    if direction == -1 and ret < 0:
        return True
    return False


async def analyze_one(symbol: str, name: str, trade_date: str) -> dict:
    """运行完整决策流程，返回信号和关键指标。"""
    print(f"\n{'='*60}")
    print(f"[{name}] {symbol} | {trade_date}")
    print(f"{'='*60}")

    start = time.monotonic()
    ta = TradingAgentsGraph(selected_analysts=[
        "market", "news", "social", "fundamentals", "macro",
        "smart_money", "volume_price",
    ])

    result = await ta.propagate_async(symbol, trade_date)
    elapsed = time.monotonic() - start

    short = result.get("short_term", {})
    final_decision = short.get("final_trade_decision", "")
    signal = ta.signal_processor.process_signal(final_decision)
    direction = signal_to_direction(signal)

    traces = short.get("analyst_traces", [])
    verdicts = {t.get("agent", ""): t.get("verdict", "?") for t in traces}
    confidences = {t.get("agent", ""): t.get("confidence", "?") for t in traces}

    # 提取研究经理置信度
    confidence = ta.signal_processor._extract_confidence(final_decision)

    print(f"  => 信号={signal}, 方向={direction:+d}, 置信度={confidence}, 耗时={elapsed:.0f}s")

    return {
        "symbol": symbol,
        "name": name,
        "trade_date": trade_date,
        "elapsed_s": round(elapsed, 1),
        "signal": signal,
        "direction": direction,
        "confidence": confidence,
        "verdicts": verdicts,
        "confidences": confidences,
    }


async def analyze_and_verify(symbol: str, name: str, trade_date: str) -> dict:
    """并行单元：分析 + 验证。"""
    try:
        analysis = await analyze_one(symbol, name, trade_date)
        forward = fetch_forward_prices(symbol, trade_date)

        record = {**analysis, "forward": forward}
        for d in FORWARD_DAYS:
            ret_key = f"ret_{d}d"
            if forward.get(ret_key) is not None:
                record[f"correct_{d}d"] = check_correct(analysis["direction"], forward[ret_key])
            else:
                record[f"correct_{d}d"] = None

        print(f"  [{name}] forward: {forward.get('base_close', '?')} => "
              + " | ".join(f"{d}d:{forward.get(f'ret_{d}d', '?')}%" for d in FORWARD_DAYS))
        return record

    except Exception as e:
        print(f"[{name}] {trade_date} 失败: {e}")
        import traceback
        traceback.print_exc()
        return {
            "symbol": symbol, "name": name, "trade_date": trade_date,
            "error": str(e),
        }


async def main():
    # 所有组合并行执行（2股票 × 3日期 = 6个并发任务）
    tasks = [
        analyze_and_verify(symbol, name, trade_date)
        for symbol, name in STOCKS
        for trade_date in BACKTEST_DATES
    ]
    all_results = await asyncio.gather(*tasks)

    # ── 计算准确率 ──
    print(f"\n{'='*70}")
    print("回测汇总")
    print(f"{'='*70}")

    for d in FORWARD_DAYS:
        correct_key = f"correct_{d}d"
        valid = [r for r in all_results if correct_key in r and r[correct_key] is not None]
        if not valid:
            print(f"\n{d}日准确率: 无有效数据")
            continue
        correct_count = sum(1 for r in valid if r[correct_key])
        acc = correct_count / len(valid) * 100
        print(f"\n{d}日准确率: {acc:.0f}% ({correct_count}/{len(valid)})")
        for r in valid:
            icon = "✓" if r[correct_key] else "✗"
            print(f"  {r['trade_date']} {r['name']}({r['symbol']}): "
                  f"信号={r['signal']:<5} 方向={r['direction']:+d} "
                  f"{d}d收益={r['forward'].get(f'ret_{d}d', '?'):+.1f}% {icon}")

    # 按置信度分层
    print(f"\n按置信度分层 (5日):")
    for conf in ["高", "中", "低"]:
        subset = [r for r in all_results if r.get("confidence") == conf and f"correct_5d" in r and r["correct_5d"] is not None]
        if subset:
            correct = sum(1 for r in subset if r["correct_5d"])
            acc = correct / len(subset) * 100
            print(f"  置信度{conf}: {acc:.0f}% ({correct}/{len(subset)})")

    # 保存结果
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {OUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
