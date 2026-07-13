"""
信号追踪器 + 策略演化引擎

记录每笔交易的信号组合与盈亏结果，从数据中学习：
- 哪些信号真正有预测力
- 哪些信号组合胜率最高
- 阈值是否需要调整
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .base_strategy import SignalResult, TradeOutcome

SIGNAL_NAMES = {
    1: "不创新低", 2: "站上MA5", 3: "缩量企稳",
    4: "5日转正", 5: "接近高点", 6: "形态确认",
}


class SignalTracker:
    """追踪信号与交易结果，驱动策略演化"""

    def __init__(self, storage_path: str | None = None):
        self._trades: list[dict] = []
        self._storage_path = storage_path
        self._evolution_log: list[dict] = []
        if storage_path:
            self._load()

    # ==================================================================
    # 记录
    # ==================================================================

    def record(self, signals: SignalResult, outcome: TradeOutcome):
        """记录一笔交易"""
        entry = {
            "date": outcome.entry_date,
            "symbol": outcome.symbol,
            "signals": signals.triggered_signals(),
            "signal_count": signals.signal_count,
            "pattern_action": signals.signal_6_pattern_action,
            "entry_score": signals.entry_score,
            "strategy_type": signals.strategy_type,
            "ma5_deviation": round(signals.ma5_deviation * 100, 1),
            "volume_ratio": round(signals.volume_ratio, 2),
            "rsi_6": round(signals.rsi_6, 1),
            "ret_5d": round(signals.ret_5d * 100, 1),
            "is_win": outcome.is_win,
            "return_pct": round(outcome.return_pct * 100, 2),
            "holding_days": outcome.holding_days,
        }
        self._trades.append(entry)
        if self._storage_path:
            self._save()

    def record_manual(self, signals: SignalResult, is_win: bool, return_pct: float, holding_days: int):
        """手动记录（无TradeOutcome对象时使用）"""
        self.record(signals, TradeOutcome(
            symbol=signals.symbol, entry_date=signals.date, entry_price=0,
            exit_date="", exit_price=0, return_pct=return_pct / 100,
            is_win=is_win, holding_days=holding_days, signals=signals,
        ))

    # ==================================================================
    # 胜率分析
    # ==================================================================

    def signal_winrate(self, min_samples: int = 5) -> dict:
        """每个信号的独立胜率"""
        win_count = defaultdict(int)
        total_count = defaultdict(int)

        for t in self._trades:
            for sig in t["signals"]:
                total_count[sig] += 1
                if t["is_win"]:
                    win_count[sig] += 1

        return {
            str(sig): {
                "name": SIGNAL_NAMES.get(sig, f"信号{sig}"),
                "win_rate": round(win_count[sig] / total_count[sig] * 100, 1),
                "samples": total_count[sig],
                "reliable": total_count[sig] >= min_samples,
            }
            for sig in sorted(total_count.keys())
        }

    def combo_winrate(self, min_samples: int = 3) -> pd.DataFrame:
        """各信号组合的胜率排名"""
        combo_data = defaultdict(lambda: {"wins": 0, "total": 0})

        for t in self._trades:
            key = tuple(sorted(t["signals"]))
            combo_data[key]["total"] += 1
            if t["is_win"]:
                combo_data[key]["wins"] += 1

        rows = []
        for combo, stats in combo_data.items():
            if stats["total"] >= min_samples:
                rows.append({
                    "signals": combo, "signal_count": len(combo),
                    "win_rate": round(stats["wins"] / stats["total"] * 100, 1),
                    "samples": stats["total"],
                })

        df = pd.DataFrame(rows)
        return df.sort_values("win_rate", ascending=False) if not df.empty else df

    def signal_count_winrate(self) -> pd.DataFrame:
        """按信号数聚合胜率"""
        bins = defaultdict(lambda: {"wins": 0, "total": 0})
        for t in self._trades:
            n = t["signal_count"]
            bins[n]["total"] += 1
            if t["is_win"]:
                bins[n]["wins"] += 1

        rows = [{"signal_count": n, "win_rate": round(s["wins"] / s["total"] * 100, 1),
                  "samples": s["total"]}
                for n, s in sorted(bins.items())]
        return pd.DataFrame(rows)

    def strategy_winrate(self) -> pd.DataFrame:
        """按策略类型聚合胜率"""
        bins = defaultdict(lambda: {"wins": 0, "total": 0, "cum_return": 0.0})
        for t in self._trades:
            st = t["strategy_type"]
            bins[st]["total"] += 1
            bins[st]["cum_return"] += t["return_pct"]
            if t["is_win"]:
                bins[st]["wins"] += 1

        rows = [{"strategy_type": st,
                 "win_rate": round(s["wins"] / s["total"] * 100, 1),
                 "samples": s["total"],
                 "cum_return": round(s["cum_return"], 1)}
                for st, s in sorted(bins.items())]
        return pd.DataFrame(rows)

    def score_winrate_matrix(self) -> pd.DataFrame:
        """评分区间×胜率矩阵"""
        rows = []
        self._trades.sort(key=lambda t: t["entry_score"])
        for t in self._trades:
            bucket = (t["entry_score"] // 10) * 10
            rows.append({"score_bucket": f"{bucket}-{bucket+9}", "entry_score": t["entry_score"],
                         "is_win": t["is_win"]})

        df = pd.DataFrame(rows)
        if df.empty:
            return df
        return df.groupby("score_bucket").agg(
            win_rate=("is_win", lambda x: round(sum(x) / len(x) * 100, 1)),
            samples=("is_win", "count"),
        ).reset_index()

    # ==================================================================
    # 学习/演化
    # ==================================================================

    def suggest_evolution(self, min_samples: int = 50) -> dict:
        """基于历史数据建议策略演化"""
        if len(self._trades) < min_samples:
            return {"ready": False, "reason": f"样本不足({len(self._trades)}<{min_samples})"}

        suggestions = {"ready": True, "changes": [], "new_thresholds": {}}

        # 1. 信号权重建议
        sw = self.signal_winrate(min_samples=10)
        weak_signals = [k for k, v in sw.items() if v["reliable"] and v["win_rate"] < 50]
        strong_signals = [k for k, v in sw.items() if v["reliable"] and v["win_rate"] > 65]

        if weak_signals:
            suggestions["changes"].append({
                "type": "downgrade_signals",
                "signals": weak_signals,
                "reason": "胜率<50%，建议降权或停用",
            })
        if strong_signals:
            suggestions["changes"].append({
                "type": "upgrade_signals",
                "signals": strong_signals,
                "reason": "胜率>65%，建议提升权重",
            })

        # 2. 信号数阈值建议
        sc_win = self.signal_count_winrate()
        if not sc_win.empty:
            best_count = sc_win.loc[sc_win["win_rate"].idxmax()]
            suggestions["changes"].append({
                "type": "optimal_signal_count",
                "current": f"3-4个",
                "suggested": f"{int(best_count['signal_count'])}个",
                "actual_winrate": float(best_count["win_rate"]),
            })

        # 3. 评分阈值建议
        score_matrix = self.score_winrate_matrix()
        if not score_matrix.empty:
            current_threshold = 55
            viable = []
            for _, row in score_matrix.iterrows():
                if row["samples"] >= 5 and row["win_rate"] >= 55:
                    low = int(row["score_bucket"].split("-")[0])
                    viable.append(low)
            if viable:
                new_threshold = min(viable)
                suggestions["new_thresholds"]["dip_buying"] = new_threshold
                if new_threshold != current_threshold:
                    suggestions["changes"].append({
                        "type": "lower_threshold",
                        "from": 55, "to": new_threshold,
                        "reason": f"评分≥{new_threshold}胜率仍达标，可放宽入场门槛",
                    })

        # 4. 动态信号权重
        suggestions["new_weights"] = {}
        for sig_key, info in sw.items():
            if info["reliable"]:
                weight = round(info["win_rate"] / 100, 2)
                suggestions["new_weights"][f"signal_{sig_key}"] = weight

        return suggestions

    def apply_evolution(self, config_path: str):
        """应用演化建议到配置文件"""
        suggestions = self.suggest_evolution()
        if not suggestions["ready"]:
            return

        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        old_version = config["version"]

        # 更新权重
        if suggestions.get("new_weights"):
            config["signal_weights"].update(suggestions["new_weights"])

        # 更新阈值
        if suggestions.get("new_thresholds"):
            config["score_thresholds"].update(suggestions["new_thresholds"])

        # 版本递增
        parts = old_version.split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        new_version = ".".join(parts)
        config["version"] = new_version

        # 记录演化
        config.setdefault("evolutions", []).append({
            "from_version": old_version,
            "to_version": new_version,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "sample_count": len(self._trades),
            "changes": suggestions["changes"],
        })

        Path(config_path).write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

        self._evolution_log.append({
            "timestamp": datetime.now().isoformat(),
            "from_version": old_version,
            "to_version": new_version,
            "changes": suggestions["changes"],
        })

    # ==================================================================
    # 报告
    # ==================================================================

    def report(self) -> str:
        """生成当前追踪状态报告"""
        total = len(self._trades)
        if total == 0:
            return "暂无交易记录"

        wins = sum(1 for t in self._trades if t["is_win"])
        wr = round(wins / total * 100, 1)
        avg_ret = round(np.mean([t["return_pct"] for t in self._trades]), 2)

        lines = [
            f"=== 信号追踪报告 ===",
            f"总交易: {total}笔  胜率: {wr}%  均收益: {avg_ret}%",
            "",
            "--- 按信号数 ---",
        ]

        sc_df = self.signal_count_winrate()
        if not sc_df.empty:
            for _, row in sc_df.iterrows():
                lines.append(f"  {int(row['signal_count'])}信号: {row['win_rate']}% ({int(row['samples'])}笔)")

        lines.append("")
        lines.append("--- 信号独立胜率 ---")
        for sig, info in self.signal_winrate().items():
            marker = " ✓" if info["reliable"] else " ?"
            lines.append(f"  信号{sig} {info['name']}: {info['win_rate']}% ({info['samples']}笔){marker}")

        lines.append("")
        lines.append("--- 策略类型 ---")
        st_df = self.strategy_winrate()
        if not st_df.empty:
            for _, row in st_df.iterrows():
                lines.append(f"  {row['strategy_type']}: {row['win_rate']}% ({int(row['samples'])}笔) 累计{row['cum_return']}%")

        lines.append("")
        lines.append("--- 最优信号组合 (Top 5) ---")
        combo_df = self.combo_winrate()
        if not combo_df.empty:
            for _, row in combo_df.head(5).iterrows():
                sig_names = ",".join(SIGNAL_NAMES.get(s, f"S{s}") for s in row["signals"])
                lines.append(f"  [{sig_names}]: {row['win_rate']}% ({int(row['samples'])}笔)")

        return "\n".join(lines)

    # ==================================================================
    # 持久化
    # ==================================================================

    def _save(self):
        if not self._storage_path:
            return
        Path(self._storage_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self._storage_path, "w", encoding="utf-8") as f:
            json.dump({"trades": self._trades, "evolutions": self._evolution_log},
                      f, ensure_ascii=False, indent=2)

    def _load(self):
        p = Path(self._storage_path)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            self._trades = data.get("trades", [])
            self._evolution_log = data.get("evolutions", [])
