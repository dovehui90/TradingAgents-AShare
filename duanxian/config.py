"""LLM 配置 —— 统一读取主系统 DEFAULT_CONFIG，兼容 MiMo 环境变量回退。

优先级（make_llm 的 config 参数 > DEFAULT_CONFIG > 环境变量回退）：
1. 调用方传入的 config dict（来自设置页 UserLLMConfigDB）
2. tradingagents.default_config.DEFAULT_CONFIG（读 TA_* 环境变量）
3. ~/.config/mimo/mimo.env 文件（兜底兼容）

quick 档 = deepseek-v4-flash（快，跑分析师这种高频节点）
deep  档 = deepseek-v4-pro（推理模型，准，跑综合裁判这种收敛节点）
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from dotenv import dotenv_values
from langchain_openai import ChatOpenAI

from . import cli_llm

_MIMO_ENV = Path.home() / ".config" / "mimo" / "mimo.env"

# 主系统 .env 文件路径
_PROJECT_ENV = Path(__file__).parent.parent / ".env"

_CREDS: dict[str, str] | None = None


def _get_default(key: str, fallback: str = "") -> str:
    """从 DEFAULT_CONFIG 读取默认值，确保与主系统一致。"""
    try:
        from tradingagents.default_config import DEFAULT_CONFIG
        return DEFAULT_CONFIG.get(key, fallback)
    except ImportError:
        return fallback


def _ensure_mimo_loaded() -> None:
    """把 LLM 凭据读进**进程内的字典**（只读一次）

    兼容两种配置方式：
    1. 主系统 TA_API_KEY / TA_BASE_URL
    2. MiMo MIMO_API_KEY / MIMO_BASE_URL
    """
    global _CREDS
    if _CREDS is not None:
        return

    creds = {}

    # ① 环境变量优先（MIMO_* 或 TA_*）
    for k in ("MIMO_API_KEY", "MIMO_BASE_URL", "MIMO_MODEL"):
        v = os.environ.get(k)
        if v:
            creds[k] = v

    # ② 主系统 TA_* 环境变量
    if not creds.get("MIMO_API_KEY"):
        ta_key = os.environ.get("TA_API_KEY")
        ta_url = os.environ.get("TA_BASE_URL")
        if ta_key:
            creds["MIMO_API_KEY"] = ta_key
        if ta_url:
            creds["MIMO_BASE_URL"] = ta_url

    # ③ MiMo 配置文件
    if not creds.get("MIMO_API_KEY") and _MIMO_ENV.exists():
        creds.update({k: v for k, v in dotenv_values(_MIMO_ENV).items() if v})

    # ④ 主系统 .env 文件
    if not creds.get("MIMO_API_KEY") and _PROJECT_ENV.exists():
        env_vars = dotenv_values(_PROJECT_ENV)
        if env_vars.get("TA_API_KEY"):
            creds["MIMO_API_KEY"] = env_vars["TA_API_KEY"]
        if env_vars.get("TA_BASE_URL"):
            creds["MIMO_BASE_URL"] = env_vars["TA_BASE_URL"]

    if not creds.get("MIMO_API_KEY"):
        raise RuntimeError(
            "找不到 LLM API Key。请设置以下任一方式：\n"
            "1. 环境变量 TA_API_KEY 或 MIMO_API_KEY\n"
            "2. ~/.config/mimo/mimo.env 文件\n"
            "3. 项目 .env 文件中的 TA_API_KEY"
        )
    _CREDS = creds


def make_llm(deep: bool = False, temperature: float = 0.6, config: Optional[dict[str, Any]] = None):
    """构造复盘用的 LLM

    Args:
        deep: 是否使用深度模型（用于裁判）
        temperature: 温度参数
        config: 可选的统一配置 dict（来自设置页 UserLLMConfigDB），
                优先级高于 DEFAULT_CONFIG 和环境变量
    """
    kind = cli_llm.wanted_kind()
    if kind:
        return cli_llm.make_cli_llm(deep=deep)

    # 优先使用传入的 config（设置页配置），否则用 DEFAULT_CONFIG
    if config:
        base_url = config.get("backend_url") or _get_default("backend_url", "https://api.deepseek.com/v1")
        api_key = config.get("api_key") or ""
        if deep:
            model = config.get("deep_think_llm") or _get_default("deep_think_llm", "deepseek-v4-pro")
        else:
            model = config.get("quick_think_llm") or _get_default("quick_think_llm", "deepseek-v4-flash")
    else:
        # 回退到 DEFAULT_CONFIG（读 TA_* 环境变量）
        _ensure_mimo_loaded()
        assert _CREDS is not None

        base_url = _CREDS.get("MIMO_BASE_URL") or _get_default("backend_url", "https://api.deepseek.com/v1")
        api_key = _CREDS["MIMO_API_KEY"]

        if deep:
            model = _CREDS.get("MIMO_MODEL")
            if not model:
                model = _get_default("deep_think_llm", "deepseek-v4-pro")
        else:
            model = _get_default("quick_think_llm", "deepseek-v4-flash")

    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        timeout=180,
        max_retries=2,
    )
