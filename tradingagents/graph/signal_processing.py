# TradingAgents/graph/signal_processing.py

import json
import logging
import re

from langchain_openai import ChatOpenAI
from tradingagents.dataflows.config import get_config
from tradingagents.prompts import get_prompt

logger = logging.getLogger(__name__)

# 否定语境模式：匹配"不建议买入"/"避免建仓"等表述，防止关键词子串误判
_NEGATION_PATTERN = re.compile(
    r'(?:不(?:建议|推荐|考虑|宜|应|该|能|可|再|会|支持|赞成|同意|适合|妨|必|得|要|允许|主张|鼓励|看|倾向)'
    r'|避免|切勿|切忌|暂不|难以|无法|放弃|远离|警惕|谨慎)'
    r'.{0,30}?'
    r'(?:买入|卖出|建仓|增持|减持|做多|做空|清仓|入场|加仓|补仓|追高|抄底|持股|持仓|参与)+',
)


class SignalProcessor:
    """Processes trading signals to extract actionable decisions."""

    def __init__(self, quick_thinking_llm: ChatOpenAI, confidence_threshold: int = 40):
        """Initialize with an LLM for processing.

        Args:
            quick_thinking_llm: LLM instance for signal extraction fallback.
            confidence_threshold: minimum confidence (0-100) to accept non-HOLD
                signals. Signals below this threshold are forced to HOLD.
        """
        self.quick_thinking_llm = quick_thinking_llm
        self.confidence_threshold = confidence_threshold

    @staticmethod
    def _extract_confidence(text: str) -> int:
        """Extract confidence value from VERDICT JSON block or text.

        Priority: VERDICT block > explicit confidence text > default 50.
        Returns 0-100 int.
        """
        # 1. 优先从 VERDICT 块提取
        m = re.search(r'<!--\s*VERDICT:\s*(\{.*?\})\s*-->', text or "", re.DOTALL)
        if m:
            try:
                d = json.loads(m.group(1))
                raw = d.get("confidence")
                if raw is not None:
                    v = float(raw)
                    return int(v) if v > 1.0 else int(v * 100)
                return 50  # missing field → assume medium confidence
            except Exception:
                pass

        # 2. 从正文提取置信度（如"置信度：70%"、"confidence: 75%"）
        for pattern in (
            r'置信度[：:]\s*(\d+)\s*%',
            r'confidence[：:]\s*(\d+)\s*%',
            r'信心[：:]\s*(\d+)\s*%',
        ):
            cm = re.search(pattern, text or "", re.IGNORECASE)
            if cm:
                v = int(cm.group(1))
                if 0 <= v <= 100:
                    return v

        # 3. 无法提取时返回 0（触发置信度过滤，保守处理）
        return 0

    def process_signal(self, full_signal: str) -> str:
        """Process a trading signal to extract decision, filtering low confidence.

        Returns BUY, SELL, or HOLD. Signals with confidence below threshold
        are forced to HOLD regardless of the stated direction.
        """
        if not full_signal:
            return "HOLD"

        decision = _extract_decision_keyword(full_signal)
        if not decision:
            messages = [
                ("system", get_prompt("signal_extractor_system", config=get_config())),
                ("human", full_signal),
            ]
            response = str(self.quick_thinking_llm.invoke(messages).content).strip().upper()
            decision = response if response in {"BUY", "SELL", "HOLD"} else "HOLD"

        # ── 置信度过滤 ──
        if decision != "HOLD":
            confidence = self._extract_confidence(full_signal)
            if confidence < self.confidence_threshold:
                logger.info(
                    "置信度过滤：信号=%s, 置信度=%d < 阈值=%d, 强制退守HOLD",
                    decision, confidence, self.confidence_threshold,
                )
                return "HOLD"

        return decision


def _extract_decision_keyword(text: str) -> str | None:
    """Rule-based decision extraction to keep UI consistent with final decision text."""
    upper = text.upper()

    def parse_verdict_direction(raw_text: str) -> str | None:
        match = re.search(r"<!--\s*VERDICT:\s*(\{.*?\})\s*-->", raw_text, re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group(1))
        except Exception:
            return None
        direction = str(payload.get("direction", "")).strip().upper()
        direction_map = {
            # 看多
            "看多": "BUY",
            "偏多": "BUY",
            "看涨": "BUY",
            "谨慎看多": "BUY",
            "BULLISH": "BUY",
            "BUY": "BUY",
            # 看空
            "看空": "SELL",
            "偏空": "SELL",
            "看跌": "SELL",
            "BEARISH": "SELL",
            "SELL": "SELL",
            # 中性/持有
            "中性": "HOLD",
            "持有": "HOLD",
            "观望": "HOLD",
            "NEUTRAL": "HOLD",
            "HOLD": "HOLD",
            "谨慎": "HOLD",
            "CAUTIOUS": "HOLD",
        }
        return direction_map.get(direction)

    def classify(snippet: str) -> str | None:
        snippet_upper = snippet.upper()
        # 先清除否定语境中的交易动作，防止"不建议买入"被误匹配为BUY
        cleaned = _NEGATION_PATTERN.sub(' __NEGATED__ ', snippet_upper)
        sell_keywords = [
            "SELL",
            "卖出",
            "减持",
            "减仓",
            "清仓",
            "空仓",
            "回避",
            "看空",
            "偏空",
            "看跌",
            "做空",
        ]
        buy_keywords = [
            "BUY",
            "买入",
            "增持",
            "加仓",
            "做多",
            "看多",
            "偏多",
            "看涨",
            "谨慎看多",
            "有条件建仓",
            "条件建仓",
            "建仓",
            "抄底",
            "补仓",
        ]
        hold_keywords = [
            "HOLD",
            "观望",
            "持有",
            "中性",
            "等待",
            "暂不操作",
            "按兵不动",
        ]

        if any(k in cleaned for k in hold_keywords):
            return "HOLD"
        if any(k in cleaned for k in buy_keywords):
            return "BUY"
        if any(k in cleaned for k in sell_keywords):
            return "SELL"
        return None

    verdict_decision = parse_verdict_direction(text)
    if verdict_decision:
        return verdict_decision

    explicit_patterns = [
        r"最终裁决[:：]\s*([^\n*]+)",
        r"风控委员会最终裁决[:：]\s*([^\n*]+)",
        r"最终建议[:：]\s*([^\n*]+)",
        r"方向[:：]\s*([^\n*]+)",
        r"核心定性[:：]\s*([^\n*]+)",
    ]
    for pattern in explicit_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            decision = classify(match.group(1).strip())
            if decision:
                return decision

    headline = "\n".join(text.splitlines()[:20])
    decision = classify(headline)
    if decision:
        return decision

    decision = classify(upper)
    if decision:
        return decision

    return None
