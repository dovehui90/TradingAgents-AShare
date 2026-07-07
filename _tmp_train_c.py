"""Quick test: train Pool C only"""
import sys; sys.path.insert(0, '.')
from tools.train_buypoint_v5 import POOL_C_SYMBOLS, TRAIN_END
from tradingagents.buy_point.ml_trainer import train

print(f"Pool C: {len(POOL_C_SYMBOLS)} stocks, cutoff={TRAIN_END}")
model, metrics = train(POOL_C_SYMBOLS, pool='C', test_ratio=0.2, data_end=TRAIN_END)
print(f"Done: {metrics['train_samples']} train / {metrics['test_samples']} test")
print(f"Features: {metrics['features']}, pos_rate: {metrics['pos_rate_test']:.1%}")
for t in [0.3, 0.4, 0.5, 0.6, 0.7]:
    m = metrics.get(f'thresh_{t}', {})
    if m: print(f"  th={t:.1f}: {m['trades']} trades, WR={m['win_rate']}%")
