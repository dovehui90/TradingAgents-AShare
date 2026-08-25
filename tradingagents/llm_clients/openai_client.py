import logging
import os
import time
from json import JSONDecodeError
from typing import Any, Optional

from langchain_openai import ChatOpenAI

_logger = logging.getLogger(__name__)

from .base_client import BaseLLMClient
from .validators import validate_model


class UnifiedChatOpenAI(ChatOpenAI):
    """ChatOpenAI subclass that strips incompatible params for certain models."""

    def __init__(self, **kwargs):
        # 彻底移除重试参数，由构造函数统一控制
        kwargs.pop("response_parse_retries", None)
        kwargs.pop("response_parse_retry_delay", None)

        model = kwargs.get("model") or kwargs.get("model_name", "")
        base_url = kwargs.get("base_url")

        # LOG_LEVEL=DEBUG 时开启 LangChain verbose，打印完整的 LLM 请求和响应
        if os.environ.get("LOG_LEVEL", "").upper() == "DEBUG":
            kwargs["verbose"] = True

        # 1. Reasoning models (O1 etc) typically don't support temperature
        if self._is_reasoning_model(model):
            kwargs.pop("temperature", None)
            kwargs.pop("top_p", None)

        # 2. Moonshot (Kimi) models often strictly require temperature=1
        if self._is_moonshot_model(model, base_url):
            kwargs["temperature"] = 1

        # 3. stream_chunk_timeout 不是所有提供商都支持，移除避免报错
        #    这个参数是 LangChain 特定的，但会被传递到底层 OpenAI 客户端
        kwargs.pop("stream_chunk_timeout", None)

        super().__init__(**kwargs)

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        result = super().invoke(input=input, config=config, **kwargs)
        if _logger.isEnabledFor(logging.DEBUG):
            content = result.content if hasattr(result, "content") else str(result)
            _logger.debug(f"[LLM Response] model={self.model_name} length={len(content)}\n{content}")
        return result

    @staticmethod
    def _is_reasoning_model(model: str) -> bool:
        """Check if model is a reasoning model."""
        model_lower = str(model).lower()
        return (
            model_lower.startswith("o1")
            or model_lower.startswith("o3")
            or "gpt-5" in model_lower
            or "-r1" in model_lower
            or "thinking" in model_lower
            or "reasoning" in model_lower
        )

    @staticmethod
    def _is_moonshot_model(model: str, base_url: Optional[str] = None) -> bool:
        """Check if model or base_url is from Moonshot (Kimi)."""
        m = str(model).lower()
        b = (base_url or "").lower()
        return "moonshot" in m or "kimi" in m or "moonshot" in b or "kimi" in b


class OpenAIClient(BaseLLMClient):
    """Client for OpenAI, Ollama, OpenRouter, and xAI providers."""

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        provider: str = "openai",
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()

    def get_llm(self) -> Any:
        """Return configured ChatOpenAI instance with long timeout and no retries."""
        llm_kwargs = {"model": self.model}

        if not UnifiedChatOpenAI._is_reasoning_model(self.model):
            llm_kwargs["temperature"] = self.kwargs.get("temperature", 0)

        # ── 稳定性配置 ──
        # 1. 启用重试：网络不稳定时自动重试，最多 3 次
        llm_kwargs["max_retries"] = self.kwargs.get("max_retries", 3)

        # 2. 总超时：默认 600 秒
        llm_kwargs["timeout"] = self.kwargs.get("timeout", 600.0)

        # 3. 流式块超时：默认 300 秒（覆盖 LangChain 的 120秒默认值）
        llm_kwargs["stream_chunk_timeout"] = self.kwargs.get("stream_chunk_timeout", 300.0)
        
        # Provider-specific default URLs (only used if user didn't provide base_url)
        _PROVIDER_DEFAULTS = {
            "xai": "https://api.x.ai/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "ollama": "http://localhost:11434/v1",
        }
        # User-provided base_url takes priority; fall back to provider default
        target_url = self.base_url or _PROVIDER_DEFAULTS.get(self.provider) or "https://api.openai.com/v1"

        print(f"[LLM Client] Init {self.provider} ({self.model}) at {target_url} (Retries=0, Timeout={llm_kwargs['timeout']}s)")

        # Set base_url (user-provided or provider default)
        llm_kwargs["base_url"] = target_url

        # API key: user-provided via kwargs takes priority; fall back to provider-specific env vars
        if self.provider == "xai" and "api_key" not in self.kwargs:
            api_key = os.environ.get("XAI_API_KEY")
            if api_key: llm_kwargs["api_key"] = api_key
        elif self.provider == "openrouter" and "api_key" not in self.kwargs:
            api_key = os.environ.get("OPENROUTER_API_KEY")
            if api_key: llm_kwargs["api_key"] = api_key
        elif self.provider == "ollama" and "api_key" not in self.kwargs:
            llm_kwargs["api_key"] = "ollama"

        # Pass remaining keys
        for key in ("api_key", "callbacks", "reasoning_effort"):
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        return UnifiedChatOpenAI(**llm_kwargs)

    def validate_model(self) -> bool:
        return validate_model(self.provider, self.model)
