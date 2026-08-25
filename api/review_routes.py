"""Vibe-Astock 短线复盘 API 路由

提供每日复盘、实时情绪、外围市场等功能。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

# 添加项目根目录到 path
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

router = APIRouter(prefix="/v1/review", tags=["短线复盘"])

# ---- 全局状态 ----
_review_state = {
    "running": False,
    "last_result": None,
    "last_date": None,
    "error": None,
}
_lock = threading.Lock()

_REVIEW_DIR = os.path.expanduser("~/.duanxian-agents/reviews")


def _load_review(trade_date: str) -> Optional[dict]:
    """从本地文件加载复盘结果"""
    path = os.path.join(_REVIEW_DIR, f"{trade_date}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _list_review_dates() -> list[str]:
    """列出所有有复盘结果的日期"""
    if not os.path.exists(_REVIEW_DIR):
        return []
    files = [f.replace(".json", "") for f in os.listdir(_REVIEW_DIR) if f.endswith(".json")]
    return sorted(files, reverse=True)


# ---- 模型 ----
class ReviewRunRequest(BaseModel):
    trade_date: Optional[str] = None  # 默认今天


class ReviewChatRequest(BaseModel):
    question: str
    trade_date: Optional[str] = None


# ---- 路由 ----
@router.post("/run")
async def run_review(request: ReviewRunRequest, background_tasks: BackgroundTasks):
    """触发每日复盘（异步执行）"""
    from duanxian.util import china_today, validate_trade_date
    from duanxian.preflight import check as preflight_check

    trade_date = request.trade_date or china_today()
    try:
        trade_date = validate_trade_date(trade_date)
    except ValueError as e:
        raise HTTPException(400, f"日期错误: {e}")

    with _lock:
        if _review_state["running"]:
            raise HTTPException(409, "复盘正在运行中，请稍后再试")
        _review_state["running"] = True
        _review_state["error"] = None

    # 获取当前用户ID（从请求头中提取）
    user_id = None
    try:
        from api.main import _require_api_user, get_db_ctx, auth_service
        from fastapi.security import HTTPBearer
        from starlette.requests import Request
        # 尝试从请求中获取用户信息
        import inspect
        frame = inspect.currentframe()
        # 由于没有直接的 request 参数，使用默认配置
        user_id = None
    except Exception:
        pass

    def _run():
        try:
            from vibe_main import initial_state, run as vibe_run
            from api.main import _build_runtime_config
            # 构建统一配置（读取用户设置页配置）
            merged_config = _build_runtime_config({}, user_id=user_id)
            result, pre = vibe_run(trade_date, config=merged_config)
            with _lock:
                _review_state["last_result"] = result
                _review_state["last_date"] = trade_date
        except Exception as e:
            with _lock:
                _review_state["error"] = str(e)
        finally:
            with _lock:
                _review_state["running"] = False

    background_tasks.add_task(_run)
    return {"status": "started", "trade_date": trade_date}


@router.get("/status")
async def get_review_status():
    """获取复盘运行状态"""
    with _lock:
        return {
            "running": _review_state["running"],
            "last_date": _review_state["last_date"],
            "error": _review_state["error"],
        }


@router.get("/latest")
async def get_latest_review(trade_date: Optional[str] = None):
    """获取最新复盘结果"""
    from duanxian.util import china_today

    date = trade_date or china_today()

    # 先检查内存中的结果
    with _lock:
        if _review_state["last_result"] and _review_state["last_date"] == date:
            return _review_state["last_result"]

    # 再检查文件
    result = _load_review(date)
    if result:
        return result

    # 尝试最近的日期
    dates = _list_review_dates()
    if dates:
        result = _load_review(dates[0])
        if result:
            return result

    raise HTTPException(404, f"未找到 {date} 的复盘结果")


@router.get("/dates")
async def get_review_dates():
    """获取可查询的复盘日期列表"""
    return {"dates": _list_review_dates()}


@router.post("/evaluate")
async def evaluate_review(trade_date: Optional[str] = None):
    """回评上期预测"""
    from duanxian.util import china_today
    from duanxian import reflection

    date = trade_date or china_today()
    try:
        reflection.auto_evaluate_prior(date)
        return {"status": "ok", "message": f"已回评 {date} 的预测"}
    except Exception as e:
        raise HTTPException(500, f"回评失败: {e}")


@router.post("/chat")
async def review_chat(request: ReviewChatRequest):
    """复盘对话（基于已有复盘结果回答问题）"""
    from duanxian.util import china_today
    from duanxian.config import make_llm

    date = request.trade_date or china_today()
    result = _load_review(date)

    if not result:
        with _lock:
            if _review_state["last_result"] and _review_state["last_date"] == date:
                result = _review_state["last_result"]

    if not result:
        raise HTTPException(404, f"未找到 {date} 的复盘结果，请先运行复盘")

    # 构建上下文
    context = f"""你是 A 股短线复盘助手。以下是 {date} 的复盘数据：

情绪面：{result.get('sentiment_report', '无')}
资金面：{result.get('capital_report', '无')}
题材热点：{result.get('theme_report', '无')}
龙虎榜：{result.get('dragon_tiger_report', '无')}
龙头跟踪：{result.get('leader_report', '无')}
明天关注：{result.get('tomorrow_focus', '无')}

请基于以上数据回答用户问题。"""

    # 构建统一配置（使用 DEFAULT_CONFIG）
    from api.main import _build_runtime_config
    merged_config = _build_runtime_config({})

    try:
        llm = make_llm(config=merged_config)
        from langchain_core.messages import HumanMessage, SystemMessage
        response = llm.invoke([
            SystemMessage(content=context),
            HumanMessage(content=request.question),
        ])
        return {"answer": response.content, "date": date}
    except Exception as e:
        raise HTTPException(500, f"AI 回答失败: {e}")


# ---- 实时市场数据路由 ----
market_router = APIRouter(prefix="/v1/review-market", tags=["复盘市场数据"])


@market_router.get("/live-emotion")
async def get_live_emotion():
    """获取实时情绪指标"""
    try:
        from duanxian import live_emotion
        return live_emotion.get_live_emotion()
    except Exception as e:
        raise HTTPException(500, f"获取实时情绪失败: {e}")


@market_router.get("/overseas")
async def get_overseas():
    """获取隔夜外围市场数据"""
    try:
        from duanxian import overseas
        return overseas.get_overseas()
    except Exception as e:
        raise HTTPException(500, f"获取外围数据失败: {e}")


@market_router.get("/session")
async def get_market_session():
    """获取当前市场交易时段"""
    try:
        from duanxian import trade_calendar
        return trade_calendar.get_session_info()
    except Exception as e:
        raise HTTPException(500, f"获取交易时段失败: {e}")
