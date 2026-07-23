"""Pydantic request/response schemas extracted from api/main.py."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_serializer

from tradingagents.dataflows.trade_calendar import cn_today_str


def _serialize_datetime_utc(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat()

class UserContextInput(BaseModel):
    objective: Optional[str] = Field(None, description="用户目标动作，如建仓/加仓/减仓/止损/观察")
    risk_profile: Optional[str] = Field(None, description="风险偏好，如保守/平衡/激进")
    investment_horizon: Optional[str] = Field(None, description="持有周期，如短线/波段/中线")
    cash_available: Optional[float] = Field(None, description="可用资金")
    current_position: Optional[float] = Field(None, description="当前持仓数量")
    current_position_pct: Optional[float] = Field(None, description="当前仓位占比")
    average_cost: Optional[float] = Field(None, description="当前持仓成本")
    max_loss_pct: Optional[float] = Field(None, description="最大容忍亏损百分比")
    constraints: List[str] = Field(default_factory=list, description="用户的硬约束列表")
    user_notes: Optional[str] = Field(None, description="用户补充说明")


class AnalyzeRequest(UserContextInput):
    symbol: str = Field(default="", description="股票代码，如 600519.SH（当 query 包含代码时可省略）")
    trade_date: str = Field(default_factory=cn_today_str, description="交易日期 YYYY-MM-DD")
    selected_analysts: List[str] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals", "macro", "smart_money", "volume_price"]
    )
    config_overrides: Dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    # When set, triggers intent-driven analysis via streaming dual-horizon path
    query: Optional[str] = Field(default=None, description="自然语言查询，如：分析贵州茅台短线机会")
    horizons: List[str] = Field(default_factory=lambda: ["short"], description="分析周期列表，如 ['short'] 或 ['short','medium']")
    # Pre-parsed intent from _ai_extract_symbol_and_date (avoids second LLM call in _run_job)
    user_intent: Optional[Dict[str, Any]] = Field(default=None, description="预解析的用户意图，由 chat_completions 传入")


class AnalyzeResponse(BaseModel):
    job_id: str
    status: Literal["pending", "running", "completed", "failed"]
    created_at: str


class BatchScheduledTriggerJob(BaseModel):
    item_id: str
    job_id: str
    symbol: str
    name: str
    status: Literal["pending", "running", "completed", "failed"]
    created_at: str
    current_position: Optional[float] = None
    average_cost: Optional[float] = None
    waiting_ahead_count: Optional[int] = None
    scheduled_running_count: Optional[int] = None
    scheduled_concurrency_limit: Optional[int] = None


class BatchScheduledTriggerResponse(BaseModel):
    summary: Dict[str, int]
    jobs: List[BatchScheduledTriggerJob]


class BatchAnalyzeRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=1, description="要批量分析的股票代码列表（不限制数量，自动排队）")
    trade_date: Optional[str] = Field(default=None, description="交易日期 YYYY-MM-DD，默认今天")
    selected_analysts: Optional[List[str]] = Field(default=None, description="要使用的分析师列表")
    horizons: Optional[List[str]] = Field(default=None, description="分析周期，如 ['short'] 或 ['short','medium']")


class BatchAnalyzeJobItem(BaseModel):
    symbol: str
    job_id: str
    name: str = ""
    status: Literal["pending", "running", "completed", "failed", "reused"]
    reused_report_id: Optional[str] = None
    error: Optional[str] = None


class BatchAnalyzeResponse(BaseModel):
    batch_id: str
    jobs: List[BatchAnalyzeJobItem]
    summary: Dict[str, int]  # {"total": N, "new": N, "reused": N, "failed": N}


class BatchAnalyzeStatusResponse(BaseModel):
    batch_id: str
    total: int
    completed: int
    failed: int
    pending: int
    running: int
    jobs: List[BatchAnalyzeJobItem]


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["pending", "running", "completed", "failed"]
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    symbol: str
    trade_date: str
    error: Optional[str] = None
    waiting_ahead_count: Optional[int] = None
    scheduled_running_count: Optional[int] = None
    scheduled_concurrency_limit: Optional[int] = None


class ChatMessage(BaseModel):
    role: str
    content: Any


class ChatCompletionRequest(UserContextInput):
    model: Optional[str] = "tradingagents-ashare"
    messages: List[ChatMessage]
    stream: bool = True
    selected_analysts: List[str] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals", "macro", "smart_money", "volume_price"]
    )
    config_overrides: Dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False


class KlineResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    start_date: str
    end_date: str
    candles: List[Dict[str, Any]]


class NiuxiongPoint(BaseModel):
    date: str
    close: float
    decision_line: Optional[float] = None
    bull_line: Optional[float] = None
    bear_line: Optional[float] = None
    orbit_line: Optional[float] = None
    orbit_direction: Optional[int] = None
    buy_signal: bool = False
    sell_signal: bool = False


class NiuxiongResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    points: List[NiuxiongPoint]
    signal: Optional[Dict[str, Any]] = None


class GSPoint(BaseModel):
    date: str
    close: float
    bb_line: Optional[float] = None
    a_line: Optional[float] = None
    trend_state: Optional[str] = None
    kline_color: Optional[int] = None
    zj_bias: Optional[float] = None
    buy_signal: bool = False
    sell_signal: bool = False


class GSResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    points: List[GSPoint]
    signal: Optional[Dict[str, Any]] = None


class RadarPoint(BaseModel):
    date: str
    close: float
    radar_wave: Optional[float] = None
    radar_avg: Optional[float] = None
    radar_retail: Optional[float] = None
    ths_zhuli: Optional[float] = None
    ths_sanhu: Optional[float] = None
    radar_buy: bool = False
    radar_sell: bool = False
    radar_top: bool = False
    radar_down: bool = False


class RadarResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    points: List[RadarPoint]
    signal: Optional[Dict[str, Any]] = None


class PositionPoint(BaseModel):
    date: str
    close: float
    position_index: Optional[float] = None
    zone: Optional[str] = None


class PositionResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    points: List[PositionPoint]
    signal: Optional[Dict[str, Any]] = None


class VolumeWashPoint(BaseModel):
    date: str
    close: float
    volume: float
    vol_wash_type: int  # 0=普通, 2=缩量洗盘, 3=温和放量, 4=放量突破


class VolumeWashResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    points: List[VolumeWashPoint]
    signal: Optional[Dict[str, Any]] = None


class AiGravityPoint(BaseModel):
    date: str
    close: float
    ai_gravity: Optional[float] = None
    willingness: Optional[float] = None
    buy_signal: bool = False


class AiGravityResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    points: List[AiGravityPoint]
    signal: Optional[Dict[str, Any]] = None


# Fund Flow Models
class FundFlowPoint(BaseModel):
    date: str
    close: float
    main_net: Optional[float] = None
    main_pct: Optional[float] = None
    super_large_net: Optional[float] = None
    large_net: Optional[float] = None
    medium_net: Optional[float] = None
    small_net: Optional[float] = None


class FundFlowResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    points: List[FundFlowPoint]
    signal: Optional[Dict[str, Any]] = None


# Bollinger Deviation Models (布林乖离)
class BollingerDeviationPoint(BaseModel):
    date: str
    close: float
    mccd: float  # 2*(C-MA20)*VOL
    ub: Optional[float] = None   # 1.618*(UP-MA20)
    lb: Optional[float] = None   # 1.618*(LP-MA20)
    uub: Optional[float] = None  # 2.33*(UP-MA20)
    llb: Optional[float] = None  # 2.33*(LP-MA20)
    is_cross_lp: bool = False    # CROSS(C, LP) 乖离反转
    is_warning: bool = False     # MCCD>UUB & 收阴


class BollingerDeviationResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    points: List[BollingerDeviationPoint]
    signal: Optional[Dict[str, Any]] = None


# Trend Strength Models (趋势强度指数)
class TrendStrengthPoint(BaseModel):
    date: str
    close: float
    trend_strength: Optional[float] = None
    zone: Optional[str] = None


class TrendStrengthResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    points: List[TrendStrengthPoint]
    signal: Optional[Dict[str, Any]] = None


# ─── Stock Screener ─────────────────────────────────────────────────────────

class ScreenerFilter(BaseModel):
    date: Optional[str] = None
    market_cap_min: Optional[float] = None          # 亿
    market_cap_max: Optional[float] = None          # 亿
    board_symbols: Optional[List[str]] = None        # 概念板块代码列表
    position_zones: Optional[List[str]] = None       # overbought/high/neutral/low/oversold
    gs_signal: Optional[str] = None                  # G / S / G_zone / S_zone
    orbit_status: Optional[List[str]] = None         # cross_up / above2 / cross_down / below2
    decision_status: Optional[str] = None             # above / below
    bull_status: Optional[str] = None                 # above / below
    trend_status: Optional[str] = None                # to_red / to_green / red_hold / green_hold
    radar_wave_min: Optional[float] = None
    radar_wave_max: Optional[float] = None
    candidate_limit: int = 300
    result_limit: int = 100


class ScreenerResultItem(BaseModel):
    symbol: str
    name: str
    price: Optional[float] = None
    change_pct: Optional[float] = None
    market_cap: Optional[float] = None               # 亿
    position_zone: Optional[str] = None
    gs_status: Optional[str] = None
    orbit_status: Optional[str] = None
    decision_status: Optional[str] = None
    bull_status: Optional[str] = None
    trend_status: Optional[str] = None
    radar_wave: Optional[float] = None
    concepts: Optional[str] = None                    # 概念/行业，逗号分隔


class ScreenerResponse(BaseModel):
    results: List[ScreenerResultItem]
    total_candidates: int
    total_filtered: int
    elapsed_ms: int
    data_date: Optional[str] = None


# TD Sequential Models (神奇九转)
class TdPoint(BaseModel):
    date: str
    close: float
    buy_count: int = 0
    sell_count: int = 0


class TdResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    points: List[TdPoint]
    signal: Optional[Dict[str, Any]] = None


# Support Resistance Models (支撑压力位)
class SupportResistancePoint(BaseModel):
    date: str
    close: float
    support: Optional[float] = None
    resistance: Optional[float] = None
    buy_signal: bool = False
    sell_signal: bool = False


class SupportResistanceResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    points: List[SupportResistancePoint]
    signal: Optional[Dict[str, Any]] = None


# Bias Analysis Models (乖离率分析)
class BiasPoint(BaseModel):
    date: str
    close: float
    ma13: float
    bias_pct: float  # MA13乖离率%
    zj_bias: Optional[float] = None  # 牛熊线乖离率 (a_line/bb-1)%


class BiasStats(BaseModel):
    mean: float
    median: float
    std: float
    max_val: float
    min_val: float
    skewness: float
    quantile_10: float
    quantile_25: float
    quantile_75: float
    quantile_90: float


class BiasProbabilityRow(BaseModel):
    threshold_label: str  # e.g. "P75(>11.8%)"
    threshold_value: float
    day_1_pct: float  # 回撤/反弹概率%
    day_3_pct: float
    day_5_pct: float
    day_10_pct: float
    day_10_avg_ret: float  # 10日平均收益%
    sample_count: int


class BiasAnalysisResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    start_date: str
    end_date: str
    total_days: int
    stats: BiasStats
    points: List[BiasPoint]  # 每日乖离率时序数据
    distribution: Dict[str, int]  # {区间: 天数}
    pullback_after_high: List[BiasProbabilityRow]  # 正向高位→回撤
    rebound_after_low: List[BiasProbabilityRow]  # 负向低位→反弹
    pullback_summary: str  # 结论摘要
    rebound_summary: str


class BiasSnapshotResponse(BaseModel):
    """盘中实时乖离率快照"""
    symbol: str
    name: Optional[str] = None
    price: float          # 当前价
    change_pct: float     # 涨跌幅%
    ma13: float           # MA13均线值
    bias_pct: float       # MA13乖离率%
    zj_bias: Optional[float] = None  # 牛熊线乖离率%
    timestamp: str        # 行情时间
    market_phase: str     # 交易时段: pre_open/in_session/lunch_break/post_close/closed


# Dark Pool Analysis Models
class DarkPoolEvent(BaseModel):
    start: str
    end: str
    duration_min: float
    direction: str  # '买' | '卖'
    volume: int
    base_score: int
    quality_score: int
    level: str  # '暗盘' | '疑似' | '低分'
    indicators: str


class DarkPoolDimension(BaseModel):
    total_events: int = 0
    high_conf_count: int = 0
    suspected_count: int = 0
    split_vol: int = 0
    split_vol_pct: float = 0.0
    active_buy_vol: int = 0
    active_sell_vol: int = 0
    direction: str = ''
    events: List[DarkPoolEvent] = []


class DarkPoolInstitutional(BaseModel):
    inst_participation_pct: float = 0
    inst_net_wan: float = 0
    retail_net_wan: float = 0
    tick_net_wan: float = 0
    big_active_buy_wan: float = 0
    big_active_sell_wan: float = 0
    intent: str = ''


class DarkPoolTail(BaseModel):
    tail_vol_ratio_pct: float = 0
    tail_chg_pct: float = 0
    full_chg_pct: float = 0
    signal: str = ''


class DarkPoolComposite(BaseModel):
    signals: List[str] = []
    confidence: int = 0
    verdict: str = ''
    intent: str = ''
    prediction: str = ''
    key_facts: List[str] = []


class DarkPoolMarket(BaseModel):
    open: float = 0
    high: float = 0
    low: float = 0
    close: float = 0
    chg_pct: float = 0
    total_vol: int = 0
    total_amt_wan: float = 0
    tick_count: int = 0


class DarkPoolAnalysisResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    date: str
    market: Optional[DarkPoolMarket] = None
    dim1_institutional: Optional[DarkPoolInstitutional] = None
    dim2_tail: Optional[DarkPoolTail] = None
    dim3_split: Optional[DarkPoolDimension] = None
    composite: Optional[DarkPoolComposite] = None
    error: Optional[str] = None


# Report API Models
class ReportCreateRequest(BaseModel):
    symbol: str = Field(..., description="股票代码")
    trade_date: str = Field(..., description="交易日期 YYYY-MM-DD")
    decision: Optional[str] = Field(None, description="交易决策")
    result_data: Optional[Dict[str, Any]] = Field(None, description="完整分析结果")


class ReportResponse(BaseModel):
    id: str
    user_id: Optional[str]
    symbol: str
    name: Optional[str] = None
    trade_date: str
    status: Literal["pending", "running", "completed", "failed"] = "completed"
    error: Optional[str] = None
    decision: Optional[str]
    direction: Optional[str]
    confidence: Optional[int]
    target_price: Optional[float]
    stop_loss_price: Optional[float]
    risk_items: Optional[List[Dict[str, Any]]] = None
    key_metrics: Optional[List[Dict[str, Any]]] = None
    analyst_traces: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    waiting_ahead_count: Optional[int] = None
    scheduled_running_count: Optional[int] = None
    scheduled_concurrency_limit: Optional[int] = None

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "updated_at", when_used="json")
    def serialize_report_datetimes(self, value: Optional[datetime]) -> Optional[str]:
        return _serialize_datetime_utc(value)


class ReportDetailResponse(ReportResponse):
    market_report: Optional[str]
    sentiment_report: Optional[str]
    news_report: Optional[str]
    fundamentals_report: Optional[str]
    macro_report: Optional[str]
    smart_money_report: Optional[str]
    volume_price_report: Optional[str]
    game_theory_report: Optional[str]
    investment_plan: Optional[str]
    trader_investment_plan: Optional[str]
    final_trade_decision: Optional[str]
    result_data: Optional[Dict[str, Any]]


class ReportListResponse(BaseModel):
    total: int
    reports: List[ReportResponse]


class ReportBatchDeleteRequest(BaseModel):
    report_ids: List[str] = Field(default_factory=list)


class ReportBatchDeleteResponse(BaseModel):
    deleted_ids: List[str]
    missing_ids: List[str]


class LatestReportsBySymbolsRequest(BaseModel):
    symbols: List[str] = Field(default_factory=list)


class LatestReportsBySymbolsResponse(BaseModel):
    reports: List[ReportResponse]


class PortfolioOverviewResponse(BaseModel):
    watchlist: List[dict]
    scheduled: List[dict]
    latest_reports: List[ReportResponse]
    portfolio_import: Optional[dict] = None


class WatchlistAddRequest(BaseModel):
    text: Optional[str] = None
    symbol: Optional[str] = None


class WatchlistUpdateRequest(BaseModel):
    notes: Optional[str] = None


class ScheduledBatchIdsRequest(BaseModel):
    item_ids: List[str] = Field(default_factory=list)


class ScheduledBatchUpdateRequest(BaseModel):
    item_ids: List[str] = Field(default_factory=list)
    is_active: Optional[bool] = None
    horizon: Optional[str] = None
    trigger_time: Optional[str] = None


class AnnouncementItemResponse(BaseModel):
    title: str
    detail: str


class AnnouncementResponse(BaseModel):
    id: str
    tag: Optional[str] = None
    title: str
    summary: Optional[str] = None
    published_at: str
    items: List[AnnouncementItemResponse]
    cta_label: Optional[str] = None
    cta_path: Optional[str] = None


class LatestAnnouncementResponse(BaseModel):
    announcement: Optional[AnnouncementResponse] = None


# ─── Briefing Response Models ────────────────────────────────────────

class BriefingItem(BaseModel):
    id: str
    date: str
    status: str


class BriefingListResponse(BaseModel):
    items: List[BriefingItem]


class BriefingDetailResponse(BaseModel):
    id: str
    date: str
    status: str
    error: Optional[str] = None
    market_data: Optional[dict] = None
    top_news: Optional[list] = None
    watchlist_analysis: Optional[list] = None
    portfolio_analysis: Optional[list] = None
    trading_advice: Optional[dict] = None
    opportunity_report: Optional[dict] = None
    sentiment_report: Optional[dict] = None
    news_briefing: Optional[dict] = None
    generated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class UserResponse(BaseModel):
    id: str
    email: str
    is_admin: bool = False
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    email_report_enabled: bool = True

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "last_login_at", when_used="json")
    def serialize_user_datetimes(self, value: Optional[datetime]) -> Optional[str]:
        return _serialize_datetime_utc(value)


class AuthRequestCodeRequest(BaseModel):
    email: str


class AuthVerifyCodeRequest(BaseModel):
    email: str
    code: str


class AuthVerifyCodeResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class UserRuntimeConfigResponse(BaseModel):
    llm_provider: str
    deep_think_llm: str
    quick_think_llm: str
    backend_url: str
    max_debate_rounds: int
    max_risk_discuss_rounds: int
    has_api_key: bool = False
    has_wecom_webhook: bool = False
    wecom_webhook_display: Optional[str] = None
    server_fallback_enabled: bool = True
    email_report_enabled: bool = True
    wecom_report_enabled: bool = True
    default_analysts: List[str] = Field(default_factory=lambda: ["market", "social", "news", "fundamentals", "macro", "smart_money", "volume_price"])


class UserRuntimeConfigUpdateRequest(BaseModel):
    llm_provider: Optional[str] = None
    deep_think_llm: Optional[str] = None
    quick_think_llm: Optional[str] = None
    backend_url: Optional[str] = None
    max_debate_rounds: Optional[int] = None
    max_risk_discuss_rounds: Optional[int] = None
    email_report_enabled: Optional[bool] = None
    wecom_report_enabled: Optional[bool] = None
    api_key: Optional[str] = None
    wecom_webhook_url: Optional[str] = None
    clear_api_key: bool = False
    clear_wecom_webhook: bool = False
    warmup: bool = True
    force_warmup: bool = False
    default_analysts: Optional[List[str]] = None


class UserRuntimeWarmupRequest(UserRuntimeConfigUpdateRequest):
    prompt: str = "你好"


class RuntimeWarmupResult(BaseModel):
    model: str
    targets: List[str] = Field(default_factory=list)
    content: Optional[str] = None
    error: Optional[str] = None


class UserRuntimeWarmupResponse(BaseModel):
    prompt: str
    results: List[RuntimeWarmupResult]


class WecomWebhookWarmupRequest(BaseModel):
    wecom_webhook_url: Optional[str] = None
    content: Optional[str] = None


class WecomWebhookWarmupResponse(BaseModel):
    sent: bool = True
    message: str
    webhook_display: Optional[str] = None


class PortfolioPositionItem(BaseModel):
    symbol: str = Field(..., description="股票代码，如 600519.SH 或 600519")
    name: Optional[str] = Field(None, description="股票名称")
    current_position: Optional[float] = Field(None, description="持仓数量")
    available_position: Optional[float] = Field(None, description="可用数量")
    average_cost: Optional[float] = Field(None, description="成本价")
    market_value: Optional[float] = Field(None, description="市值")
    current_position_pct: Optional[float] = Field(None, description="仓位占比 %")


class PortfolioImportSyncRequest(BaseModel):
    positions: List[PortfolioPositionItem] = Field(..., description="持仓列表")
    source: str = Field("manual", description="持仓来源标识")
    auto_apply_scheduled: bool = Field(True, description="是否自动将持仓股票加入定时任务")


class UserTokenResponse(BaseModel):
    id: str
    name: str
    token: str
    token_hint: Optional[str] = None
    last_used_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "last_used_at", when_used="json")
    def serialize_token_datetimes(self, value: Optional[datetime]) -> Optional[str]:
        return _serialize_datetime_utc(value)


class UserTokenListItem(BaseModel):
    """Token info for list endpoint — never exposes the full token."""
    id: str
    name: str
    token_hint: Optional[str] = None
    last_used_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "last_used_at", when_used="json")
    def serialize_token_datetimes(self, value: Optional[datetime]) -> Optional[str]:
        return _serialize_datetime_utc(value)


class UserTokenCreateRequest(BaseModel):
    name: str


class StrategyDecisionResponse(BaseModel):
    symbol: str
    name: str = ""
    market_state: str = ""
    phase: str = ""
    phase_reasoning: str = ""
    effort_result: str = ""
    checklist_score: str = ""
    ice_line: float | None = None
    paths: dict = {}
    final_action: str = ""
    confidence: str = ""
    summary: str = ""
