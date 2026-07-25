import logging
import os
import time
from typing import List

from tradingagents.dataflows.config import get_config
from tradingagents.prompts import get_prompt
from tradingagents.agents.utils.agent_states import current_tracker_var
from tradingagents.agents.utils.debate_utils import (
    format_claim_subset_for_prompt,
    format_claims_for_prompt,
)

_logger = logging.getLogger(__name__)

# ── 分析师权重配置 ──
ANALYST_WEIGHTS = {
    "volume_price_analyst": 2.0,   # 量价分析基于定量数据，信号更可靠
    "smart_money_analyst": 2.0,    # 资金分析基于定量数据，信号更可靠
    "social_media_analyst": 0.5,   # 社交舆情本质为新闻重包装，降权
}

DIRECTION_SCORE = {"看多": 2, "偏多": 1, "中性": 0, "偏空": -1, "看空": -2}

AGENT_LABELS = {
    "market_analyst": "市场",
    "news_analyst": "新闻",
    "social_media_analyst": "社交",
    "fundamentals_analyst": "基本面",
    "macro_analyst": "宏观",
    "smart_money_analyst": "资金",
    "volume_price_analyst": "量价",
}

# 置信度等级 → 数值（用于加权计算）
_CONFIDENCE_NUM = {"高": 1.0, "中": 0.6, "低": 0.3}

# ── 各分析师的核心数据 vs 辅助数据 ──
# core: 缺失时严重影响分析质量，必须降级
# supplementary: 缺失时影响有限，不降级或轻微降级
# context: 仅作为参考信息，缺失时不降级
_ANALYST_DATA_IMPORTANCE = {
    "market_analyst": {
        "core": ["K线", "close", "sma", "ema", "rsi", "macd", "boll", "atr", "指标"],
        "supplementary": ["融资融券", "五档盘口", "盘口", "orderbook", "level2"],
        "context": ["位置指标"],
    },
    "news_analyst": {
        "core": ["新闻", "news", "公告"],
        "supplementary": ["全球新闻", "global", "巨潮", "cninfo"],
        "context": ["行业"],
    },
    "social_media_analyst": {
        "core": ["舆情", "新闻", "情绪"],
        "supplementary": ["社交", "雪球", "热度"],
        "context": [],
    },
    "fundamentals_analyst": {
        "core": ["财务", "营收", "利润", "balance", "cashflow", "income", "基本面"],
        "supplementary": ["研报", "research", "股东", "分红", "股息", "restricted", "pledge"],
        "context": ["F10"],
    },
    "macro_analyst": {
        "core": ["板块资金", "board_fund", "概念资金", "concept_fund"],
        "supplementary": ["宏观新闻", "global_news", "行业"],
        "context": [],
    },
    "smart_money_analyst": {
        "core": ["资金流", "fund_flow", "龙虎榜", "lhb"],
        "supplementary": ["机构", "institution", "活跃座位", "active_seats"],
        "context": ["北向", "hsgt"],
    },
    "volume_price_analyst": {
        "core": ["OHLCV", "K线", "close", "open", "high", "low", "volume"],
        "supplementary": ["VPA", "量价"],
        "context": [],
    },
}

# 数据质量关键词 → 罚分（不是直接乘以因子，而是按重要性分级应用）
_DATA_QUALITY_SIGNALS = {
    # (关键词列表, 严重程度: 1=严重, 2=中等, 3=轻微)
    "severe": (["无数据", "数据缺失", "暂无数据", "无法获取", "暂无相关", "调用失败"], 1),
    "moderate": (["数据不足", "样本不足", "数据有限", "信息有限"], 2),
    "mild": (["数据较少", "覆盖不足", "时间较短", "仅获取到"], 3),
}

# 严重程度 × 数据重要性 → 罚分因子
# 行: 重要性(core/supplementary/context), 列: 严重程度(1=严重/2=中等/3=轻微)
# 设计原则：core+severe 降一级，core+moderate 微降，supplementary/context 基本不降
_PENALTY_MATRIX = {
    "core":           {1: 0.5, 2: 0.6, 3: 0.9},    # 严重缺失→降一级，中等→明确降级
    "supplementary":  {1: 0.8, 2: 0.9, 3: 1.0},    # 严重→微降，中等→几乎不影响
    "context":        {1: 0.9, 2: 1.0, 3: 1.0},    # 基本不影响
}


