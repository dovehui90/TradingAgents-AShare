from .market_state import (
    calculate_bull_line,
    classify_market_state,
    fetch_sh_index_data,
    get_current_market_state,
)
from .fact_engine import compute_facts, format_fact_text
from .llm_decision import run_decision, build_system_prompt, build_decision_prompt
from .base_strategy import BaseStrategy, SignalResult, TradeOutcome
from .v207b_v2 import V207bV2Strategy
from .volume_price_strategy import VolumePriceStrategy, VolumePriceSignal
from .signal_tracker import SignalTracker

# 短线策略（基于V207b_v2）
ShortTermStrategy = V207bV2Strategy

# 量价分析策略（独立）
VolumePriceAnalysisStrategy = VolumePriceStrategy
