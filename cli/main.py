"""TradingAgents CLI 入口。

提供 `tradingagents` 控制台命令，默认启动 API 服务。
用法: tradingagents [--host HOST] [--port PORT] [--reload]
"""

import argparse
import uvicorn


def app():
    parser = argparse.ArgumentParser(description="TradingAgents — A股多智能体投研系统")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址 (默认: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="监听端口 (默认: 8000)")
    parser.add_argument("--reload", action="store_true", help="开启热重载 (开发模式)")
    args = parser.parse_args()

    uvicorn.run(
        "api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    app()
