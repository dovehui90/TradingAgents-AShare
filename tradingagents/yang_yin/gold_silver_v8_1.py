"""金/银手指 v8.1 — 逻辑回归预测大盘信号（金=1/银=0）

11特征：7个阳谱EMA序列 + 4个全市场面板统计。
"""

import hashlib
import json
import logging

import numpy as np
import pandas as pd

from .pipeline import YangYinPipeline

logger = logging.getLogger(__name__)

FEATURE_COLS = [
    "prev_signal",
    "macd_5_10",
    "ema5_slope",
    "delta_1d",
    "bias_vs_ema5",
    "ema5_up_days",
    "ema5_down_days",
    "up_mean",
    "vol_ratio_ma5",
    "limit_up_ma5",
    "mean_chg_ma5",
]

INTERCEPT = 1.7483

COEF = {
    "prev_signal": 1.139, "macd_5_10": 0.597, "ema5_slope": 1.040,
    "delta_1d": 0.825, "bias_vs_ema5": 0.180, "ema5_up_days": 0.443,
    "ema5_down_days": 0.395, "up_mean": 0.678, "vol_ratio_ma5": 1.792,
    "limit_up_ma5": -0.190, "mean_chg_ma5": 1.640,
}

SCALER_MEAN = {
    "prev_signal": 0.1667, "macd_5_10": -0.4153, "ema5_slope": -0.0495,
    "delta_1d": -0.1759, "bias_vs_ema5": -2.8094, "ema5_up_days": 1.3333,
    "ema5_down_days": 1.5833, "up_mean": 2.5818, "vol_ratio_ma5": 1.6049,
    "limit_up_ma5": 103.4019, "mean_chg_ma5": 0.0541,
}

SCALER_STD = {
    "prev_signal": 0.9860, "macd_5_10": 5.7335, "ema5_slope": 6.4091,
    "delta_1d": 14.4080, "bias_vs_ema5": 31.7240, "ema5_up_days": 1.7743,
    "ema5_down_days": 2.0867, "up_mean": 0.5450, "vol_ratio_ma5": 0.6607,
    "limit_up_ma5": 27.3926, "mean_chg_ma5": 0.6042,
}


def compute_market_features(panel: pd.DataFrame, trade_date: str) -> dict | None:
    """从面板计算单个日期的4个大盘情绪特征原始值。"""
    day = panel[panel["trade_date"] == trade_date]
    if day.empty:
        return None

    up = day[day["pct_chg"] > 0]
    down = day[day["pct_chg"] < 0]

    up_mean = float(up["pct_chg"].mean()) if not up.empty else 0.0
    up_vol = up["vol"].sum() if not up.empty else 0.0
    down_vol = down["vol"].sum() if not down.empty else 1.0
    vol_ratio_raw = up_vol / max(down_vol, 1.0)
    limit_up_count = int((day["pct_chg"] >= 9.9).sum())
    mean_chg_raw = float(day["pct_chg"].mean())

    return {
        "trade_date": trade_date,
        "up_mean": up_mean,
        "vol_ratio_raw": vol_ratio_raw,
        "limit_up_count": limit_up_count,
        "mean_chg_raw": mean_chg_raw,
    }


