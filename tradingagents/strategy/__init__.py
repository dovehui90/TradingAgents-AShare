from .market_state import (
    calculate_bull_line,
    classify_market_state,
    fetch_sh_index_data,
    get_current_market_state,
)
from .fact_engine import compute_facts, format_fact_text
from .llm_decision import run_decision, build_system_prompt, build_decision_prompt
try:
    from .base_strategy import BaseStrategy, SignalResult, TradeOutcome
except ImportError:
    BaseStrategy = None  # type: ignore
    SignalResult = None  # type: ignore
    TradeOutcome = None  # type: ignore

try:
    from .v207b_v2 import V207bV2Strategy
    ShortTermStrategy = V207bV2Strategy
except ImportError:
    V207bV2Strategy = None  # type: ignore
    ShortTermStrategy = None  # type: ignore

try:
    from .volume_price_strategy import VolumePriceStrategy, VolumePriceSignal
    VolumePriceAnalysisStrategy = VolumePriceStrategy
except ImportError:
    VolumePriceStrategy = None  # type: ignore
    VolumePriceSignal = None  # type: ignore
    VolumePriceAnalysisStrategy = None  # type: ignore

try:
    from .signal_tracker import SignalTracker
except ImportError:
    SignalTracker = None  # type: ignore
