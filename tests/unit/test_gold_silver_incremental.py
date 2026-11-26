"""金/银手指 P0 优化对拍测试（向量化 + 增量 + 参数指纹）。

两套合成数据：
- 边界版：含全涨 / 全跌 / NaN / limit_up(=9.9) / 下跌 vol=0，用于验证向量化
  compute_market_features_all 与旧逐日循环的语义逐位对齐。
- 温和版：每日有涨有跌、涨跌幅温和，prob 不饱和，用于验证增量逻辑
  （链式 prev_signal 正确性、历史行不变、今天正确重算）。

全部合成数据自包含，不依赖线上数据，可在 CI 离线运行。
"""

import json

import numpy as np
import pandas as pd

from tradingagents.yang_yin.gold_silver_v8_1 import (
    compute_market_features_all,
    generate_history,
    _params_fingerprint,
    _history_matches_params,
)
from tradingagents.yang_yin.aggregation import _incremental_gold_finger


_DATES = ["20260105", "20260106", "20260107", "20260108", "20260109"]


# ──────────────────────────────────────────────────────────────────────────
# 边界数据：覆盖涨跌平 / 全涨 / 全跌 / NaN / limit_up(恰 9.9) / 下跌 vol=0
# ──────────────────────────────────────────────────────────────────────────

def _make_panel() -> pd.DataFrame:
    rows = [
        {"ts_code": "000001.SZ", "trade_date": "20260105", "close": 10.0, "vol": 1000.0, "pct_chg": 2.0},
        {"ts_code": "000002.SZ", "trade_date": "20260105", "close": 20.0, "vol": 2000.0, "pct_chg": -1.0},
        {"ts_code": "000003.SZ", "trade_date": "20260105", "close": 30.0, "vol": 3000.0, "pct_chg": 0.0},
        # 全涨 + limit_up 边界(恰 9.9) → vol_ratio 会很大（down_vol clip 到 1.0）
        {"ts_code": "000001.SZ", "trade_date": "20260106", "close": 11.0, "vol": 1100.0, "pct_chg": 9.9},
        {"ts_code": "000002.SZ", "trade_date": "20260106", "close": 21.0, "vol": 2100.0, "pct_chg": 5.0},
        {"ts_code": "000003.SZ", "trade_date": "20260106", "close": 31.0, "vol": 3100.0, "pct_chg": 3.0},
        # 全跌（无上涨股 → up_mean fillna(0)）
        {"ts_code": "000001.SZ", "trade_date": "20260107", "close": 10.0, "vol": 900.0, "pct_chg": -2.0},
        {"ts_code": "000002.SZ", "trade_date": "20260107", "close": 20.0, "vol": 1900.0, "pct_chg": -3.0},
        {"ts_code": "000003.SZ", "trade_date": "20260107", "close": 30.0, "vol": 2900.0, "pct_chg": -1.5},
        # NaN pct_chg + 下跌股 vol=0（测 NaN 排除 + down_vol clip 到 1.0）
        {"ts_code": "000001.SZ", "trade_date": "20260108", "close": 10.5, "vol": 1000.0, "pct_chg": float("nan")},
        {"ts_code": "000002.SZ", "trade_date": "20260108", "close": 20.5, "vol": 0.0, "pct_chg": -0.5},
        {"ts_code": "000003.SZ", "trade_date": "20260108", "close": 30.5, "vol": 3000.0, "pct_chg": 0.5},
        {"ts_code": "000001.SZ", "trade_date": "20260109", "close": 11.0, "vol": 1200.0, "pct_chg": 1.5},
        {"ts_code": "000002.SZ", "trade_date": "20260109", "close": 21.0, "vol": 2200.0, "pct_chg": -1.0},
        {"ts_code": "000003.SZ", "trade_date": "20260109", "close": 31.0, "vol": 3200.0, "pct_chg": 0.0},
    ]
    return pd.DataFrame(rows)


def _make_yang() -> pd.DataFrame:
    return pd.DataFrame({
        "trade_date": _DATES,
        "total_scored": [3, 3, 3, 3, 3],
        "yang_pct": [10.0, 22.0, 31.0, 44.0, 50.0],
        "yin_pct": [90.0, 78.0, 69.0, 56.0, 50.0],
        "updated_at": [f"{d[:4]}-{d[4:6]}-{d[6:]} 15:00" for d in _DATES],
    })


# ──────────────────────────────────────────────────────────────────────────
# 温和数据：每日有涨有跌、涨跌幅温和，prob 不饱和（增量逻辑测试专用）
# ──────────────────────────────────────────────────────────────────────────

def _make_panel_mild() -> pd.DataFrame:
    rows = []
    for d in _DATES:
        rows += [
            {"ts_code": "000001.SZ", "trade_date": d, "close": 10.0, "vol": 1000.0, "pct_chg": 1.5},
            {"ts_code": "000002.SZ", "trade_date": d, "close": 20.0, "vol": 2000.0, "pct_chg": -1.0},
            {"ts_code": "000003.SZ", "trade_date": d, "close": 30.0, "vol": 1500.0, "pct_chg": 0.3},
        ]
    return pd.DataFrame(rows)


def _make_yang_mild() -> pd.DataFrame:
    return pd.DataFrame({
        "trade_date": _DATES,
        "total_scored": [3, 3, 3, 3, 3],
        "yang_pct": [20.0, 25.0, 22.0, 28.0, 30.0],
        "yin_pct": [80.0, 75.0, 78.0, 72.0, 70.0],
        "updated_at": [f"{d[:4]}-{d[4:6]}-{d[6:]} 15:00" for d in _DATES],
    })


