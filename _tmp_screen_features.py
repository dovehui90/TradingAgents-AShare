"""LR特征筛选：L1正则+系数分析，筛出20-30个有效特征"""
import sys, numpy as np, pandas as pd, json
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from tradingagents.buy_point.ml_trainer import (
    build_multi_stock_matrix, ALL_FEATURE_COLS, NUMERIC_FEATURES,
    BOOL_FEATURES, PATTERN_FEATURES, DEFAULT_LABEL_WINDOW, DEFAULT_ATR_MULTIPLIER
)

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
data["_label"] = (data[label_col] * 100 > data["atr_pct_14d"] * DEFAULT_ATR_MULTIPLIER).astype(int)

X_raw = data[ALL_FEATURE_COLS]
y = data["_label"].values

print(f"样本: {len(X_raw)}, 正样本率: {y.mean():.1%}")
print(f"特征总数: {len(ALL_FEATURE_COLS)} = {len(NUMERIC_FEATURES)}数值 + {len(BOOL_FEATURES)}布尔 + {len(PATTERN_FEATURES)}形态")

# ---- L1 正则 LR（自动稀疏化）----
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X_raw.values)

# 用交叉验证找最优C
from sklearn.model_selection import StratifiedKFold
best_c, best_score = 0.1, 0
for c in [0.01, 0.03, 0.05, 0.08, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0]:
    lr = LogisticRegression(penalty="l1", solver="saga", C=c, max_iter=5000, random_state=42)
    scores = []
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    for train_idx, val_idx in skf.split(X_scaled, y):
        lr.fit(X_scaled[train_idx], y[train_idx])
        scores.append(lr.score(X_scaled[val_idx], y[val_idx]))
    avg = np.mean(scores)
    nonzero = (lr.coef_[0] != 0).sum()
    print(f"  C={c:.3f}: acc={avg:.3f} nonzero={nonzero}")
    if avg > best_score:
        best_score, best_c = avg, c

print(f"\n最优C={best_c:.3f} (acc={best_score:.3f})")
lr_final = LogisticRegression(penalty="l1", solver="saga", C=best_c, max_iter=5000, random_state=42)
lr_final.fit(X_scaled, y)
coefs = lr_final.coef_[0]
nonzero_count = (coefs != 0).sum()
print(f"非零系数特征: {nonzero_count}/{len(ALL_FEATURE_COLS)}")

# ---- 系数分析 ----
rows = []
for f, c in zip(ALL_FEATURE_COLS, coefs):
    if c != 0:
        direction = "+" if c > 0 else "-"
        rows.append({"feature": f, "coef": round(c, 4), "abs_coef": abs(c), "dir": direction})
    else:
        rows.append({"feature": f, "coef": 0, "abs_coef": 0, "dir": "0"})

df_coef = pd.DataFrame(rows).sort_values("abs_coef", ascending=False)

# ---- 同时跑一次XGBoost看特征重要性做交叉验证 ----
from tradingagents.buy_point.ml_trainer import BuyPointXGB
xgb = BuyPointXGB(n_estimators=200, max_depth=4)
xgb.fit(X_raw, y)
xgb_imp = xgb.feature_importance()

# ---- 合并排行 ----
merged = df_coef.merge(xgb_imp[["feature", "importance"]], on="feature", how="left")
merged["importance"] = merged["importance"].fillna(0)
# 综合评分：LR系数绝对值归一化 + XGBoost重要性归一化
merged["lr_score"] = merged["abs_coef"] / merged["abs_coef"].max()
merged["xgb_score"] = merged["importance"] / merged["importance"].max()
merged["composite"] = merged["lr_score"] * 0.5 + merged["xgb_score"] * 0.5
merged = merged.sort_values("composite", ascending=False)

print(f"\n{'='*80}")
print(f"综合特征排行 (LR系数 + XGBoost重要性) — 前40")
print(f"{'='*80}")
print(f"{'特征':28s} {'LR系数':>8s} {'方向':>3s} {'XGB重要':>8s} {'综合分':>7s}")
for _, r in merged.head(40).iterrows():
    print(f"  {r['feature']:26s} {r['coef']:>+8.4f} {r['dir']:>3s} {r['importance']:>8.4f} {r['composite']:>7.3f}")

# ---- 建议保留的特征 ----
# 规则：综合分>0.05 或 至少在一个模型中排名前30
top_by_composite = merged[merged["composite"] > 0.05]["feature"].tolist()
top_by_lr = merged.nlargest(30, "abs_coef")["feature"].tolist()
top_by_xgb = merged.nlargest(30, "importance")["feature"].tolist()
recommended = list(set(top_by_composite + top_by_lr + top_by_xgb))
print(f"\n建议保留: {len(recommended)}个特征")
print(json.dumps(recommended, ensure_ascii=False))

# ---- 零系数/噪声特征 ----
zero_coef = [f for f, c in zip(ALL_FEATURE_COLS, coefs) if c == 0]
print(f"\nL1消除特征 ({len(zero_coef)}个):")
print(json.dumps(zero_coef, ensure_ascii=False))

# 保存结果
out = {
    "train_end": TRAIN_END,
    "samples": len(X_raw),
    "pos_rate": float(y.mean()),
    "best_c": best_c,
    "lr_acc": float(best_score),
    "recommended_features": recommended,
    "zero_coef_features": zero_coef,
    "ranking": [
        {"feature": r["feature"], "lr_coef": r["coef"], "lr_dir": r["dir"],
         "xgb_importance": r["importance"], "composite": round(r["composite"], 4)}
        for _, r in merged.iterrows()
    ]
}
Path("_tmp_feature_screening.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
print(f"\n结果已保存到 _tmp_feature_screening.json")
