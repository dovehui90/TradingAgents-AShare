#!/usr/bin/env python
"""全量重建 daily_k parquet 数据 — 内存批量版。

策略：所有交易日数据收集到内存 → 按股票分组 → 一次性写 parquet。
避免逐日读写 5000 个文件的 I/O 瓶颈。
"""

import os, sys, json, time, shutil, logging
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(str(PROJECT_ROOT / '.env'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

import tushare as ts
import pandas as pd
import numpy as np

TOKEN = os.environ.get('TUSHARE_TOKEN')
if not TOKEN:
    logger.error("TUSHARE_TOKEN 未设置！")
    sys.exit(1)
ts.set_token(TOKEN)
pro = ts.pro_api()

CACHE_DIR = PROJECT_ROOT / 'data' / 'yang_yin_cache'
DAILY_DIR = CACHE_DIR / 'daily_k'
CHECKPOINT_DIR = CACHE_DIR / 'daily_k_checkpoints'
START_DATE = '20240101'
END_DATE = datetime.now().strftime('%Y%m%d')

# ── Step 1 & 2: 交易日历 + 股票列表 ──────────────────

logger.info("Step 1: 获取交易日历...")
cal = pro.trade_cal(exchange='SSE', start_date=START_DATE, end_date=END_DATE)
TRADE_DATES = sorted(cal[cal['is_open'] == 1]['cal_date'].tolist())
logger.info(f"  交易日: {len(TRADE_DATES)} 天 ({TRADE_DATES[0]} ~ {TRADE_DATES[-1]})")

logger.info("Step 2: 获取股票列表...")
stocks = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name')
stocks = stocks[~stocks['ts_code'].str.startswith('8')]
stocks = stocks[~stocks['name'].str.contains('ST', na=False)]
STOCK_SET = set(stocks['ts_code'].tolist())
logger.info(f"  股票: {len(STOCK_SET)} 只")

# ── Step 3: 批量拉取数据到内存 ─────────────────────────

CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
all_dfs = []
t0 = time.monotonic()
BATCH_SIZE = 50  # 每批处理 50 个交易日，存 checkpoint

for batch_start in range(0, len(TRADE_DATES), BATCH_SIZE):
    batch = TRADE_DATES[batch_start:batch_start + BATCH_SIZE]
    batch_dfs = []

    for td in batch:
        try:
            df = pro.daily(trade_date=td)
            if df is not None and not df.empty:
                df = df[df['ts_code'].isin(STOCK_SET)]
                if not df.empty:
                    df = df[['ts_code', 'trade_date', 'open', 'high', 'low',
                             'close', 'vol', 'amount', 'pct_chg']].copy()
                    # 确保数值类型
                    for col in ['open', 'high', 'low', 'close', 'vol', 'pct_chg']:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                    df['amount'] = pd.to_numeric(df.get('amount', 0), errors='coerce').fillna(0)
                    batch_dfs.append(df)
        except Exception as e:
            logger.warning(f"  {td}: {e}")
            continue

    if batch_dfs:
        batch_df = pd.concat(batch_dfs, ignore_index=True)
        # 保存 checkpoint（parquet 格式，便于恢复）
        cp_path = CHECKPOINT_DIR / f"batch_{batch_start:04d}.parquet"
        batch_df.to_parquet(cp_path, index=False)
        all_dfs.append(batch_df)
        logger.info(f"  批次 {batch_start//BATCH_SIZE + 1}: "
                    f"{len(batch)} 天 → {len(batch_df)} 行, 累计 {sum(len(d) for d in all_dfs)} 行")

    elapsed = time.monotonic() - t0
    if batch_start + BATCH_SIZE < len(TRADE_DATES):
        remaining = (len(TRADE_DATES) - batch_start - BATCH_SIZE) / BATCH_SIZE
        eta = elapsed / (batch_start / BATCH_SIZE + 1) * remaining
        logger.info(f"    预计剩余 {eta:.0f}s")

collection_time = time.monotonic() - t0
logger.info(f"数据收集完成: {len(all_dfs)} 批, {sum(len(d) for d in all_dfs)} 行, {collection_time:.0f}s")

# ── Step 4: 合并 → 按股票分组 → 写入 parquet ──────────

logger.info("Step 4: 合并并按股票写入 parquet...")
t0 = time.monotonic()

# 合并所有批次
full_df = pd.concat(all_dfs, ignore_index=True)
full_df = full_df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
n_rows = len(full_df)
n_stocks = full_df['ts_code'].nunique()
logger.info(f"  合并: {n_rows} 行, {n_stocks} 只股票")

# 准备新目录
NEW_DIR = CACHE_DIR / 'daily_k_new'
if NEW_DIR.exists():
    shutil.rmtree(str(NEW_DIR))
NEW_DIR.mkdir(parents=True, exist_ok=True)

# 按股票分组，一次性写入
written = 0
errors = 0
for ts_code, group in full_df.groupby('ts_code'):
    try:
        group = group.sort_values('trade_date')
        path = NEW_DIR / f"{ts_code.replace('.', '_')}.parquet"
        group.to_parquet(path, index=False)
        written += 1
    except Exception as e:
        logger.warning(f"  {ts_code} 写入失败: {e}")
        errors += 1
    if written % 1000 == 0:
        logger.info(f"  已写入 {written}/{n_stocks}...")

write_time = time.monotonic() - t0
logger.info(f"  写入完成: {written} 成功, {errors} 失败, {write_time:.0f}s")

# ── Step 5: 验证 ──────────────────────────────────────

logger.info("Step 5: 验证...")
new_files = list(NEW_DIR.glob('*.parquet'))
valid = 0
corrupted = []
total_rows = 0

for f in new_files:
    try:
        df = pd.read_parquet(f)
        if len(df) > 0:
            valid += 1
            total_rows += len(df)
        else:
            corrupted.append(f.name)
    except Exception:
        corrupted.append(f.name)

logger.info(f"  有效: {valid}, 损坏/空: {len(corrupted)}, 总行数: {total_rows}")
if corrupted:
    logger.warning(f"  损坏文件: {corrupted[:10]}")

if valid < n_stocks * 0.95:
    logger.error(f"  有效文件数不足 95%，中止！")
    sys.exit(1)

# ── Step 6: 原子替换 ──────────────────────────────────

logger.info("Step 6: 原子替换...")
backup_dir = CACHE_DIR / f"daily_k_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
if list(DAILY_DIR.glob('*.parquet')):
    shutil.move(str(DAILY_DIR), str(backup_dir))
    logger.info(f"  旧数据备份: {backup_dir}")

shutil.move(str(NEW_DIR), str(DAILY_DIR))
logger.info(f"  新数据已就位: {DAILY_DIR}")

# 清理
shutil.rmtree(str(CHECKPOINT_DIR), ignore_errors=True)
shutil.rmtree(str(backup_dir), ignore_errors=True)

# ── 最终验证 ──────────────────────────────────────────

final_files = list(DAILY_DIR.glob('*.parquet'))
final_ok = sum(1 for f in final_files if f.stat().st_size > 100)  # 至少 100 字节
logger.info(f"\n✓ 完成！{final_ok}/{len(final_files)} 个文件, 总耗时 {time.monotonic()-t0+collection_time:.0f}s")