# ──────────────────────────────────────────────────────────────────────────
# 参考实现（旧循环 oracle）
# ──────────────────────────────────────────────────────────────────────────

def _ref_compute_market_features(panel: pd.DataFrame, trade_date: str):
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


def _ref_compute_market_features_all(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for td in sorted(panel["trade_date"].unique()):
        r = _ref_compute_market_features(panel, str(td))
        if r:
            rows.append(r)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["trade_date"] = df["trade_date"].astype(str)
    return df.set_index("trade_date")


# ──────────────────────────────────────────────────────────────────────────
# 测试
# ──────────────────────────────────────────────────────────────────────────

def test_compute_market_features_all_matches_reference():
    """向量化 == 旧逐日循环（含 NaN/全涨/全跌/limit_up 边界）。"""
    panel = _make_panel()
    got = compute_market_features_all(panel)
    ref = _ref_compute_market_features_all(panel)

    assert list(got.index) == list(ref.index), "index 顺序应一致"
    assert list(got.columns) == list(ref.columns), "列顺序应一致"
    for col in ["up_mean", "vol_ratio_raw", "limit_up_count", "mean_chg_raw"]:
        a = got[col].to_numpy(dtype=float)
        b = ref[col].to_numpy(dtype=float)
        assert np.allclose(a, b, rtol=1e-9, atol=1e-12, equal_nan=True), f"列 [{col}] 不一致"


def test_generate_history_is_deterministic():
    panel = _make_panel_mild()
    yang = _make_yang_mild()
    assert generate_history(panel, yang).equals(generate_history(panel, yang))


def test_incremental_equals_full():
    """增量（从 N-1 天历史算今天）== 全量 N 天。"""
    panel = _make_panel_mild()
    yang = _make_yang_mild()
    full = generate_history(panel, yang)

    prev = full.iloc[:-1].copy()
    inc = _incremental_gold_finger(panel, yang, prev)

    assert inc.equals(full), f"增量应等于全量：\n{inc}\nvs\n{full}"


def test_incremental_intraday_recompute_preserves_history():
    """盘中二次扫描：历史行原样不变、今天正确重算为新值。"""
    panel = _make_panel_mild()
    yang = _make_yang_mild()
    full = generate_history(panel, yang)
    today = _DATES[-1]

    # 盘中阳谱值变化
    yang_mod = yang.copy()
    yang_mod.loc[yang_mod["trade_date"] == today, "yang_pct"] = 42.0
    full_mod = generate_history(panel, yang_mod)  # 新阳谱全量 oracle

    # 历史已含今天旧值，增量重算
    inc = _incremental_gold_finger(panel, yang_mod, full.copy())

    # 增量结果 == 新阳谱全量结果（历史不变 + 今天正确更新）
    assert inc.equals(full_mod)

    # 显式验证历史行（今天之前）与旧值一致
    hist_before = full[full["trade_date"] != today].reset_index(drop=True)
    hist_after = inc[inc["trade_date"] != today].reset_index(drop=True)
    assert hist_before.equals(hist_after), "历史行不应被改动"


def test_incremental_prev_signal_uses_prior_day():
    """链式 prev_signal 必须取「待算日前一天」，而非历史最后一行。

    若错误取历史末行（=今天旧值），盘中二次扫描会用今天的旧值当 prev，
    今天重算的 prob 会偏离全量 oracle。
    """
    panel = _make_panel_mild()
    yang = _make_yang_mild()
    full = generate_history(panel, yang)
    today = _DATES[-1]

    yesterday_signal = int(full.iloc[-2]["signal"])
    # 构造「含今天、但今天 signal 被写错」的历史（与正确 prev 相反）
    wrong_today = pd.DataFrame([{
        "trade_date": today,
        "signal": 1 - yesterday_signal,
        "prob": 0.9999,
    }])
    hist_with_wrong = pd.concat([full.iloc[:-1], wrong_today], ignore_index=True)

    inc = _incremental_gold_finger(panel, yang, hist_with_wrong.copy())

    inc_today = inc[inc["trade_date"] == today]
    full_today = full[full["trade_date"] == today]
    # 增量今天 == 全量今天（说明 prev_signal 正确取到昨天，而非错误的今天旧值）
    assert inc_today["signal"].iloc[0] == full_today["signal"].iloc[0]
    assert np.isclose(inc_today["prob"].iloc[0], full_today["prob"].iloc[0])


def test_params_fingerprint_sensitive_and_stable():
    fp = _params_fingerprint()
    assert fp and fp == _params_fingerprint(), "指纹应稳定"

    import tradingagents.yang_yin.gold_silver_v8_1 as gs
    orig = gs.COEF["prev_signal"]
    gs.COEF["prev_signal"] = orig + 1.0
    changed = _params_fingerprint()
    gs.COEF["prev_signal"] = orig
    assert fp != changed, "改 COEF 后指纹应变化"


class _FakePipeline:
    def __init__(self, d):
        self.summary_dir = d


def test_history_matches_params(tmp_path):
    pipe = _FakePipeline(tmp_path)
    # 无指纹文件 → 不匹配（触发全量回填）
    assert _history_matches_params(pipe) is False

    (tmp_path / "gold_finger_history.meta.json").write_text(
        json.dumps({"fingerprint": _params_fingerprint()}), encoding="utf-8"
    )
    assert _history_matches_params(pipe) is True

    # 错误指纹 → 不匹配
    (tmp_path / "gold_finger_history.meta.json").write_text(
        json.dumps({"fingerprint": "deadbeef00000000"}), encoding="utf-8"
    )
    assert _history_matches_params(pipe) is False