def compute_market_features_all(panel: pd.DataFrame) -> pd.DataFrame:
    """向量化计算面板中所有日期的大盘情绪特征。

    等价于旧版逐日 compute_market_features 的结果，但用 groupby 一次算完，
    避免对 77 万行面板做 O(天数) 次全表过滤（原为 234 次 × 77 万行）。
    """
    if panel is None or panel.empty:
        return pd.DataFrame()

    df = panel[["trade_date", "pct_chg", "vol"]]

    is_up = df["pct_chg"] > 0
    is_down = df["pct_chg"] < 0
    is_limit_up = df["pct_chg"] >= 9.9

    g = df.groupby("trade_date", sort=True)
    all_dates = g["pct_chg"].mean().index  # 已排序的全日期索引

    up_mean = (
        df[is_up].groupby("trade_date", sort=True)["pct_chg"].mean()
        .reindex(all_dates).fillna(0.0)
    )
    up_vol = (
        df[is_up].groupby("trade_date", sort=True)["vol"].sum()
        .reindex(all_dates).fillna(0.0)
    )
    # 复刻旧语义 max(down_vol, 1.0)：无下跌股 → 1.0，且下限夹到 1.0
    down_vol = (
        df[is_down].groupby("trade_date", sort=True)["vol"].sum()
        .reindex(all_dates).fillna(1.0).clip(lower=1.0)
    )
    limit_up_count = (
        df[is_limit_up].groupby("trade_date", sort=True).size()
        .reindex(all_dates).fillna(0).astype(int)
    )
    mean_chg_raw = g["pct_chg"].mean()

    out = pd.DataFrame({
        "up_mean": up_mean.values,
        "vol_ratio_raw": (up_vol / down_vol).values,
        "limit_up_count": limit_up_count.values,
        "mean_chg_raw": mean_chg_raw.values,
    }, index=all_dates)
    out.index = out.index.astype(str)
    out.index.name = "trade_date"
    return out


def compute_features(
    yang_hist: pd.DataFrame,
    mkt_feat: pd.DataFrame,
    trade_date: str,
    prev_signal: int,
) -> dict | None:
    """计算单个日期的11个特征。"""
    yang_hist = yang_hist.sort_values("trade_date").reset_index(drop=True)
    dates = yang_hist["trade_date"].tolist()
    if trade_date not in dates:
        return None
    idx = dates.index(trade_date)

    yangpu = yang_hist["yang_pct"].values.astype(float)
    ema5 = pd.Series(yangpu).ewm(span=5, adjust=False).mean()
    ema10 = pd.Series(yangpu).ewm(span=10, adjust=False).mean()

    # 7 baseline features
    f_macd = float(ema5.iloc[idx] - ema10.iloc[idx])
    f_slope = float(ema5.iloc[idx] - ema5.iloc[idx - 1]) if idx > 0 else 0.0
    f_delta = float(yangpu[idx] - yangpu[idx - 1]) if idx > 0 else 0.0
    _e5 = float(ema5.iloc[idx])
    f_bias = (float(yangpu[idx]) - _e5) / _e5 * 100.0 if _e5 != 0 else 0.0

    f_up_days = 0
    for j in range(idx - 1, -1, -1):
        sl = float(ema5.iloc[j + 1] - ema5.iloc[j]) if j + 1 < len(ema5) else 0.0
        if sl > 0:
            f_up_days += 1
        else:
            break

    f_down_days = 0
    for j in range(idx - 1, -1, -1):
        sl = float(ema5.iloc[j + 1] - ema5.iloc[j]) if j + 1 < len(ema5) else 0.0
        if sl < 0:
            f_down_days += 1
        else:
            break

    # 4 market features with MA5 smoothing
    f_up_mean = 0.0
    f_vol_ratio_ma5 = 0.0
    f_limit_up_ma5 = 0.0
    f_mean_chg_ma5 = 0.0

    if trade_date in mkt_feat.index:
        # get up to 5 most recent dates including current
        mkt_sorted = mkt_feat.sort_index()
        pos = mkt_sorted.index.get_loc(trade_date)
        if isinstance(pos, slice) or isinstance(pos, np.ndarray):
            pos = pos[0] if len(pos) > 0 else None
        if pos is not None:
            start = max(0, int(pos) - 4)
            window = mkt_sorted.iloc[start : int(pos) + 1]
            f_up_mean = float(mkt_sorted.iloc[int(pos)]["up_mean"])
            f_vol_ratio_ma5 = float(window["vol_ratio_raw"].mean())
            f_limit_up_ma5 = float(window["limit_up_count"].mean())
            f_mean_chg_ma5 = float(window["mean_chg_raw"].mean())

    features = {
        "prev_signal": float(prev_signal),
        "macd_5_10": f_macd,
        "ema5_slope": f_slope,
        "delta_1d": f_delta,
        "bias_vs_ema5": f_bias,
        "ema5_up_days": float(f_up_days),
        "ema5_down_days": float(f_down_days),
        "up_mean": f_up_mean,
        "vol_ratio_ma5": f_vol_ratio_ma5,
        "limit_up_ma5": f_limit_up_ma5,
        "mean_chg_ma5": f_mean_chg_ma5,
    }
    return features