def _find_quality_issues(text: str) -> list[tuple[str, int]]:
    """从报告文本中提取数据质量问题，返回 (数据名称上下文, 严重程度)。

    策略：按行扫描，找到包含质量关键词的行，提取该行作为上下文。
    这样能精确关联"哪个数据"出了问题。
    """
    issues = []
    lines = text.split('\n')
    for line in lines:
        line_lower = line.lower()
        for _label, (keywords, severity) in _DATA_QUALITY_SIGNALS.items():
            for kw in keywords:
                if kw in line_lower:
                    issues.append((line.strip(), severity))
                    break  # 每行只匹配一次最严重的
            else:
                continue
            break  # 已匹配到，跳过更低级别的
    return issues


def _classify_data_importance(agent: str, keyword_context: str) -> str:
    """判断某个数据关键词属于该分析师的哪类数据。

    优先匹配更长的关键词（如"全球新闻"优先于"新闻"），避免子串误匹配。
    """
    importance = _ANALYST_DATA_IMPORTANCE.get(agent, {})
    ctx_lower = keyword_context.lower()

    # 收集所有匹配项，按关键词长度降序排列（长的优先）
    matches = []
    for level in ("core", "supplementary", "context"):
        for data_kw in importance.get(level, []):
            if data_kw.lower() in ctx_lower:
                matches.append((len(data_kw), level))
    if matches:
        matches.sort(reverse=True)
        return matches[0][1]

    # 未匹配到具体数据类型，默认当作 supplementary（保守处理）
    return "supplementary"


def _assess_confidence_from_report(
    report_text: str,
    original_confidence: str,
    agent_type: str = "",
) -> str:
    """基于报告内容和分析师类型修正置信度等级。

    逻辑：
    1. 扫描报告中的数据质量关键词
    2. 对每个关键词，判断它属于该分析师的 core/supplementary/context 数据
    3. 根据 严重程度 × 数据重要性 矩阵计算罚分
    4. 取最严格的罚分，应用到原始置信度

    Args:
        report_text: 分析师报告全文。
        original_confidence: 分析师自报置信度（高/中/低）。
        agent_type: 分析师类型（如 "market_analyst"），用于判断数据重要性。
    """
    if not report_text:
        return "低"

    issues = _find_quality_issues(report_text)
    if not issues:
        return original_confidence  # 无数据质量问题，保持原值

    # 对每个问题，计算罚分
    worst_penalty = 1.0
    for kw, severity in issues:
        importance = _classify_data_importance(agent_type, kw)
        penalty = _PENALTY_MATRIX.get(importance, {}).get(severity, 1.0)
        worst_penalty = min(worst_penalty, penalty)

    # 原始置信度 → 数值 → 应用罚分 → 等级
    base = _CONFIDENCE_NUM.get(original_confidence, 0.6)
    adjusted = base * worst_penalty

    if adjusted >= 0.7:
        return "高"
    elif adjusted >= 0.4:
        return "中"
    return "低"


