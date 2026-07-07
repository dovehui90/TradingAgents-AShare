"""阳谱模型 v0.8 — XGBoost + 资金流因子

训练: 同花顺前日actual做prev_yangpu, self-rolling收敛
MAE: 1.05% (v0.7: 1.87%, 改善44%)
"""

import os
import numpy as np
import pandas as pd
import xgboost as xgb
from .model_v7 import FEATURE_COLS

_model = None


def _load_model():
    global _model
    if _model is None:
        path = os.path.join(os.path.dirname(__file__), "model_v8.json")
        _model = xgb.Booster()
        _model.load_model(path)
    return _model


def predict_yangpu_v8(factors: dict[str, float]) -> float:
    model = _load_model()
    row_data = {f: factors.get(f, 0.0) or 0.0 for f in FEATURE_COLS}
    dtest = xgb.DMatrix(pd.DataFrame([row_data]))
    pred = float(model.predict(dtest)[0])
    if pred < 0:
        return 0.0
    if pred > 100:
        return 100.0
    return pred
