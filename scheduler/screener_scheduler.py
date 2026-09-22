"""选股神器盘后定时重算 — 收盘后重算 signal 历史 + signals.json。

选股神器此前只在启动预热时算一次信号，收盘后不再更新，导致前端选当天日期
却显示昨日数据。本模块补一个盘后重算，照搬阳谱 scheduler 的模式。

由 scheduler/main.py 的 _startup() 调用，与主调度循环并行运行。
"""

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

CST = ZoneInfo("Asia/Shanghai")

# 盘后重算时间：比阳谱的 16:05 稍晚，等 tushare 发布当日 adj_factor
# （选股神器 K 线用 pro_bar(adj='qfq')，依赖 adj_factor，发布比 pro.daily 晚）
POST_MARKET_HOUR = 17
POST_MARKET_MINUTE = 0


def _is_trading_day(date_str: str) -> bool:
    from tradingagents.dataflows.trade_calendar import is_cn_trading_day
    return is_cn_trading_day(date_str)


async def screener_post_market_loop():
    """盘后定时重算选股神器信号，交易日 17:00 后每天一次。"""
    logger.info("[选股神器] 盘后重算循环启动 (每日 17:00)")

    while True:
        try:
            now = datetime.now(CST)
            today = now.strftime("%Y-%m-%d")
            today_yyyymmdd = now.strftime("%Y%m%d")

            if not _is_trading_day(today):
                await asyncio.sleep(60)
                continue

            if (now.hour, now.minute) >= (POST_MARKET_HOUR, POST_MARKET_MINUTE):
                # 当天已跑过就等到次日，避免重复重算
                if getattr(screener_post_market_loop, "_done_date", "") == today_yyyymmdd:
                    await asyncio.sleep(600)
                    continue

                from api.main import run_screener_post_market_update
                try:
                    await asyncio.to_thread(run_screener_post_market_update)
                except Exception as e:
                    logger.error(f"[选股神器] 盘后重算失败: {e}")

                screener_post_market_loop._done_date = today_yyyymmdd

                # 等到次日 9:25
                tomorrow = now.date() + timedelta(days=1)
                next_check = datetime(
                    tomorrow.year, tomorrow.month, tomorrow.day, 9, 25, 0, tzinfo=CST
                )
                wait = max(60.0, (next_check - now).total_seconds())
                logger.info(f"[选股神器] 盘后重算完成，{wait / 3600:.1f}h 后恢复检查")
                await asyncio.sleep(wait)
                continue

            await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("[选股神器] 盘后重算循环已取消")
            break
        except Exception as e:
            logger.error(f"[选股神器] 循环异常: {e}")
            await asyncio.sleep(60)
