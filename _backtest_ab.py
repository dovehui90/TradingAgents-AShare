"""A/B 回测：对比 baseline（旧方案）vs enhanced（新方案）信号准确率。

用法: python _backtest_ab.py

设计:
- 同股票 × 同日期，分别用 TA_ENHANCED=0（旧方案）和 TA_ENHANCED=1（新方案）各跑一轮
- 对每轮获取 forward 实际走势，计算方向正确性
- 输出对比报告：_backtest_ab_results.json

基线差异:
  baseline: 无概念共振 + 无裁决聚合 + 置信度不过滤 + 辩论1轮
  enhanced: 概念共振 + 裁决聚合 + 置信度<40→HOLD + 辩论2轮
  共同点: 提示词文本相同（提示词改动无法热切换，作为整体方案一部分）
"""
import asyncio
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# UTF-8
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

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
    ("300502.SZ", "新易盛"),
    ("002230.SZ", "科大讯飞"),
]
BACKTEST_DATES = ["2026-06-15", "2026-06-22", "2026-06-29"]
FORWARD_DAYS = [1, 3, 5, 10]
OUT_FILE = Path(__file__).parent / "_backtest_ab_results.json"


def fetch_forward_prices(symbol: str, from_date: str) -> dict:
    """复用项目 provider 链路获取 forward 数据。"""
    try:
        from tradingagents.dataflows.interface import route_to_vendor
        end_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        raw = route_to_vendor("get_stock_data", symbol, from_date, end_date)
        if not raw or len(raw) < 50:
            return {"error": "数据不足"}
        lines = raw.strip().split("\n")
        csv_lines = [l for l in lines if not l.startswith("#")]
        if not csv_lines:
            return {"error": "无有效数据"}
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
                fc = float(df[close_col].iloc[d])
                result[f"ret_{d}d"] = round((fc - base_close) / base_close * 100, 2)
            else:
                result[f"ret_{d}d"] = None
        return result
    except Exception as e:
        return {"error": str(e)}


def signal_to_direction(signal: str) -> int:
    s = (signal or "").strip().upper()
    if s in ("BUY", "买入"):
        return 1
    if s in ("SELL", "卖出"):
        return -1
    return 0


def check_correct(direction: int, ret: float) -> bool | None:
    if direction == 0 or ret is None:
        return None
    return (direction == 1 and ret > 0) or (direction == -1 and ret < 0)


