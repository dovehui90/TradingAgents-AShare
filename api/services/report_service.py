"""Report service for database operations."""

import json
import json_repair
import logging
import re

logger = logging.getLogger(__name__)
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Iterable, Literal
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, load_only

from api.database import ReportDB, SignalBacktestDB


REPORT_SUMMARY_COLUMNS = (
    ReportDB.id,
    ReportDB.user_id,
    ReportDB.symbol,
    ReportDB.trade_date,
    ReportDB.status,
    ReportDB.error,
    ReportDB.decision,
    ReportDB.direction,
    ReportDB.confidence,
    ReportDB.target_price,
    ReportDB.stop_loss_price,
    ReportDB.risk_items,
    ReportDB.key_metrics,
    ReportDB.analyst_traces,
    ReportDB.created_at,
    ReportDB.updated_at,
)

ACTIVE_REPORT_STATUSES = ("pending", "running")
STALE_REPORT_ERROR_MESSAGE = "分析任务已中断，请重新发起分析"


# ─── Structured extraction schemas ───────────────────────────────────────────

from pydantic import field_validator


class RiskItemSchema(BaseModel):
    name: str = Field(..., description="风险名称，15字以内")
    level: str = Field("medium", description="风险等级")
    description: str = Field("", description="一句话说明，30字以内")

    @field_validator("level", mode="before")
    @classmethod
    def _coerce_level(cls, v):
        if isinstance(v, str) and v.lower() in ("high", "medium", "low"):
            return v.lower()
        return "medium"


class KeyMetricSchema(BaseModel):
    name: str = Field(..., description="指标名称，如 PE、ROE、营收增速")
    value: str = Field(..., description="指标值，包含单位，如 28.5x、15.2%")
    status: str = Field("neutral", description="优劣判断")

    @field_validator("value", mode="before")
    @classmethod
    def _coerce_value(cls, v):
        # LLM 可能返回数字而非字符串
        return str(v) if not isinstance(v, str) else v

    @field_validator("status", mode="before")
    @classmethod
    def _coerce_status(cls, v):
        if isinstance(v, str) and v.lower() in ("good", "neutral", "bad"):
            return v.lower()
        return "neutral"


class StructuredReport(BaseModel):
    decision: str = Field("HOLD", description="交易决策关键词：BUY/SELL/HOLD/增持/减持/持有")
    confidence: Optional[int] = Field(None, description="整体置信度 0-100")
    target_price: Optional[float] = Field(None, description="目标价（数字，无单位）")
    stop_loss_price: Optional[float] = Field(None, description="止损价（数字，无单位）")
    risks: List[RiskItemSchema] = Field(default_factory=list, description="主要风险，最多5条")
    key_metrics: List[KeyMetricSchema] = Field(default_factory=list, description="关键指标，最多6条")

    @field_validator("target_price", "stop_loss_price", mode="before")
    @classmethod
    def _coerce_price(cls, v):
        # LLM 可能返回数组 [34.0, 32.5] 而非单个数字，取第一个
        if isinstance(v, list):
            return v[0] if v else None
        return v