def _aggregate_analyst_verdicts(
    analyst_traces: List[dict],
    report_texts: dict[str, str] | None = None,
) -> str:
    """构建分析师裁决的结构化聚合摘要，注入研究经理提示词。

    Args:
        analyst_traces: 各分析师的裁决追踪数据。
        report_texts: 可选，agent_key → 报告全文映射，用于数据质量感知的置信度修正。
    """
    if not analyst_traces:
        return "无分析师裁决数据。"

    # agent_key → report_key 映射
    _REPORT_MAP = {
        "market_analyst": "market_report",
        "news_analyst": "news_report",
        "social_media_analyst": "sentiment_report",
        "fundamentals_analyst": "fundamentals_report",
        "macro_analyst": "macro_report",
        "smart_money_analyst": "smart_money_report",
        "volume_price_analyst": "volume_price_report",
    }

    dir_count = {}
    weighted_sum = 0.0
    total_weight = 0.0
    details = []
    downgraded = []

    for trace in analyst_traces:
        agent = trace.get("agent", "unknown")
        verdict = trace.get("verdict", "中性")
        confidence = trace.get("confidence", "中")

        # ── 数据质量感知的置信度修正 ──
        original_conf = confidence
        if report_texts:
            report_key = _REPORT_MAP.get(agent)
            report_text = report_texts.get(report_key, "") if report_key else ""
            confidence = _assess_confidence_from_report(report_text, confidence, agent_type=agent)
            if confidence != original_conf:
                downgraded.append(
                    f"{AGENT_LABELS.get(agent, agent)}：{original_conf}→{confidence}"
                )

        dir_count[verdict] = dir_count.get(verdict, 0) + 1

        # 置信度影响权重：低信心分析师权重再打折
        conf_factor = _CONFIDENCE_NUM.get(confidence, 0.6)
        score = DIRECTION_SCORE.get(verdict, 0)
        weight = ANALYST_WEIGHTS.get(agent, 1.0) * conf_factor
        weighted_sum += score * weight
        total_weight += weight

        label = AGENT_LABELS.get(agent, agent)
        details.append(f"{label}({verdict}/{confidence})")

    # 方向分布统计
    bullish = dir_count.get("看多", 0) + dir_count.get("偏多", 0)
    bearish = dir_count.get("看空", 0) + dir_count.get("偏空", 0)
    neutral = dir_count.get("中性", 0)

    # 未加权共识评分：归一化到 [-1, +1]
    raw_sum = sum(DIRECTION_SCORE.get(t.get("verdict", "中性"), 0) for t in analyst_traces)
    raw_score = raw_sum / max(len(analyst_traces), 1) / 2.0

    # 加权共识评分
    weighted_score = weighted_sum / max(total_weight, 1.0) / 2.0

    # 共识强度
    majority = max(bullish, bearish, neutral)
    if majority >= 4:
        strength = "高"
    elif majority >= 3:
        strength = "中"
    else:
        strength = "低"

    # 多数方向
    if bullish > bearish:
        majority_dir = "偏多"
    elif bearish > bullish:
        majority_dir = "偏空"
    else:
        majority_dir = "中性"

    lines = [
        f"分析师方向分布：{bullish}人偏多/看多，{bearish}人偏空/看空，{neutral}人中性",
        f"多数方向：{majority_dir} | 共识强度：{strength}（{majority}/7一致）",
        f"未加权共识评分：{raw_score:+.2f} | 加权共识评分（量价/资金×2，社交×0.5，置信度修正后）：{weighted_score:+.2f}",
        f"各分析师裁决：{'；'.join(details)}",
    ]

    if downgraded:
        lines.append(f"⚠ 置信度降级（数据质量修正）：{'；'.join(downgraded)}")

    return "\n".join(lines)