async def analyze_one(symbol: str, name: str, trade_date: str, mode: str) -> dict:
    """运行一轮分析，mode='baseline'|'enhanced'。"""
    label = f"[{mode.upper()}] {name} {trade_date}"
    print(f"\n{'='*60}")
    print(label)
    print(f"{'='*60}")

    # 设置环境变量控制模式
    os.environ["TA_ENHANCED"] = "0" if mode == "baseline" else "1"

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
    confidence = ta.signal_processor._extract_confidence(final_decision)

    traces = short.get("analyst_traces", [])
    verdicts = {t.get("agent", ""): t.get("verdict", "?") for t in traces}
    confidences = {t.get("agent", ""): t.get("confidence", "?") for t in traces}

    print(f"  => 信号={signal}, 方向={direction:+d}, 置信度={confidence}, 耗时={elapsed:.0f}s")

    return {
        "mode": mode,
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


async def run_batch(mode: str, stock_date_pairs: list, max_concurrent: int = 6) -> list:
    """以指定模式并行跑一批任务。先设全局 env，避免并行时的竞态。"""
    os.environ["TA_ENHANCED"] = "0" if mode == "baseline" else "1"
    print(f"\n{'#'*60}")
    print(f"# BATCH: {mode.upper()} ({len(stock_date_pairs)} tasks, max {max_concurrent} concurrent)")
    print(f"{'#'*60}")

    sem = asyncio.Semaphore(max_concurrent)

    async def run_one(symbol, name, trade_date):
        async with sem:
            forward = fetch_forward_prices(symbol, trade_date)
            try:
                analysis = await analyze_one(symbol, name, trade_date, mode)
                record = {**analysis, "forward": forward}
                for d in FORWARD_DAYS:
                    ret_key = f"ret_{d}d"
                    if forward.get(ret_key) is not None:
                        record[f"correct_{d}d"] = check_correct(analysis["direction"], forward[ret_key])
                    else:
                        record[f"correct_{d}d"] = None
                verifies = " | ".join(
                    f"{d}d:{forward.get(f'ret_{d}d', '?')}%"
                    + (f" {'✓' if record.get(f'correct_{d}d') else '✗' if record.get(f'correct_{d}d') is False else '?'}"
                     if record.get(f"correct_{d}d") is not None else "")
                    for d in FORWARD_DAYS
                )
                print(f"  forward={forward.get('base_close','?')} => {verifies}")
                return record
            except Exception as e:
                print(f"  失败: {e}")
                import traceback
                traceback.print_exc()
                return {
                    "mode": mode, "symbol": symbol, "name": name, "trade_date": trade_date,
                    "error": str(e), "forward": forward,
                }

    tasks = [run_one(s, n, d) for s, n, d in stock_date_pairs]
    return await asyncio.gather(*tasks)


async def main():
    pairs = [(s, n, d) for s, n in STOCKS for d in BACKTEST_DATES]

    # 先跑 baseline，再跑 enhanced，避免 env var 竞态
    baseline_results = await run_batch("baseline", pairs)
    enhanced_results = await run_batch("enhanced", pairs)
    all_results = list(baseline_results) + list(enhanced_results)

    # ── 汇总 ──
    baseline = [r for r in all_results if r.get("mode") == "baseline"]
    enhanced = [r for r in all_results if r.get("mode") == "enhanced"]

    print(f"\n{'='*70}")
    print("A/B 回测对比报告")
    print(f"{'='*70}")
    print(f"股票: {len(STOCKS)} 只 | 日期: {len(BACKTEST_DATES)} 个 | 总轮次: {len(all_results)}")

    def compute_stats(records: list, label: str) -> dict:
        """计算各周期准确率。"""
        stats = {"label": label}
        for d in FORWARD_DAYS:
            ck = f"correct_{d}d"
            valid = [r for r in records if ck in r and r[ck] is not None]
            if not valid:
                stats[f"acc_{d}d"] = None
                stats[f"n_{d}d"] = 0
                continue
            correct = sum(1 for r in valid if r[ck])
            stats[f"acc_{d}d"] = round(correct / len(valid) * 100, 1)
            stats[f"n_{d}d"] = len(valid)
        # 综合
        all_valid = []
        for d in FORWARD_DAYS:
            ck = f"correct_{d}d"
            all_valid.extend([r[ck] for r in records if ck in r and r[ck] is not None])
        if all_valid:
            stats["acc_overall"] = round(sum(1 for v in all_valid if v) / len(all_valid) * 100, 1)
            stats["n_overall"] = len(all_valid)
        else:
            stats["acc_overall"] = None
            stats["n_overall"] = 0

        # 信号分布
        signals = [r.get("signal", "?") for r in records]
        stats["n_buy"] = signals.count("BUY")
        stats["n_sell"] = signals.count("SELL")
        stats["n_hold"] = signals.count("HOLD")
        return stats

    bs = compute_stats(baseline, "Baseline（旧方案）")
    es = compute_stats(enhanced, "Enhanced（新方案）")

    print(f"\n{'指标':<20} {'Baseline':>10} {'Enhanced':>10} {'变化':>10}")
    print(f"{'-'*50}")
    print(f"{'总轮次':<20} {len(baseline):>10} {len(enhanced):>10}")
    print(f"{'成功轮次':<20} {sum(1 for r in baseline if 'error' not in r):>10} {sum(1 for r in enhanced if 'error' not in r):>10}")
    print(f"{'BUY/SELL/HOLD':<20} {bs['n_buy']}/{bs['n_sell']}/{bs['n_hold']:>5} {es['n_buy']}/{es['n_sell']}/{es['n_hold']:>5}")

    for d in FORWARD_DAYS:
        b_acc = bs.get(f"acc_{d}d") or 0
        e_acc = es.get(f"acc_{d}d") or 0
        delta = e_acc - b_acc
        b_n = bs.get(f"n_{d}d", 0)
        e_n = es.get(f"n_{d}d", 0)
        print(f"{f'{d}日准确率':<20} {b_acc:>9.1f}% ({b_n}) {e_acc:>9.1f}% ({e_n}) {delta:>+9.1f}%")

    b_ov = bs.get("acc_overall") or 0
    e_ov = es.get("acc_overall") or 0
    print(f"{'-'*50}")
    print(f"{'综合准确率':<20} {b_ov:>9.1f}% ({bs['n_overall']}) {e_ov:>9.1f}% ({es['n_overall']}) {e_ov-b_ov:>+9.1f}%")

    # ── 明细 ──
    print(f"\n{'='*70}")
    print("逐信号明细（✓=正确 ✗=错误 -=HOLD/无数据）")
    print(f"{'='*70}")

    for r in all_results:
        if r.get("error"):
            continue
        marks = []
        for d in FORWARD_DAYS:
            ck = f"correct_{d}d"
            if ck in r:
                marks.append("✓" if r[ck] is True else ("✗" if r[ck] is False else "-"))
            else:
                marks.append("?")
        print(f"[{r['mode'][:4]:>4}] {r['trade_date']} {r['name']:<6} {r['signal']:<5} conf={r.get('confidence','?'):>3} "
              + " ".join(f"{d}d:{m}" for d, m in zip(FORWARD_DAYS, marks)))

    # ── 保存 ──
    report = {
        "config": {"stocks": len(STOCKS), "dates": len(BACKTEST_DATES)},
        "baseline_stats": {k: v for k, v in bs.items() if k != "label"},
        "enhanced_stats": {k: v for k, v in es.items() if k != "label"},
        "results": all_results,
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {OUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