def predict_gold_finger(features: dict) -> tuple[int, float]:
    """返回 (signal, probability): signal=1金, 0银。"""
    z = 0.0
    for f in FEATURE_COLS:
        raw = features.get(f, 0.0) or 0.0
        if not np.isfinite(raw):
            return 1, 0.5
        z += (raw - SCALER_MEAN[f]) / SCALER_STD[f] * COEF[f]
    logit = INTERCEPT + z
    if not np.isfinite(logit):
        return 1, 0.5
    prob = 1.0 / (1.0 + np.exp(-logit))
    signal = 1 if prob >= 0.5 else 0
    return signal, float(prob)


def generate_history(
    panel: pd.DataFrame,
    yang_hist: pd.DataFrame,
) -> pd.DataFrame:
    """链式回填：按时间顺序计算每日金/银信号。"""
    if yang_hist.empty:
        return pd.DataFrame()

    yang_hist = yang_hist.sort_values("trade_date").reset_index(drop=True)
    mkt_feat = compute_market_features_all(panel)
    if mkt_feat.empty:
        logger.info("大盘情绪特征为空（盘中面板未更新？），市场特征全部置零")

    # 使用 yang_hist 中的所有日期，不限定 mkt_feat 范围
    dates = yang_hist["trade_date"].tolist()
    if not dates:
        return pd.DataFrame()

    results = []
    prev_signal = 1  # 默认金起步

    for td in dates:
        feats = compute_features(yang_hist, mkt_feat, td, prev_signal)
        if feats is None:
            continue
        signal, prob = predict_gold_finger(feats)
        results.append({"trade_date": td, "signal": signal, "prob": round(prob, 4)})
        prev_signal = signal

    if not results:
        return pd.DataFrame()
    df = pd.DataFrame(results)
    logger.info(
        "金/银手指历史生成: %d 天 | 金=%d 银=%d",
        len(df),
        (df["signal"] == 1).sum(),
        (df["signal"] == 0).sum(),
    )
    return df


def _history_path(pipeline: YangYinPipeline = None):
    if pipeline is None:
        pipeline = YangYinPipeline()
    return pipeline.summary_dir / "gold_finger_history.parquet"


def load_gold_finger_history(pipeline: YangYinPipeline = None) -> pd.DataFrame:
    path = _history_path(pipeline)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def save_gold_finger_history(df: pd.DataFrame, pipeline: YangYinPipeline = None):
    if df.empty:
        return
    path = _history_path(pipeline)
    df.to_parquet(path, index=False)
    # 写参数指纹：模型参数一旦变更，下次增量会检测到并回退全量重算
    try:
        with open(_fingerprint_path(pipeline), "w", encoding="utf-8") as f:
            json.dump({"fingerprint": _params_fingerprint()}, f)
    except Exception as e:
        logger.warning(f"金/银手指参数指纹写入失败: {e}")
    logger.info(f"金/银手指历史已保存: {path} ({len(df)} 条)")


def _fingerprint_path(pipeline: YangYinPipeline = None):
    if pipeline is None:
        pipeline = YangYinPipeline()
    return pipeline.summary_dir / "gold_finger_history.meta.json"


def _params_fingerprint() -> str:
    """模型参数指纹：COEF/SCALER/INTERCEPT 任一变化，指纹随之变化。

    用于增量场景：历史信号是「参数」的函数，参数变了历史必须全量重算，
    否则新旧日期用不同参数会产生前后不一致。
    """
    payload = json.dumps(
        {"intercept": INTERCEPT, "coef": COEF, "mean": SCALER_MEAN, "std": SCALER_STD},
        sort_keys=True, default=str,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _history_matches_params(pipeline: YangYinPipeline = None) -> bool:
    """已有历史是否匹配当前模型参数。无指纹/指纹不符 → False（触发全量回填）。"""
    fp = _fingerprint_path(pipeline)
    if not fp.exists():
        return False
    try:
        return json.loads(fp.read_text(encoding="utf-8")).get("fingerprint") == _params_fingerprint()
    except Exception:
        return False
