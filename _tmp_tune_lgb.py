"""LightGBM超参数随机搜索 — 合并训练+时间验证"""
import sys, numpy as np, pandas as pd, json, random
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from tradingagents.buy_point.ml_trainer import (
    build_multi_stock_matrix, ALL_FEATURE_COLS, DEFAULT_ATR_MULTIPLIER
)
import lightgbm as lgb

SYMBOLS = [
    "300265.SZ", "300750.SZ", "300059.SZ", "300274.SZ", "300502.SZ",
    "300394.SZ", "300024.SZ", "300014.SZ", "300433.SZ",
    "600498.SH", "600519.SH", "601127.SH", "601012.SH", "600118.SH",
    "600760.SH", "603501.SH", "603986.SH", "603259.SH", "603019.SH",
]
TRAIN_END = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

print(f"训练截止: {TRAIN_END}")
data = build_multi_stock_matrix(SYMBOLS, label_window=5, data_end=TRAIN_END)
label_col = f"fwd_max_5d"

# 精炼标签：反弹+收盘为正
data["atr_threshold"] = data["atr_pct_14d"] * DEFAULT_ATR_MULTIPLIER / 100
data["_label"] = (
    (data[label_col] > data["atr_threshold"]) &
    (data["_fwd_close_ret"] > 0)
).astype(int)

# 按时间排序后取后20%做验证集（跨股票混合）
data = data.sort_index()
split_idx = int(len(data) * 0.8)
train_df = data.iloc[:split_idx]
val_df = data.iloc[split_idx:]

X_train = train_df[ALL_FEATURE_COLS].values
y_train = train_df["_label"].values
X_val = val_df[ALL_FEATURE_COLS].values
y_val = val_df["_label"].values

pos_rate = y_train.mean()
print(f"训练: {len(X_train)}, 验证: {len(X_val)}, 正样本率: {pos_rate:.1%}")
print(f"验证集正样本率: {y_val.mean():.1%}")

# ---- 参数采样 ----
def sample_params():
    return {
        "max_depth": random.choice([2, 3, 4, 5]),
        "num_leaves": random.choice([15, 31, 63]),
        "learning_rate": random.choice([0.01, 0.02, 0.03, 0.05]),
        "min_child_samples": random.choice([20, 30, 50, 80]),
        "subsample": random.choice([0.5, 0.6, 0.7, 0.8]),
        "colsample_bytree": random.choice([0.4, 0.5, 0.6, 0.7]),
        "reg_alpha": random.choice([0.0, 0.5, 1.0, 2.0, 5.0]),
        "reg_lambda": random.choice([0.0, 1.0, 2.0, 5.0, 10.0]),
        "min_child_weight": random.choice([0.001, 0.01, 0.1, 1.0]),
        "n_estimators": random.choice([200, 300, 500, 800]),
    }

def evaluate_params(params):
    """在验证集上评估 WR@threshold=0.5"""
    pos = y_train.sum()
    neg = len(y_train) - pos
    spw = neg / pos if pos > 0 else 1.0

    model_params = {
        **params,
        "objective": "binary",
        "metric": "binary_logloss",
        "scale_pos_weight": spw,
        "random_state": 42,
        "verbosity": -1,
    }
    dtrain = lgb.Dataset(X_train, label=y_train)
    booster = lgb.train(model_params, dtrain, valid_sets=[dtrain],
                        callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(0)])

    y_prob = booster.predict(X_val)

    # 评估多个阈值
    best_score = 0
    best_wr, best_trades, best_th = 0, 0, 0.5
    for th in [0.4, 0.45, 0.5, 0.55, 0.6, 0.65]:
        y_pred = y_prob >= th
        trades = y_pred.sum()
        if trades >= 10:
            wr = y_val[y_pred].mean()
            # score = WR * min(trades, 50) / 50  (penalize too few trades)
            score = wr * min(trades, 50) / 50
            if score > best_score:
                best_score = score
                best_wr, best_trades, best_th = wr, trades, th

    return best_wr, best_trades, best_th

# ---- 搜索 ----
N_TRIALS = 80
best_score, best_wr, best_params, best_trades, best_th = 0, 0, None, 0, 0.5
results = []

for i in range(N_TRIALS):
    params = sample_params()
    wr, trades, th = evaluate_params(params)
    score = wr * min(trades, 50) / 50 if trades >= 10 else 0
    results.append({"params": params, "wr": wr, "trades": trades, "th": th, "score": score})
    flag = "***" if score > best_score else "   "
    print(f"[{i+1:2d}/{N_TRIALS}] th={th:.2f} WR={wr:.1%} {trades:3d}笔 score={score:.3f} max_depth={params['max_depth']} lr={params['learning_rate']} {flag}")
    if score > best_score:
        best_score, best_wr, best_params, best_trades, best_th = score, wr, params, trades, th

# ---- Top 10 ----
results.sort(key=lambda r: r["score"], reverse=True)
print(f"\n=== Top 10 参数组合 ===")
for i, r in enumerate(results[:10]):
    p = r["params"]
    print(f"#{i+1}: th={r['th']:.2f} WR={r['wr']:.1%} {r['trades']}笔 score={r['score']:.3f}")
    print(f"    max_depth={p['max_depth']} num_leaves={p['num_leaves']} lr={p['learning_rate']} n_est={p['n_estimators']}")
    print(f"    min_child_samples={p['min_child_samples']} subsample={p['subsample']} colsample={p['colsample_bytree']}")
    print(f"    reg_alpha={p['reg_alpha']} reg_lambda={p['reg_lambda']} min_child_weight={p['min_child_weight']}")

print(f"\n=== 最优参数 ===")
print(json.dumps(best_params, indent=2))
print(f"Best: th={best_th:.2f} WR={best_wr:.1%} ({best_trades}笔) score={best_score:.3f}")

# Save
Path("_tmp_best_params.json").write_text(json.dumps({
    "params": best_params, "wr": best_wr, "trades": best_trades, "threshold": best_th,
    "top10": [{"wr": r["wr"], "trades": r["trades"], "th": r["th"], "params": r["params"]} for r in results[:10]]
}, indent=2, ensure_ascii=False))
print("\n结果已保存到 _tmp_best_params.json")
