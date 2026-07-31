"""简化的问财数据获取器 —— 使用 playwright 直接访问问财网页

本模块使用 playwright 驱动浏览器访问问财网页，
获取涨停原因类别等数据，无需安装 iwencai-cli。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# 缓存目录
_CACHE_DIR = os.path.expanduser("~/.duanxian-agents/cache/iwencai")


def _get_cache_path(date: str) -> str:
    """获取缓存文件路径"""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f"{date}.json")


def _load_cache(date: str) -> Optional[Dict[str, str]]:
    """从缓存加载数据"""
    cache_path = _get_cache_path(date)
    if not os.path.exists(cache_path):
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "reasons" in data:
                return data["reasons"]
    except Exception as e:
        logger.warning(f"读取缓存失败: {e}")

    return None


def _save_cache(date: str, reasons: Dict[str, str]) -> None:
    """保存数据到缓存"""
    cache_path = _get_cache_path(date)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"reasons": reasons, "date": date}, f, ensure_ascii=False, indent=2)
        logger.info(f"已缓存 {len(reasons)} 只股票的涨停原因到 {cache_path}")
    except Exception as e:
        logger.warning(f"保存缓存失败: {e}")


def fetch_zt_reasons_via_playwright(date: str, force_refresh: bool = False) -> Tuple[Dict[str, str], Optional[str]]:
    """通过 playwright 获取涨停原因类别

    Args:
        date: 日期，格式为 'YYYYMMDD'
        force_refresh: 是否强制刷新缓存

    Returns:
        Tuple[Dict[str, str], Optional[str]]:
            - 第一个元素: {股票代码前6位: 涨停原因} 的字典
            - 第二个元素: 错误信息，成功时为 None
    """
    # 尝试从缓存加载
    if not force_refresh:
        cached = _load_cache(date)
        if cached:
            logger.info(f"从缓存加载 {len(cached)} 只股票的涨停原因")
            return cached, None

    try:
        from playwright.sync_api import sync_playwright
        import re

        # 构造查询语句
        year = date[:4]
        month = date[4:6]
        day = date[6:8]
        query = f"{year}年{month}月{day}日涨停的股票 涨停原因"

        logger.info(f"正在从问财获取数据: {query}")

        reasons = {}

        with sync_playwright() as p:
            # 启动浏览器
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )
            page = context.new_page()

            # 访问问财
            url = f"https://www.iwencai.com/unifiedwap/result?w={query}"
            page.goto(url, wait_until="networkidle", timeout=60000)

            # 等待表格加载
            page.wait_for_selector("table", timeout=30000)

            # 获取表格数据
            table = page.query_selector("table")
            if table:
                rows = table.query_selector_all("tr")
                headers = []

                for i, row in enumerate(rows):
                    cells = row.query_selector_all("td, th")
                    cell_texts = [cell.inner_text().strip() for cell in cells]

                    if i == 0:
                        # 表头行
                        headers = cell_texts
                        continue

                    # 数据行
                    if len(cell_texts) >= 2:
                        # 找到股票代码列
                        code_idx = None
                        reason_idx = None

                        for j, header in enumerate(headers):
                            if "代码" in header or "股票代码" in header:
                                code_idx = j
                            if "涨停原因" in header and "类别" in header:
                                reason_idx = j

                        if code_idx is not None and reason_idx is not None:
                            code = cell_texts[code_idx] if code_idx < len(cell_texts) else ""
                            reason = cell_texts[reason_idx] if reason_idx < len(cell_texts) else ""

                            if code and reason:
                                # 取前6位作为匹配键
                                code_key = code[:6]
                                reasons[code_key] = reason

            browser.close()

        if not reasons:
            return {}, "未找到涨停原因数据"

        # 保存到缓存
        _save_cache(date, reasons)

        logger.info(f"成功获取 {len(reasons)} 只股票的涨停原因")
        return reasons, None

    except ImportError:
        return {}, "playwright 未安装，请运行: pip install playwright"
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
    reasons, error = fetch_zt_reasons_via_playwright(date)

    if error:
        print(f"错误: {error}")
        return

    print(f"\n成功获取 {len(reasons)} 只股票的涨停原因:")
    for code, reason in sorted(reasons.items()):
        print(f"  {code}: {reason}")


if __name__ == "__main__":
    test_fetcher()
