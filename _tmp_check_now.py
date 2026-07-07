import sys, os
sys.path.insert(0, r"d:\AIProjects\TradingAgents-AShare")
os.chdir(r"d:\AIProjects\TradingAgents-AShare")

import pandas as pd
import numpy as np

# Load feature panel
feat = pd.read_parquet(r"data\yang_yin_cache\panel_features.parquet")

# Simulate factor computation for 20260622
from tradingagents.yang_yin.factors_v7 import compute_factors

# Need prev_yangpu
prev = 41.0  # from 6/18 post-market

factors = compute_factors(feat, "20260622", prev_yangpu=prev)
if factors:
    from tradingagents.yang_yin.model_v7 import predict_yangpu, FEATURE_COLS, COEF, X_MEAN, X_STD, INTERCEPT
    pred = predict_yangpu(factors)
    print(f"Predicted yang_pct: {pred:.1f}%")
    print(f"Actual (from history): 38.9%")
    print()
    print("Factor values:")
    for f in FEATURE_COLS:
        val = factors.get(f, 0)
        coef = COEF[f]
        mean = X_MEAN[f]
        std = X_STD[f]
        scaled = (val - mean) / std
        contrib = scaled * coef
        print(f"  {f:25s}: raw={val:8.4f} scaled={scaled:8.4f} coef={coef:8.4f} contrib={contrib:8.4f}")
    print(f"  {'INTERCEPT':25s}: {INTERCEPT}")
    print(f"  {'SUM':25s}: {sum((np.array([factors.get(f,0) for f in FEATURE_COLS]) - np.array([X_MEAN[f] for f in FEATURE_COLS])) / np.array([X_STD[f] for f in FEATURE_COLS]) * np.array([COEF[f] for f in FEATURE_COLS])) + INTERCEPT:.4f}")
