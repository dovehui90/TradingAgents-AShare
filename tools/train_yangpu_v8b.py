"""阳谱v0.8训练方案A: XGBoost + 资金流 + 同花顺真实prev_yangpu

用同花顺前一日的actual做prev_yangpu训练, 避免v0.7依赖。
训练后验证自滚动是否发散。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from tradingagents.yang_yin.pipeline import YangYinPipeline
from tradingagents.yang_yin.factors_v7 import compute_factors
from tradingagents.yang_yin.model_v7 import FEATURE_COLS, predict_yangpu as predict_v7

CSV_PATH = r"D:\下载\_app_data_所有对话_主对话_yangpu_data_yangpu_comparison_v7 (1).csv"
MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "tradingagents", "yang_yin", "model_v8.json")

import xgboost as xgb

pipeline = YangYinPipeline()
panel = pipeline.load_feature_panel()
if panel is None or "rsi14" not in panel.columns:
    panel = pipeline.build_feature_panel()
logger.info(f"面板: {len(panel)} 行, {panel['trade_date'].nunique()} 天")

mf_dir = pipeline.summary_dir / "moneyflow"
mf_cache = {}
for f in mf_dir.glob("*.parquet"):
    dt = f.stem
    df = pd.read_parquet(f)
    mf_cache[dt] = {}
    for _, row in df.iterrows():
        mf_cache[dt][row.get("ts_code", "")] = float(row.get("net_mf_vol", 0) or 0)
logger.info(f"资金流缓存: {len(mf_cache)} 天")

ref = pd.read_csv(CSV_PATH)
ref = ref.set_index("trade_date")
ref_dates = sorted(str(d) for d in ref.index if str(d) in panel["trade_date"].values)
logger.info(f"匹配日期: {len(ref_dates)} / {len(ref)}")

FEATURES_WITHOUT_PREV = [f for f in FEATURE_COLS if f != "prev_yangpu"]

# ── 构建训练数据: prev_yangpu用同花顺前一日actual ──
X_rows = []
y_actual = []
actual_prev_map = {}
for i, dt in enumerate(ref_dates):
    factors = compute_factors(panel, dt, prev_yangpu=50.0)
    if factors is None:
        continue
    mf = mf_cache.get(dt, {})
    day = panel[panel["trade_date"] == dt]
    mf_vals = [mf.get(c, 0.0) for c in day["ts_code"]]
    factors["money_mean"] = float(np.mean(mf_vals)) if mf_vals else 0.0
    factors["money_yang"] = float(sum(1 for v in mf_vals if v > 0) / len(mf_vals)) if len(mf_vals) > 0 else 0.0

    # prev_yangpu = 前一日同花顺真实值（第一天用50）
    if i == 0:
        prev = 50.0
    else:
        prev = ref.loc[int(ref_dates[i-1]), "actual"]
    factors["prev_yangpu"] = float(prev)

    row = {f: factors.get(f, 0.0) for f in FEATURE_COLS}
    X_rows.append(row)
    y_actual.append(ref.loc[int(dt), "actual"])
    actual_prev_map[dt] = prev

N = len(X_rows)
logger.info(f"训练数据: {N} 行 x {len(FEATURE_COLS)} 列, prev_yangpu=同花顺前日actual")

# ── 训练 ──
X = pd.DataFrame(X_rows)
y = pd.Series(y_actual)

split_idx = int(N * 0.8)
X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

params = {
    "objective": "reg:squarederror",
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 1.0,
    "reg_lambda": 2.0,
    "min_child_weight": 3,
    "eval_metric": "mae",
    "seed": 42,
}

dtrain = xgb.DMatrix(X_train, label=y_train)
dval = xgb.DMatrix(X_val, label=y_val)
model = xgb.train(params, dtrain, num_boost_round=500,
                  evals=[(dtrain, "train"), (dval, "val")],
                  early_stopping_rounds=50, verbose_eval=50)

# 静态评估
dtest_all = xgb.DMatrix(X)
preds_static = model.predict(dtest_all)
mae_static = np.mean(np.abs(y_actual - preds_static))
logger.info(f"\n静态 MAE (prev=同花顺真实): {mae_static:.4f}%")

# ── 自滚动评估 ──
preds_rolling = []
curr = 50.0
for i in range(N):
    row = {f: factors_val for f, factors_val in zip(FEATURES_WITHOUT_PREV,
          [X_rows[i].get(f, 0.0) for f in FEATURES_WITHOUT_PREV])}
    row["prev_yangpu"] = float(curr)
    dtest = xgb.DMatrix(pd.DataFrame([row]))
    pred = float(model.predict(dtest)[0])
    pred = max(0.0, min(100.0, pred))
    preds_rolling.append(pred)
    curr = pred

mae_rolling = np.mean(np.abs(np.array(y_actual) - np.array(preds_rolling)))
pct5_rolling = np.mean(np.abs(np.array(y_actual) - np.array(preds_rolling)) <= 5) * 100
pct10_rolling = np.mean(np.abs(np.array(y_actual) - np.array(preds_rolling)) > 10) * 100
logger.info(f"自滚动 MAE: {mae_rolling:.4f}%")
logger.info(f"≤5%占比: {pct5_rolling:.0f}%  >10%占比: {pct10_rolling:.0f}%")

# v0.7 自滚动
v7_preds = []
curr = 50.0
for i in range(N):
    factors_v7 = {f: X_rows[i].get(f, 0.0) for f in FEATURES_WITHOUT_PREV}
    factors_v7["prev_yangpu"] = float(curr)
    pred = predict_v7(factors_v7)
    pred = max(0.0, min(100.0, pred))
    v7_preds.append(pred)
    curr = pred

v7_mae = np.mean(np.abs(np.array(y_actual) - np.array(v7_preds)))
logger.info(f"v0.7 自滚动 MAE: {v7_mae:.4f}%")
logger.info(f"MAE改善: {(v7_mae - mae_rolling):.2f}% ({(1 - mae_rolling/v7_mae)*100:.1f}%)")

# ── 保存 ──
model.save_model(MODEL_PATH)
logger.info(f"模型已保存: {MODEL_PATH}")

# 特征重要性
importance = model.get_score(importance_type="gain")
for feat, score in sorted(importance.items(), key=lambda x: x[1], reverse=True)[:10]:
    logger.info(f"  {feat}: {score:.1f}")

# 最近10天
logger.info(f"\n{'日期':<10} {'同花顺':>6} {'v0.7':>7} {'v0.8':>7} {'v0.7偏差':>8} {'v0.8偏差':>8}")
for i in range(max(0, N-10), N):
    e7 = abs(y_actual[i] - v7_preds[i])
    e8 = abs(y_actual[i] - preds_rolling[i])
    star = " *" if e8 < e7 else ""
    logger.info(f"{ref_dates[i][:4]}-{ref_dates[i][4:6]}-{ref_dates[i][6:]:<4} "
                f"{y_actual[i]:>5.0f}% {v7_preds[i]:>6.1f}% {preds_rolling[i]:>6.1f}% "
                f"{e7:>7.1f}% {e8:>7.1f}%{star}")

logger.info("Done.")
