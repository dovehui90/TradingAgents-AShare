"""阳谱v0.8训练: XGBoost + 资金流因子

1. 加载同花顺真实值CSV (110天)
2. 逐日计算21因子 (含money_mean/money_yang，从Tushare获取)
3. 训练XGBoost回归
4. 对比v0.7岭回归MAE
5. 保存模型到 model_v8.json
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import time
import numpy as np
import pandas as pd
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from tradingagents.yang_yin.pipeline import YangYinPipeline
from tradingagents.yang_yin.factors_v7 import FACTOR_NAMES
from tradingagents.yang_yin.model_v7 import FEATURE_COLS as V7_FEATURE_COLS, predict_yangpu as predict_v7

# ── 加载真实值 ──
CSV_PATH = r"D:\下载\_app_data_所有对话_主对话_yangpu_data_yangpu_comparison_v7 (1).csv"
ref = pd.read_csv(CSV_PATH)
ref = ref.set_index("trade_date")
logger.info(f"参考数据: {len(ref)} 天, 列: {list(ref.columns)}")

# ── 加载面板 ──
pipeline = YangYinPipeline()
panel = pipeline.load_feature_panel()
if panel is None:
    panel = pipeline.load_panel()
    if panel is None:
        logger.info("构建面板...")
        panel = pipeline.build_panel()
        pipeline.build_feature_panel()
        panel = pipeline.load_feature_panel()
logger.info(f"面板: {len(panel)} 行, {panel['trade_date'].nunique()} 天")

if "rsi14" not in panel.columns:
    logger.info("构建特征面板...")
    panel = pipeline.build_feature_panel()
logger.info(f"特征面板列: {list(panel.columns)}")

# ── 资金流缓存 ──
import tushare as ts
TOKEN = os.environ.get("TUSHARE_TOKEN", "")
ts.set_token(TOKEN)
pro = ts.pro_api()
mf_cache_dir = pipeline.summary_dir / "moneyflow"
mf_cache_dir.mkdir(parents=True, exist_ok=True)


def get_moneyflow(trade_date: str) -> dict[str, float]:
    """获取单日全市场资金流，返回 {ts_code: net_mf_vol}。优先读缓存。"""
    cache_path = mf_cache_dir / f"{trade_date}.parquet"
    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        result = {}
        for _, row in df.iterrows():
            result[row.get("ts_code", "")] = float(row.get("net_mf_vol", 0) or 0)
        return result

    try:
        df = pro.moneyflow(trade_date=trade_date)
        if df is not None and not df.empty:
            df.to_parquet(cache_path, index=False)
            result = {}
            for _, row in df.iterrows():
                result[row.get("ts_code", "")] = float(row.get("net_mf_vol", 0) or 0)
            return result
    except Exception as e:
        logger.warning(f"资金流获取失败 {trade_date}: {e}")
    return {}


def compute_factors_with_moneyflow(panel, trade_date: str, prev_yangpu: float,
                                   moneyflow: dict[str, float]) -> dict[str, float] | None:
    """计算因子（含资金流），复用 _compute_factors_from_features 逻辑。"""
    from tradingagents.yang_yin.factors_v7 import compute_factors

    factors = compute_factors(panel, trade_date, prev_yangpu=prev_yangpu)
    if factors is None:
        return None

    # 覆写 money 因子
    day = panel[panel["trade_date"] == trade_date]
    n = len(day)
    mf_vals = []
    mf_positive = 0
    for _, row in day.iterrows():
        code = row["ts_code"]
        net = moneyflow.get(code, 0.0)
        mf_vals.append(net)
        if net > 0:
            mf_positive += 1

    factors["money_mean"] = float(np.mean(mf_vals)) if mf_vals else 0.0
    factors["money_yang"] = float(mf_positive / n) if n > 0 else 0.0
    return factors


# ── 收集特征矩阵 ──
ref_dates = sorted(str(d) for d in ref.index if str(d) in panel["trade_date"].values)
logger.info(f"匹配参考日期: {len(ref_dates)} / {len(ref)}")

X_rows = []
y_actual = []
prev_pred = 50.0
mf_cache: dict[str, dict[str, float]] = {}

for i, dt in enumerate(ref_dates):
    # 获取资金流
    if dt not in mf_cache:
        mf_cache[dt] = get_moneyflow(dt)
        if i % 10 == 0:
            logger.info(f"  资金流进度: {i+1}/{len(ref_dates)} ({dt})")
        time.sleep(0.15)  # Tushare rate limit

    factors = compute_factors_with_moneyflow(panel, dt, prev_yangpu=prev_pred,
                                              moneyflow=mf_cache[dt])
    if factors is None:
        continue

    actual = ref.loc[int(dt), "actual"]
    row = {f: factors.get(f, 0.0) for f in V7_FEATURE_COLS}
    X_rows.append(row)
    y_actual.append(actual)
    prev_pred = predict_v7(factors)  # v0.7预测值用于下一日prev_yangpu

logger.info(f"特征矩阵: {len(X_rows)} 行 x {len(V7_FEATURE_COLS)} 列")

# ── 训练XGBoost ──
import xgboost as xgb

X = pd.DataFrame(X_rows)
y = pd.Series(y_actual)
logger.info(f"训练数据: {X.shape}")

# 时序划分: 前80%训练, 后20%验证
split_idx = int(len(X) * 0.8)
X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

dtrain = xgb.DMatrix(X_train, label=y_train)
dval = xgb.DMatrix(X_val, label=y_val)

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

evals = [(dtrain, "train"), (dval, "val")]
model = xgb.train(params, dtrain, num_boost_round=500, evals=evals,
                  early_stopping_rounds=50, verbose_eval=50)

# ── 评估 ──
# 全量预测（滚动prev_yangpu，同模式2）
all_preds = []
prev_pred_v8 = 50.0
for i, dt in enumerate(ref_dates):
    factors = compute_factors_with_moneyflow(panel, dt, prev_yangpu=prev_pred_v8,
                                              moneyflow=mf_cache.get(dt, {}))
    if factors is None:
        continue
    row_data = {f: factors.get(f, 0.0) for f in V7_FEATURE_COLS}
    dtest = xgb.DMatrix(pd.DataFrame([row_data]))
    pred = float(model.predict(dtest)[0])
    pred = max(0.0, min(100.0, pred))
    all_preds.append({"trade_date": dt, "actual": ref.loc[int(dt), "actual"], "predicted": round(pred, 2)})
    prev_pred_v8 = pred

df_result = pd.DataFrame(all_preds)
df_result["abs_diff"] = abs(df_result["actual"] - df_result["predicted"])
mae_v8 = df_result["abs_diff"].mean()
pct5_v8 = (df_result["abs_diff"] <= 5).mean() * 100
pct10_v8 = (df_result["abs_diff"] > 10).mean() * 100

# v0.7 同样条件下对比
df_result_v7 = ref.loc[[int(d) for d in ref_dates if int(d) in df_result["trade_date"].values]]
if "abs_diff" in df_result_v7.columns:
    mae_v7 = df_result_v7["abs_diff"].mean()
else:
    mae_v7 = abs(df_result_v7["actual"] - df_result_v7["predicted"]).mean()

logger.info(f"\n=== 结果对比 ===")
logger.info(f"v0.7 岭回归 MAE: {mae_v7:.2f}%")
logger.info(f"v0.8 XGBoost MAE: {mae_v8:.2f}%")
logger.info(f"改善: {(mae_v7 - mae_v8):.2f}% ({(1 - mae_v8/mae_v7)*100:.1f}%)")
logger.info(f"v0.8 ≤5%占比: {pct5_v8:.0f}%")
logger.info(f"v0.8 >10%占比: {pct10_v8:.0f}%")

# 最大偏差
max_row = df_result.loc[df_result["abs_diff"].idxmax()]
logger.info(f"最大偏差: {max_row.abs_diff:.2f}% ({max_row.trade_date}) 同花顺:{max_row.actual}% 预测:{max_row.predicted}%")

# ── 保存模型 ──
MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "tradingagents", "yang_yin", "model_v8.json")
model.save_model(MODEL_PATH)
logger.info(f"模型已保存: {MODEL_PATH}")

# ── 保存特征重要性 ──
importance = model.get_score(importance_type="gain")
importance_sorted = sorted(importance.items(), key=lambda x: x[1], reverse=True)
logger.info(f"\n=== 特征重要性 (gain) ===")
for feat, score in importance_sorted[:10]:
    logger.info(f"  {feat}: {score:.1f}")

logger.info("Done.")