def extract_structured_data(
    final_trade_decision: str,
    fundamentals_report: str = "",
    current_price: Optional[float] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[StructuredReport]:
    """Use LLM structured output to extract key data from report text."""
    if not final_trade_decision:
        return None
    if config is None:
        from tradingagents.default_config import DEFAULT_CONFIG
        config = DEFAULT_CONFIG

    try:
        from langchain_core.messages import HumanMessage
        from tradingagents.llm_clients import create_llm_client

        client = create_llm_client(
            provider=config.get("llm_provider", "openai"),
            model=config.get("quick_think_llm", "deepseek-v4-flash"),
            base_url=config.get("backend_url"),
            api_key=config.get("api_key"),
        )
        llm = client.get_llm()

        price_hint = ""
        if current_price and current_price > 0:
            price_hint = (
                f"\n**重要：当前股价为 {current_price:.2f} 元。**"
                f"若方向偏多，target_price 应高于当前价；若方向偏空，target_price 应低于当前价。"
                f"若报告中目标价与当前价关系矛盾（如看空但目标>当前价），target_price 设为 null。"
            )

        prompt = (
            "请从以下投资分析报告中提取结构化信息，并以 JSON 格式返回。\n\n"
            f"【最终交易决策】\n{final_trade_decision[:3000]}\n\n"
            f"【基本面报告摘要】\n{fundamentals_report[:1000]}\n"
            f"{price_hint}\n"
            "提取要求（请确保输出为有效的 JSON 对象，不要包裹在 markdown 代码块中）：\n"
            "1. decision：决策方向关键词（BUY/SELL/HOLD 或 增持/减持/持有）\n"
            "2. confidence：整体置信度（0-100整数），若文中未明确给出则根据语气判断\n"
            "3. target_price / stop_loss_price：纯数字。若方向偏多，提取上涨目标（目标价/目标位/关键价位/阻力位/突破做多等）；若方向偏空，提取下跌目标（下行目标/看空目标/目标位等，区别于止损位）。若文中确实未提及任何目标价格则为 null\n"
            "   ★ 重要：只提取【主方案/核心方案】的价格，忽略\"追加建仓\"、\"加仓场景\"、\"第二阶段\"等二级方案的价格。若报告有\"核心目标位\"、\"第一目标位\"，优先提取该值。\n"
            "4. risks：最多5条主要风险，每条包含名称（15字内）、等级（high/medium/low）、一句话说明\n"
            "5. key_metrics：最多6条关键财务/估值指标，每条包含名称、值（含单位）、优劣（good/neutral/bad）"
        )

        response = llm.invoke([HumanMessage(content=prompt)])
        raw = response.content if hasattr(response, "content") else str(response)
        parsed = json_repair.loads(raw)
        result = StructuredReport(**parsed)

        # 统一 decision 为 BUY/SELL/HOLD（与 signal_processing 对齐）
        _decision_normalize = {
            "买入": "BUY", "增持": "BUY", "做多": "BUY", "看多": "BUY",
            "偏多": "BUY", "看涨": "BUY", "建仓": "BUY", "加仓": "BUY",
            "卖出": "SELL", "减持": "SELL", "做空": "SELL", "看空": "SELL",
            "偏空": "SELL", "看跌": "SELL", "减仓": "SELL", "清仓": "SELL",
            "持有": "HOLD", "观望": "HOLD", "中性": "HOLD", "等待": "HOLD",
        }
        if result.decision:
            upper = result.decision.strip().upper()
            if upper in ("BUY", "SELL", "HOLD"):
                pass  # 已标准化
            elif result.decision.strip() in _decision_normalize:
                result.decision = _decision_normalize[result.decision.strip()]
            else:
                logger.warning(f"无法标准化 decision='{result.decision}'，默认 HOLD")
                result.decision = "HOLD"

        if result.confidence is not None and not (0 <= result.confidence <= 100):
            result.confidence = None
        # 后置校验：目标价与决策方向/当前价矛盾时丢弃
        if result.target_price is not None and current_price and current_price > 0:
            decision_upper = str(result.decision or "").upper()
            is_bearish = any(kw in decision_upper for kw in ("SELL", "减持", "看空", "看跌"))
            is_bullish = any(kw in decision_upper for kw in ("BUY", "增持", "看多", "看涨"))
            if is_bearish and result.target_price > current_price:
                logger.info(f"Target price {result.target_price} > current {current_price} for bearish decision, discarding")
                result.target_price = None
            if is_bullish and result.target_price < current_price:
                logger.info(f"Target price {result.target_price} < current {current_price} for bullish decision, discarding")
                result.target_price = None
        return result
    except Exception as e:
        logger.warning(f"LLM structured extraction failed: {e}")
        if 'raw' in locals():
            logger.warning(f"Raw LLM output:\n{raw}")
        return None


# ─── Fallback regex extraction (used when LLM extraction unavailable) ─────────

def _extract_confidence_regex(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    for pattern in (r'置信度[:：]\s*(\d+)%', r'confidence[:：]\s*(\d+)%'):
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            v = int(m.group(1))
            return v if 0 <= v <= 100 else None
    return None


def _extract_price_regex(text: Optional[str], price_type: str = "target") -> Optional[float]:
    if not text:
        return None
    # 预处理：去除 markdown 加粗标记，避免 **目标价** 干扰匹配
    clean = re.sub(r'\*{1,2}', '', text)
    if price_type == "target":
        patterns = [
            # ★ 主方案核心目标（最高优先级：避免从"追加建仓"等二级场景误提取）
            r'核心目标[位价][^：:\n]{0,20}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            r'第一目标[位价][^：:\n]{0,20}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            r'主[目要]标[位价][^：:\n]{0,20}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            # 看空/看跌方向目标（优先：更精确的方向性目标）
            r'下行目标[^：:\n]{0,15}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            r'下跌目标[^：:\n]{0,15}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            r'downside\s+target[^：:\n]{0,15}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            # 看多方向目标
            r'上方目标[^：:\n]{0,20}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            r'upside\s+target[^：:\n]{0,15}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            # 通用目标价（排除减仓目标价——那是反弹逃逸价，不是预测目标）
            # .*? 允许表格格式中分隔符和价格之间有较长描述文字（如 |目标价| ...设定为13.00元|）
            r'(?<!减仓)目标[^：:\|\n]{0,30}[：:\|].*?(\d+\.?\d+)\s*元',
            r'(?<!减仓)target[^：:\|\n]{0,30}[：:\|].*?(\d+\.?\d+)\s*元',
            # 英文变体
            r'price\s+target[^：:\n]{0,15}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            r'price\s+objective[^：:\n]{0,15}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            r'support\s+level[^：:\n]{0,10}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            r'resistance\s+level[^：:\n]{0,10}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            # 关键价位/阻力位/压力位 可作为目标价参考
            r'关键[^：:\n]{0,30}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            r'阻力位[^：:\n]{0,20}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            r'压力位[^：:\n]{0,20}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            # 突破做多 + 紧邻价格（限10字符内，避免跨句误匹配止损价）
            r'突破做多[^，。,.\n]{0,10}?(\d+\.?\d+)\s*元',
            # 入场区间取上限作为目标参考
            r'入场区间[：:\|]\s*[¥$]?\s*(\d+\.?\d+)\s*[–\-—至~]\s*\d+\.?\d+',
            # 看空/看跌方向
            r'下[行看跌][^：:\n]{0,30}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            r'看[空跌][^：:\n]{0,30}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',

            # ===== 新增：更宽松的匹配模式 =====
            # "建议目标价位"
            r'建议目标[价位格][^：:\n]{0,30}[：:\|]\s*[¥$]?\s*(\d+\.?\d+)',
            # "预计涨至XX元"
            r'预计[涨上行跌下降][^至到]{0,10}[至到]\s*[¥$]?\s*(\d+\.?\d+)\s*元?',
            # "看涨目标XX元" - 修正：确保完整匹配价格
            r'看[涨跌]目标[^：:\n]{0,20}[：:\|]?\s*[¥$]?\s*(\d+\.?\d*)\s*元',
            # "涨至XX元附近"
            r'[涨跌升降][至到]\s*[¥$]?\s*(\d+\.?\d*)\s*元?\s*附近',
            # "目标区间XX-YY元"（取上限）
            r'目标区间[^：:\n]{0,20}[：:\|]?\s*\d+\.?\d*\s*[-–—~至]\s*[¥$]?\s*(\d+\.?\d*)\s*元?',
            # "建议入场价格XX-YY元"（取上限）
            r'建议入场[价格位][^：:\n]{0,20}[：:\|]?\s*\d+\.?\d*\s*[-–—~至]\s*[¥$]?\s*(\d+\.?\d*)\s*元?',
            # "目标价格"
            r'目标价[格位]?[^：:\n]{0,30}[：:\|]?\s*[¥$]?\s*(\d+\.?\d*)\s*元',
            # "盈利目标"
            r'盈利目标[^：:\n]{0,20}[：:\|]?\s*[¥$]?\s*(\d+\.?\d*)\s*元',
        ]
    else:
        patterns = [
            # ★ 主方案止损（最高优先级：避免从"追加建仓"等二级场景误提取）
            r'核心止损[^：:\n]{0,20}[：:\|]\s*[¥$]?\s*(\d+\.?\d*)',
            r'止损位[^：:\n]{0,20}[：:\|]\s*[¥$]?\s*(\d+\.?\d*)',
            r'止损价[^：:\n]{0,20}[：:\|]\s*[¥$]?\s*(\d+\.?\d*)',
            # 通用止损
            r'止损[^：:\n]{0,30}[：:\|]\s*[¥$]?\s*(\d+\.?\d*)',
            r'stop[-\s_]?loss[^：:\n]{0,30}[：:\|]\s*[¥$]?\s*(\d+\.?\d*)',
            r'硬止损[^：:\n]{0,30}[：:\|]\s*[¥$]?\s*(\d+\.?\d*)',

            # ===== 新增：更宽松的匹配模式 =====
            # "建议止损价位"
            r'建议止损[价位格][^：:\n]{0,30}[：:\|]\s*[¥$]?\s*(\d+\.?\d*)',
            # "止损设在XX元"
            r'止损设[在于]\s*[¥$]?\s*(\d+\.?\d*)\s*元?',
            # "跌破XX元止损"
            r'跌破\s*[¥$]?\s*(\d+\.?\d*)\s*元?\s*止损',
            # "XX元以下止损"
            r'[¥$]?\s*(\d+\.?\d*)\s*元?\s*以下止损',
            # "严格止损XX元"
            r'严格止损[^：:\n]{0,20}[：:\|]?\s*[¥$]?\s*(\d+\.?\d*)\s*元',
        ]

    for p in patterns:
        m = re.search(p, clean, re.IGNORECASE)
        if m:
            try:
                price = float(m.group(1))
                # 基本合理性检查：价格应在0.1-10000之间
                if 0.1 <= price <= 10000:
                    return price
            except (ValueError, IndexError):
                continue

    return None


def _extract_verdict(text: Optional[str]) -> Optional[Dict[str, str]]:
    if not text:
        return None
    match = re.search(r"<!--\s*VERDICT:\s*(\{.*?\})\s*-->", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    try:
        # Clean potential newlines or invisible characters common in LLM outputs
        raw_json = match.group(1).strip().replace('\n', ' ').replace('\r', ' ')
        payload = json.loads(raw_json)
    except Exception:
        return None
    direction = str(payload.get("direction") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    if not direction:
        return None
    return {"direction": direction, "reason": reason}


def resolve_report_fields(
    result_data: Optional[Dict[str, Any]] = None,
    confidence_override: Optional[int] = None,
    target_price_override: Optional[float] = None,
    stop_loss_override: Optional[float] = None,
) -> Dict[str, Any]:
    """Resolve the final structured fields once for both SSE payloads and DB writes."""
    market_report = sentiment_report = news_report = None
    fundamentals_report = macro_report = smart_money_report = volume_price_report = game_theory_report = None
    investment_plan = trader_investment_plan = None
    final_trade_decision = None

    if result_data:
        market_report = result_data.get("market_report")
        sentiment_report = result_data.get("sentiment_report")
        news_report = result_data.get("news_report")
        fundamentals_report = result_data.get("fundamentals_report")
        macro_report = result_data.get("macro_report")
        smart_money_report = result_data.get("smart_money_report")
        volume_price_report = result_data.get("volume_price_report")
        game_theory_report = result_data.get("game_theory_report")
        investment_plan = result_data.get("investment_plan")
        trader_investment_plan = result_data.get("trader_investment_plan")
        final_trade_decision = result_data.get("final_trade_decision")

    verdict = _extract_verdict(final_trade_decision)
    direction = verdict["direction"] if verdict else None

    confidence = confidence_override if confidence_override is not None else _extract_confidence_regex(final_trade_decision)

    # ── 价格幻觉检测：RM引用的当前价 vs market_report实际当前价 ──
    _market_current_price = None
    if market_report:
        _mcp = re.search(r'(?:当前价|最新价|现价|收盘价|close)[^\d]*(\d+\.?\d+)', str(market_report), re.IGNORECASE)
        if _mcp:
            _market_current_price = float(_mcp.group(1))

    _decision_ref_price = None
    if final_trade_decision:
        _drp = re.search(r'当前价[^\d]{0,10}(\d+\.?\d+)', str(final_trade_decision))
        if _drp:
            _decision_ref_price = float(_drp.group(1))

    _price_hallucinated = False
    if _market_current_price and _decision_ref_price:
        _deviation = abs(_decision_ref_price - _market_current_price) / _market_current_price
        if _deviation > 0.05:  # 偏差超过5%
            _price_hallucinated = True
            logger.warning(
                f"⚠️ 价格幻觉检测: RM引用当前价 {_decision_ref_price}，"
                f"market_report实际价 {_market_current_price}，偏差 {_deviation:.1%}。"
                f"将使用 market_report 价格校验目标价/止损价。"
            )

    target_price = target_price_override if target_price_override is not None else _extract_price_regex(final_trade_decision, "target")
    if target_price is None:
        target_price = _extract_price_regex(trader_investment_plan, "target")
        if target_price:
            logger.info(f"✅ 从trader_investment_plan提取到目标价: {target_price}")
        else:
            logger.warning(f"⚠️ 未能从任何来源提取目标价")
            if trader_investment_plan:
                logger.debug(f"trader_investment_plan前300字符: {trader_investment_plan[:300]}")
    else:
        logger.info(f"✅ 从final_trade_decision提取到目标价: {target_price}")

    stop_loss_price = stop_loss_override if stop_loss_override is not None else _extract_price_regex(final_trade_decision, "stop_loss")
    if stop_loss_price is None:
        stop_loss_price = _extract_price_regex(trader_investment_plan, "stop_loss")
        if stop_loss_price:
            logger.info(f"✅ 从trader_investment_plan提取到止损价: {stop_loss_price}")
        else:
            logger.warning(f"⚠️ 未能从任何来源提取止损价")
    else:
        logger.info(f"✅ 从final_trade_decision提取到止损价: {stop_loss_price}")

    # 后置校验：从报告中提取当前价，验证目标价与决策方向是否一致
    if target_price is not None and market_report:
        current_m = re.search(r'(?:当前价|最新价|现价|收盘价|close)[^\d]*(\d+\.?\d+)', str(market_report), re.IGNORECASE)
        if current_m:
            current = float(current_m.group(1))
            is_bearish = direction and direction.upper() in ("SELL", "BEARISH", "看空", "看跌", "减持")
            is_bullish = direction and direction.upper() in ("BUY", "BULLISH", "看多", "看涨", "增持")
            if is_bearish and target_price > current:
                logger.info(f"Target {target_price} > current {current} for bearish {direction}, discarding LLM extraction")
                target_price = None
            if is_bullish and target_price < current:
                logger.info(f"Target {target_price} < current {current} for bullish {direction}, discarding LLM extraction")
                target_price = None
    # LLM提取被丢弃时，回退到regex重提取
    if target_price is None and target_price_override is not None:
        target_price = _extract_price_regex(final_trade_decision, "target")
        if target_price is None:
            target_price = _extract_price_regex(trader_investment_plan, "target")

    stop_loss_price = stop_loss_override if stop_loss_override is not None else _extract_price_regex(final_trade_decision, "stop_loss")
    if stop_loss_price is None:
        stop_loss_price = _extract_price_regex(trader_investment_plan, "stop_loss")

    # 价格幻觉时：清空从 final_trade_decision 提取的目标价/止损价（基于错误当前价）
    # 尝试从 trader_investment_plan 重新提取（可能包含原始正确参数）
    if _price_hallucinated:
        logger.warning(f"价格幻觉: 丢弃目标价={target_price}、止损价={stop_loss_price}，尝试从 trader_investment_plan 重提取")
        target_price = _extract_price_regex(trader_investment_plan, "target")
        stop_loss_price = _extract_price_regex(trader_investment_plan, "stop_loss")
        if target_price or stop_loss_price:
            logger.info(f"从 trader_investment_plan 重提取: 目标价={target_price}、止损价={stop_loss_price}")
        else:
            logger.warning("trader_investment_plan 中也未找到价格，目标价/止损价设为 null")

    return {
        "market_report": market_report,
        "sentiment_report": sentiment_report,
        "news_report": news_report,
        "fundamentals_report": fundamentals_report,
        "macro_report": macro_report,
        "smart_money_report": smart_money_report,
        "volume_price_report": volume_price_report,
        "game_theory_report": game_theory_report,
        "investment_plan": investment_plan,
        "trader_investment_plan": trader_investment_plan,
        "final_trade_decision": final_trade_decision,
        "direction": direction,
        "confidence": confidence,
        "target_price": target_price,
        "stop_loss_price": stop_loss_price,
    }


# ─── CRUD ────────────────────────────────────────────────────────────────────

def init_report(
    db: Session,
    report_id: str,
    symbol: str,
    trade_date: str,
    user_id: Optional[str] = None,
) -> ReportDB:
    """Create a pending report record when a job is submitted."""
    now = datetime.now(timezone.utc)
    db_report = ReportDB(
        id=report_id,
        user_id=user_id,
        symbol=symbol,
        trade_date=trade_date,
        status="pending",
        created_at=now,
        updated_at=now,
    )
    db.add(db_report)
    db.commit()
    db.refresh(db_report)
    return db_report


def update_report_partial(
    db: Session,
    report_id: str,
    status: Optional[str] = None,
    **fields: Any
) -> Optional[ReportDB]:
    """Update specific fields of an existing report (e.g., partial analyst reports)."""
    db_report = db.query(ReportDB).filter(ReportDB.id == report_id).first()
    if not db_report:
        return None
    
    if status:
        db_report.status = status
    
    for key, value in fields.items():
        if hasattr(db_report, key):
            setattr(db_report, key, value)
    
    db_report.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(db_report)
    return db_report


def finalize_orphan_report(
    db: Session,
    report: ReportDB,
    *,
    error_message: str = STALE_REPORT_ERROR_MESSAGE,
) -> ReportDB:
    """Mark an orphaned pending/running report as failed."""
    if str(report.status or "") not in ACTIVE_REPORT_STATUSES:
        return report

    report.status = "failed"
    report.error = error_message
    report.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(report)
    return report


def recover_stale_active_reports(
    db: Session,
    *,
    active_job_ids: Optional[Iterable[str]] = None,
    error_message: str = STALE_REPORT_ERROR_MESSAGE,
) -> Dict[str, int]:
    """Recover stale pending/running reports left behind by interrupted jobs."""
    active_job_id_set = {str(job_id) for job_id in (active_job_ids or []) if str(job_id).strip()}
    rows = (
        db.query(ReportDB)
        .filter(ReportDB.status.in_(ACTIVE_REPORT_STATUSES))
        .all()
    )
    if not rows:
        return {"total": 0, "failed": 0}

    failed = 0
    changed = False
    now = datetime.now(timezone.utc)
    for row in rows:
        if str(row.id) in active_job_id_set:
            continue
        row.status = "failed"
        row.error = error_message
        row.updated_at = now
        changed = True
        failed += 1

    if changed:
        db.commit()

    return {
        "total": failed,
        "failed": failed,
    }


def mark_report_failed(
    db: Session,
    report_id: str,
    error_message: str
) -> Optional[ReportDB]:
    """Mark a report as failed with an error message."""
    return update_report_partial(db, report_id, status="failed", error=error_message)


def create_report(
    db: Session,
    symbol: str,
    trade_date: str,
    decision: Optional[str] = None,
    result_data: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    risk_items: Optional[List[dict]] = None,
    key_metrics: Optional[List[dict]] = None,
    analyst_traces: Optional[List[dict]] = None,
    confidence_override: Optional[int] = None,
    target_price_override: Optional[float] = None,
    stop_loss_override: Optional[float] = None,
    report_id: Optional[str] = None,  # If provided, update existing
) -> ReportDB:
    """Create or finalize a report."""
    resolved = resolve_report_fields(
        result_data=result_data,
        confidence_override=confidence_override,
        target_price_override=target_price_override,
        stop_loss_override=stop_loss_override,
    )

    now = datetime.now(timezone.utc)
    
    # Check if we should update an existing record (initialized via init_report)
    db_report = None
    if report_id:
        db_report = db.query(ReportDB).filter(ReportDB.id == report_id).first()

    if db_report:
        # Update existing
        db_report.status = "completed"
        db_report.decision = decision
        db_report.direction = resolved["direction"]
        db_report.confidence = resolved["confidence"]
        db_report.target_price = resolved["target_price"]
        db_report.stop_loss_price = resolved["stop_loss_price"]
        db_report.result_data = result_data
        db_report.risk_items = risk_items
        db_report.key_metrics = key_metrics
        db_report.analyst_traces = analyst_traces
        db_report.market_report = resolved["market_report"]
        db_report.sentiment_report = resolved["sentiment_report"]
        db_report.news_report = resolved["news_report"]
        db_report.fundamentals_report = resolved["fundamentals_report"]
        db_report.macro_report = resolved["macro_report"]
        db_report.smart_money_report = resolved["smart_money_report"]
        db_report.volume_price_report = resolved["volume_price_report"]
        db_report.game_theory_report = resolved["game_theory_report"]
        db_report.investment_plan = resolved["investment_plan"]
        db_report.trader_investment_plan = resolved["trader_investment_plan"]
        db_report.final_trade_decision = resolved["final_trade_decision"]
        db_report.updated_at = now
    else:
        # Create new
        db_report = ReportDB(
            id=report_id or str(uuid4()),
            user_id=user_id,
            symbol=symbol,
            trade_date=trade_date,
            status="completed",
            decision=decision,
            direction=resolved["direction"],
            confidence=resolved["confidence"],
            target_price=resolved["target_price"],
            stop_loss_price=resolved["stop_loss_price"],
            result_data=result_data,
            risk_items=risk_items,
            key_metrics=key_metrics,
            analyst_traces=analyst_traces,
            market_report=resolved["market_report"],
            sentiment_report=resolved["sentiment_report"],
            news_report=resolved["news_report"],
            fundamentals_report=resolved["fundamentals_report"],
            macro_report=resolved["macro_report"],
            smart_money_report=resolved["smart_money_report"],
            volume_price_report=resolved["volume_price_report"],
            game_theory_report=resolved["game_theory_report"],
            investment_plan=resolved["investment_plan"],
            trader_investment_plan=resolved["trader_investment_plan"],
            final_trade_decision=resolved["final_trade_decision"],
            created_at=now,
            updated_at=now,
        )
        db.add(db_report)

    db.commit()
    db.refresh(db_report)
    return db_report


def get_report(db: Session, report_id: str, user_id: Optional[str] = None) -> Optional[ReportDB]:
    query = db.query(ReportDB).filter(ReportDB.id == report_id)
    if user_id:
        query = query.filter(ReportDB.user_id == user_id)
    return query.first()


def get_reports_by_user(
    db: Session,
    user_id: Optional[str] = None,
    symbol: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[ReportDB]:
    query = db.query(ReportDB).options(load_only(*REPORT_SUMMARY_COLUMNS))
    if user_id:
        query = query.filter(ReportDB.user_id == user_id)
    if symbol:
        query = query.filter(ReportDB.symbol == symbol)
    return query.order_by(ReportDB.created_at.desc()).offset(skip).limit(limit).all()


def get_latest_reports_by_symbols(
    db: Session,
    symbols: List[str],
    user_id: Optional[str] = None,
) -> List[ReportDB]:
    normalized_symbols = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
    if not normalized_symbols:
        return []

    query = db.query(ReportDB).options(load_only(*REPORT_SUMMARY_COLUMNS))
    if user_id:
        query = query.filter(ReportDB.user_id == user_id)

    rows = (
        query.filter(ReportDB.symbol.in_(normalized_symbols))
        .order_by(ReportDB.symbol.asc(), ReportDB.created_at.desc())
        .all()
    )

    latest_by_symbol: dict[str, ReportDB] = {}
    for row in rows:
        symbol = str(row.symbol or "").upper()
        if symbol and symbol not in latest_by_symbol:
            latest_by_symbol[symbol] = row

    return [latest_by_symbol[symbol] for symbol in normalized_symbols if symbol in latest_by_symbol]


def count_reports(
    db: Session,
    user_id: Optional[str] = None,
    symbol: Optional[str] = None,
) -> int:
    query = db.query(func.count(ReportDB.id))
    if user_id:
        query = query.filter(ReportDB.user_id == user_id)
    if symbol:
        query = query.filter(ReportDB.symbol == symbol)
    return query.scalar() or 0


def delete_report(db: Session, report_id: str, user_id: Optional[str] = None) -> bool:
    query = db.query(ReportDB).filter(ReportDB.id == report_id)
    if user_id:
        query = query.filter(ReportDB.user_id == user_id)
    report = query.first()
    if report:
        # 级联删除关联的回测记录，避免孤儿数据影响准确率统计
        db.query(SignalBacktestDB).filter(SignalBacktestDB.report_id == report_id).delete()
        db.delete(report)
        db.commit()
        return True
    return False


def batch_delete_reports(db: Session, report_ids: Iterable[str], user_id: Optional[str] = None) -> dict:
    normalized_ids: list[str] = []
    seen: set[str] = set()
    for raw_report_id in report_ids:
        report_id = str(raw_report_id or "").strip()
        if not report_id or report_id in seen:
            continue
        seen.add(report_id)
        normalized_ids.append(report_id)

    if not normalized_ids:
        raise ValueError("请至少选择 1 份报告")

    query = db.query(ReportDB).filter(ReportDB.id.in_(normalized_ids))
    if user_id:
        query = query.filter(ReportDB.user_id == user_id)

    rows = query.all()
    row_by_id = {str(row.id): row for row in rows}
    deleted_ids: list[str] = []
    missing_ids: list[str] = []

    for report_id in normalized_ids:
        row = row_by_id.get(report_id)
        if row is None:
            missing_ids.append(report_id)
            continue
        db.delete(row)
        deleted_ids.append(report_id)

    if deleted_ids:
        # 级联删除关联的回测记录
        db.query(SignalBacktestDB).filter(SignalBacktestDB.report_id.in_(deleted_ids)).delete(synchronize_session='fetch')
        db.commit()

    return {
        "deleted_ids": deleted_ids,
        "missing_ids": missing_ids,
    }
