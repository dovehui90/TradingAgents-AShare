import os
import tradingagents.default_config as default_config
from typing import Dict, Optional


def get_tushare_token() -> str:
    """获取 Tushare API Token。必须设置环境变量 TUSHARE_TOKEN。"""
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "TUSHARE_TOKEN environment variable is not set.\n"
            "Get your token from https://tushare.pro and add it to .env:\n"
            "  TUSHARE_TOKEN=your_token_here"
        )
    return token

# Use default config but allow it to be overridden
_config: Optional[Dict] = None


def initialize_config():
    """Initialize the configuration with default values."""
    global _config
    if _config is None:
        _config = default_config.DEFAULT_CONFIG.copy()


def set_config(config: Dict):
    """Update the configuration with custom values."""
    global _config
    if _config is None:
        _config = default_config.DEFAULT_CONFIG.copy()
    _config.update(config)


def get_config() -> Dict:
    """Get the current configuration."""
    if _config is None:
        initialize_config()
    return _config.copy()


# Initialize with default config
initialize_config()