def create_research_manager(llm, memory, data_collector=None):
    async def research_manager_node(state) -> dict:
        history = state["investment_debate_state"].get("history", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        smart_money_report = state.get("smart_money_report", "")
        volume_price_report = state.get("volume_price_report", "")

        # ── 概念共振数据与一致性警告 ──
        ticker = state["company_of_interest"]
        trade_date = state["trade_date"]
        concept_resonance_text = ""
        consistency_warnings_text = ""
        if data_collector:
            pool = data_collector.get(ticker, trade_date)
            if pool:
                concept_resonance_text = pool.get("concept_resonance_text", "") or ""
                consistency_warnings_text = pool.get("consistency_warnings_text", "") or ""

        investment_debate_state = state["investment_debate_state"]
        claims = investment_debate_state.get("claims", [])
        unresolved_claim_ids = investment_debate_state.get("unresolved_claim_ids", [])
        round_summary = investment_debate_state.get("round_summary", "")

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        claims_text = format_claims_for_prompt(claims)
        unresolved_claims_text = format_claim_subset_for_prompt(claims, unresolved_claim_ids)
        round_summary_text = round_summary or "暂无轮次摘要。"

        # ── 结构化裁决聚合（仅增强模式）──
        analyst_traces = state.get("analyst_traces", [])
        if os.getenv("TA_ENHANCED", "1") not in ("0", "false", "no"):
            report_texts = {
                "market_report": market_research_report,
                "news_report": news_report,
                "sentiment_report": sentiment_report,
                "fundamentals_report": fundamentals_report,
                "smart_money_report": smart_money_report,
                "volume_price_report": volume_price_report,
                "macro_report": state.get("macro_report", ""),
            }
            analyst_consensus = _aggregate_analyst_verdicts(analyst_traces, report_texts)
        else:
            analyst_consensus = ""

        prompt = get_prompt("research_manager_prompt", config=get_config()).format(
            past_memory_str=past_memory_str,
            history=history,
            smart_money_report=smart_money_report,
            volume_price_report=volume_price_report,
            sentiment_report=sentiment_report,
            claims_text=claims_text,
            unresolved_claims_text=unresolved_claims_text,
            round_summary=round_summary_text,
            analyst_consensus=analyst_consensus,
            concept_resonance_text=concept_resonance_text or "概念共振数据未计算。",
            consistency_warnings=consistency_warnings_text or "",
        )

        _logger.info(
            "[research_manager] prompt size: total=%d chars | "
            "history=%d, smart_money=%d, volume_price=%d, sentiment=%d, "
            "memory=%d, claims=%d, unresolved=%d, round_summary=%d",
            len(prompt),
            len(history or ""),
            len(smart_money_report or ""),
            len(volume_price_report or ""),
            len(sentiment_report or ""),
            len(past_memory_str or ""),
            len(claims_text or ""),
            len(unresolved_claims_text or ""),
            len(round_summary_text or ""),
        )

        # ── 实现 Token 级流式输出 ──────────────────
        tracker = current_tracker_var.get()
        full_content = ""
        reasoning_buf: list[str] = []
        first_token_at: float | None = None
        first_reasoning_at: float | None = None
        start = time.monotonic()

        async for chunk in llm.astream(prompt):
            now = time.monotonic()
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            full_content += content

            # reasoning_content (thinking 模型) 仅做 server 端日志，不发前端
            reasoning = None
            extra = getattr(chunk, "additional_kwargs", None) or {}
            if isinstance(extra, dict):
                reasoning = extra.get("reasoning_content")
            if reasoning:
                if first_reasoning_at is None:
                    first_reasoning_at = now
                reasoning_buf.append(reasoning)

            if content:
                if first_token_at is None:
                    first_token_at = now
                if tracker:
                    tracker._emit_token("Research Manager", "investment_plan", content)
                    tracker.emit_debate_token(
                        debate="research", agent="Research Manager",
                        round_num=-1, token=content,
                    )

        total_elapsed = time.monotonic() - start
        reasoning_text = "".join(reasoning_buf)
        _logger.info(
            "[research_manager] streaming done: total_elapsed=%.2fs | "
            "ttft_reasoning=%.2fs ttft_content=%.2fs | "
            "reasoning_chars=%d content_chars=%d",
            total_elapsed,
            (first_reasoning_at - start) if first_reasoning_at else -1,
            (first_token_at - start) if first_token_at else -1,
            len(reasoning_text),
            len(full_content),
        )
        if reasoning_text:
            _logger.debug(
                "[research_manager] reasoning preview (%d chars): %s",
                len(reasoning_text),
                reasoning_text[:1500],
            )

        # ── 推送辩论裁决（标记流式结束）──
        if tracker:
            tracker.emit_debate_message(
                debate="research", agent="Research Manager",
                round_num=-1, content=full_content, is_verdict=True,
            )

        new_investment_debate_state = {
            "judge_decision": full_content,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_speaker": investment_debate_state.get("current_speaker", ""),
            "current_response": full_content,
            "count": investment_debate_state["count"],
            "claims": claims,
            "focus_claim_ids": investment_debate_state.get("focus_claim_ids", []),
            "open_claim_ids": investment_debate_state.get("open_claim_ids", []),
            "resolved_claim_ids": investment_debate_state.get("resolved_claim_ids", []),
            "unresolved_claim_ids": unresolved_claim_ids,
            "round_summary": round_summary,
            "round_goal": investment_debate_state.get("round_goal", ""),
            "claim_counter": investment_debate_state.get("claim_counter", 0),
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": full_content,
        }

    return research_manager_node
