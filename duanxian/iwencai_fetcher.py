"""问财数据获取器 —— 使用 iwencai-cli 获取涨停原因等数据

本模块使用 iwencai-cli 通过 Playwright 驱动 Chrome 访问问财网页，
无需 API Key，免费获取涨停原因类别等数据。
"""

from __future__ import annotations

import json
import subprocess
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def fetch_zt_reasons_via_cli(date: str) -> Tuple[Dict[str, str], Optional[str]]:
    """通过 iwencai-cli 获取涨停原因类别

    Args:
        date: 日期，格式为 'YYYYMMDD'

    Returns:
        Tuple[Dict[str, str], Optional[str]]:
            - 第一个元素: {股票代码前6位: 涨停原因} 的字典
            - 第二个元素: 错误信息，成功时为 None
    """
    try:
        # 构造查询语句
        year = date[:4]
        month = date[4:6]
        day = date[6:8]
        query = f"{year}年{month}月{day}日涨停的股票 涨停原因"

        # 调用 iwencai-cli
        result = subprocess.run(
            ["iwencai-query", "-q", query, "--json"],
            capture_output=True,
            text=True,
            timeout=120,  # 2分钟超时
        )

        if result.returncode != 0:
            error_msg = result.stderr or "未知错误"
            logger.warning(f"iwencai-cli 调用失败: {error_msg}")
            return {}, f"iwencai-cli 调用失败: {error_msg[:100]}"

        # 解析 JSON 输出
        output = result.stdout.strip()
        if not output:
            return {}, "iwencai-cli 无输出"

        # 找到 JSON 数组的开始位置（跳过前面的统计信息）
        json_start = output.find('[')
        if json_start == -1:
            return {}, f"iwencai-cli 输出格式错误: {output[:100]}"

        json_str = output[json_start:]
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            return {}, f"JSON 解析失败: {str(e)[:100]}"

        # 提取涨停原因
        reasons = {}
        for item in data:
            # 获取股票代码
            code = item.get("股票代码", "")
            if not code:
                continue

            # 取前6位作为匹配键
            code_key = code[:6]

            # 获取涨停原因类别（列名可能因日期而异）
            reason = None
            for key, value in item.items():
                if "涨停原因" in key and "类别" in key:
                    reason = value
                    break

            if reason:
                reasons[code_key] = reason

        if not reasons:
            return {}, "未找到涨停原因数据"

        logger.info(f"成功获取 {len(reasons)} 只股票的涨停原因")
        return reasons, None

    except subprocess.TimeoutExpired:
        return {}, "iwencai-cli 调用超时"
    except FileNotFoundError:
        return {}, "iwencai-cli 未安装，请运行: pip install git+https://github.com/shaw-baobao/iwencai-cli.git"
    except Exception as e:
        logger.exception(f"获取涨停原因时发生异常: {e}")
        return {}, f"获取涨停原因异常: {type(e).__name__}: {str(e)[:100]}"


def test_fetcher():
    """测试函数"""
    import sys
    from datetime import datetime

    # 使用今天的日期
    date = datetime.now().strftime("%Y%m%d")
    if len(sys.argv) > 1:
        date = sys.argv[1]

    print(f"测试获取 {date} 的涨停原因...")
    reasons, error = fetch_zt_reasons_via_cli(date)

    if error:
        print(f"错误: {error}")
        return

    print(f"\n成功获取 {len(reasons)} 只股票的涨停原因:")
    for code, reason in sorted(reasons.items()):
        print(f"  {code}: {reason}")


if __name__ == "__main__":
    test_fetcher()
