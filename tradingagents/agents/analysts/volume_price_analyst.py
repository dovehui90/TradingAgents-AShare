import asyncio
import logging
from datetime import datetime, timedelta

from langchain_core.messages import HumanMessage, SystemMessage

from tradingagents.dataflows.config import get_config
from tradingagents.prompts import get_prompt
from tradingagents.graph.intent_parser import build_horizon_context
from tradingagents.agents.utils.agent_states import current_tracker_var, extract_verdict

logger = logging.getLogger(__name__)


def _is_empty_or_failed(value) -> bool:
    """Check if data is empty, default placeholder, or contains a failure message."""
    if not value:
        return True
    s = str(value)
    if s == "无数据":
        return True
    if "调用失败" in s:
        return True
    if "数据不足" in s:
        return True
    return False


async def _fetch_vpa_direct(ticker: str, current_date: str):
    """Fallback: directly fetch stock_data and compute VPA indicators locally.

    Used when the DataCollector cache is empty or stock_data / vpa_indicators
    are missing — identical pattern to other analysts' _fetch_direct().
    """
    from tradingagents.agents.utils.core_stock_tools import get_stock_data
    from tradingagents.agents.utils.game_theory_tools import get_level2_quotes
    from tradingagents.graph.data_collector import _parse_csv_to_dataframe, _compute_vpa_indicators

    async def _safe(tool, payload):
        try:
            return await asyncio.to_thread(tool.invoke, payload)
        except Exception as exc:
            logger.warning("VPA direct fetch %s failed: %s", getattr(tool, "name", str(tool)), exc)
            return f"调用失败：{exc}"

    end_dt = datetime.strptime(current_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=365)

    stock_result, level2_result = await asyncio.gather(
        _safe(get_stock_data, {
            "symbol": ticker,
            "start_date": start_dt.strftime("%Y-%m-%d"),
            "end_date": current_date,
        }),
        _safe(get_level2_quotes, {
            "symbol": ticker,
            "date": current_date,
        }),
    )

    vpa_data = "VPA 数据不足"
    stock_str = str(stock_result) if stock_result else ""
    if not _is_empty_or_failed(stock_str) and len(stock_str) > 50:
        df = _parse_csv_to_dataframe(stock_str)
        if df is not None:
            try:
                vpa_data = _compute_vpa_indicators(df.copy())
            except Exception as exc:
                logger.warning("VPA direct compute failed for %s: %s", ticker, exc)
                vpa_data = f"VPA 计算失败：{exc}"

    level2_str = str(level2_result) if level2_result else "无数据"
    return stock_str, vpa_data, level2_str, "14天"


def create_volume_price_analyst(llm, data_collector=None):
    async def volume_price_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        horizon = "short"
        user_intent = state.get("user_intent") or {}
        focus_areas = user_intent.get("focus_areas", [])
        specific_questions = user_intent.get("specific_questions", [])

        config = get_config()
        horizon_ctx = build_horizon_context(horizon, focus_areas, specific_questions, agent_type="volume_price")
        system_message = get_prompt("volume_price_system_message", config=config)

        # ── Data fetching with fallback (aligned with market/fundamentals analysts) ──
        vpa_data = stock_data = level2_quotes = data_window = None
        used_fallback = False

        if data_collector is not None:
            pool = data_collector.get(ticker, current_date)
            if pool is not None:
                windowed = data_collector.get_window(pool, horizon, current_date)
                vpa_data = windowed.get("vpa_indicators", "无数据")
                stock_data = windowed.get("stock_data", "无数据")
                level2_quotes = windowed.get("level2_quotes", "无数据")
                data_window = windowed.get("_data_window", "14天")

        # If any critical data is missing, fall back to direct tool calls
        if _is_empty_or_failed(stock_data) or _is_empty_or_failed(vpa_data):
            logger.warning(
                "Volume Price Analyst: cache data empty for %s (stock=%s, vpa=%s), trying direct fetch",
                ticker,
                "ok" if not _is_empty_or_failed(stock_data) else "empty",
                "ok" if not _is_empty_or_failed(vpa_data) else "empty",
            )
            try:
                stock_data, vpa_data, level2_quotes, data_window = await _fetch_vpa_direct(ticker, current_date)
                used_fallback = True
            except Exception as exc:
                logger.error("Volume Price Analyst direct fetch failed for %s: %s", ticker, exc)
                if not stock_data or _is_empty_or_failed(stock_data):
                    stock_data = "无数据"
                if not vpa_data or _is_empty_or_failed(vpa_data):
                    vpa_data = "VPA 数据不足（直接获取也失败）"
                if not level2_quotes:
                    level2_quotes = "无数据"
                if not data_window:
                    data_window = "14天"

        # Final defaults (should not normally be reached)
        if vpa_data is None:
            vpa_data = "无数据"
        if stock_data is None:
            stock_data = "无数据"
        if level2_quotes is None:
            level2_quotes = "无数据"
        if data_window is None:
            data_window = "14天"

        # ── Build the LLM prompt ──
        data_source_note = "（通过直接调用获取）" if used_fallback else "（来自预采集缓存）"
        messages = [
            SystemMessage(content=horizon_ctx + system_message + "\n\n请全程使用中文。"),
            HumanMessage(content=(
                f"以下是 {ticker} 在 {current_date} 的量价分析预计算数据（数据窗口：{data_window}）{data_source_note}。\n\n"
                f"{vpa_data}\n\n"
                f"【原始 K 线数据参考】\n{stock_data}\n\n"
                f"【逐笔成交明细（Level 2）】\n{level2_quotes}"
            )),
        ]

        tracker = current_tracker_var.get()
        full_content = ""
        async for chunk in llm.astream(messages):
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            full_content += content
            if tracker:
                tracker._emit_token("Volume Price Analyst", "volume_price_report", content)

        verdict, confidence = extract_verdict(full_content)

        return {
            "volume_price_report": full_content,
            "analyst_traces": [{
                "agent": "volume_price_analyst",
                "horizon": horizon,
                "data_window": data_window,
                "key_finding": f"量价分析结论：{verdict}",
                "verdict": verdict,
                "confidence": confidence,
            }],
        }

    return volume_price_analyst_node
