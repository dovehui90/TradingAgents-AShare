"""Quick A/B test: run backtest on watchlist stocks to verify improvements.

Usage: python tests/run_quick_ab.py
"""
import sys, os, time, json

# Load .env before importing project modules
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(env_path):
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.services.backtest_service import submit, get_job

SYMBOLS = ["000815.SZ"]  # 先单个测试，验证通过后扩展
START = "2025-05-01"
END   = "2025-06-30"
HOLD_DAYS = 5
SAMPLE_INTERVAL = 10
TIMEOUT = 3600  # 60 min

# 合并默认配置 + 用户 LLM 配置
from tradingagents.default_config import DEFAULT_CONFIG
config = dict(DEFAULT_CONFIG)
config.update({
    "llm_provider": os.getenv("TA_LLM_PROVIDER", "deepseek"),
    "quick_think_llm": os.getenv("TA_LLM_QUICK", "deepseek-v4-flash"),
    "deep_think_llm": os.getenv("TA_LLM_DEEP", "deepseek-v4-pro"),
    "backend_url": os.getenv("TA_BASE_URL", "https://api.deepseek.com/v1"),
    "api_key": os.getenv("TA_API_KEY", ""),
})
print(f"LLM: {config['quick_think_llm']} @ {config['backend_url']}")

BASELINE = {"accuracy_5d": 22.2, "avg_return_5d": 2.55, "sample_count": 54}
print(f"基线（54条）：5日准确率 {BASELINE['accuracy_5d']}% | 均收益 {BASELINE['avg_return_5d']}%")
print(f"测试: {SYMBOLS} | {START}~{END} | 持仓{HOLD_DAYS}d\n")

all_results = {}
for sym in SYMBOLS:
    print(f"[{sym}] 提交回测...")
    job_id = submit(sym, START, END, selected_analysts=[],
                    hold_days=HOLD_DAYS, sample_interval=SAMPLE_INTERVAL, config=config)

    started = time.time()
    while time.time() - started < TIMEOUT:
        job = get_job(job_id)
        if not job:
            time.sleep(5)
            continue
        status = job.get("status", "?")
        cd, td = job.get("completed_dates", 0), job.get("total_dates", 0)
        if status in ("pending", "running"):
            if cd != td or td == 0:
                print(f"  [{sym}] {status} {cd}/{td}", flush=True)
        elif status == "completed":
            s = job.get("stats") or {}
            all_results[sym] = job
            wr = s.get('win_rate') or 0
            ar = s.get('avg_return_pct') or 0
            ts = s.get('total_signals') or 0
            print(f"  [{sym}] 完成: {ts}信号 胜率{wr:.1f}% 均收益{ar:.2f}%")
            break
        elif status == "failed":
            print(f"  [{sym}] 失败: {job.get('error','?')}")
            break
        time.sleep(20)
    else:
        print(f"  [{sym}] 超时")

# 汇总
if all_results:
    total = 0; wins = []; rets = []
    for r in all_results.values():
        s = r.get("stats") or {}
        total += s.get("total_signals", 0) or 0
        if s.get("win_rate") is not None:
            wins.append(s["win_rate"])
        if s.get("avg_return_pct") is not None:
            rets.append(s["avg_return_pct"])
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_ret = sum(rets) / len(rets) if rets else 0

    print(f"\n{'='*55}")
    print(f" 结果汇总")
    print(f"{'='*55}")
    delta = avg_win - BASELINE["accuracy_5d"]
    print(f"  信号数: {total} | 胜率: {avg_win:.1f}% | 均收益: {avg_ret:.2f}%")
    print(f"  vs 基线: 胜率 {'↑' if delta>0 else '↓'}{abs(delta):.1f}%")
    for sym, r in all_results.items():
        s = r.get("stats") or {}
        records = r.get("records") or []
        buys = sum(1 for x in records if x.get("action") == "BUY")
        wr = s.get("win_rate") or 0; ts = s.get("total_signals") or 0; ar = s.get("avg_return_pct") or 0
        print(f"  {sym}: {ts}信号 胜率{wr:.1f}% 收益{ar:+.2f}% 买{buys}次")
else:
    print("\n无结果")
