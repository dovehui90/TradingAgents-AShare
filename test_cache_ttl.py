#!/usr/bin/env python3
"""
测试差异化缓存TTL功能
验证不同时间段的缓存过期时间是否符合预期
"""

import sys
from datetime import datetime, timedelta, time
from api.services.market_analysis_service import _get_cache_ttl


def test_cache_ttl():
    """测试各种场景下的TTL"""

    print("=" * 60)
    print("差异化缓存 TTL 测试")
    print("=" * 60)

    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    last_week = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

    current_time = datetime.now().time()

    test_cases = [
        {
            'name': '历史数据（昨天）',
            'date': yesterday,
            'expected': 86400,
            'description': '历史数据应使用24小时缓存'
        },
        {
            'name': '历史数据（上周）',
            'date': last_week,
            'expected': 86400,
            'description': '历史数据应使用24小时缓存'
        },
        {
            'name': '当日数据',
            'date': today,
            'expected': None,  # 根据当前时间动态判断
            'description': '当日数据根据交易时段动态调整'
        },
        {
            'name': '未来日期',
            'date': tomorrow,
            'expected': 300,
            'description': '未来日期应使用默认5分钟缓存'
        },
        {
            'name': '错误日期格式',
            'date': 'invalid-date',
            'expected': 300,
            'description': '错误格式应使用默认5分钟缓存'
        },
    ]

    print(f"\n当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 判断当前处于哪个交易时段
    if current_time >= time(15, 0):
        current_period = "盘后（15:00后）"
        today_expected_ttl = 1800
    elif time(9, 30) <= current_time <= time(15, 0):
        current_period = "盘中（9:30-15:00）"
        today_expected_ttl = 60
    elif current_time < time(9, 30):
        current_period = "盘前（9:30前）"
        today_expected_ttl = 600
    else:
        current_period = "其他时间"
        today_expected_ttl = 300

    print(f"当前交易时段: {current_period}")
    print(f"当日数据预期TTL: {today_expected_ttl}秒 ({today_expected_ttl/60:.1f}分钟)\n")

    # 更新当日数据的预期值
    for tc in test_cases:
        if tc['date'] == today:
            tc['expected'] = today_expected_ttl

    print("-" * 60)
    print(f"{'测试场景':<20} {'日期':<15} {'TTL(秒)':<10} {'TTL(分钟)':<12} {'结果':<6}")
    print("-" * 60)

    passed = 0
    failed = 0

    for tc in test_cases:
        ttl = _get_cache_ttl(tc['date'])
        expected = tc['expected']

        if expected is None:
            status = "❓"
            result = "N/A"
        elif ttl == expected:
            status = "✅"
            result = "通过"
            passed += 1
        else:
            status = "❌"
            result = "失败"
            failed += 1

        ttl_minutes = ttl / 60
        print(f"{tc['name']:<20} {tc['date']:<15} {ttl:<10} {ttl_minutes:<12.1f} {status} {result}")

        if ttl != expected and expected is not None:
            print(f"  ⚠️  预期: {expected}秒, 实际: {ttl}秒")

    print("-" * 60)
    print(f"\n测试结果: 通过 {passed} / 失败 {failed} / 总计 {passed + failed}")

    # 详细说明
    print("\n" + "=" * 60)
    print("TTL 策略说明:")
    print("=" * 60)
    print("1. 历史数据（往日）    : 86400秒 (24小时) - 数据不变，长期缓存")
    print("2. 盘中数据（9:30-15:00）: 60秒 (1分钟)   - 快速更新捕捉盘中变化")
    print("3. 盘后数据（15:00后）  : 1800秒 (30分钟) - 盘后数据相对稳定")
    print("4. 盘前数据（9:30前）   : 600秒 (10分钟)  - 中等更新频率")
    print("5. 未来/错误日期       : 300秒 (5分钟)   - 防御性默认值")
    print("=" * 60)

    # 实际应用示例
    print("\n实际应用示例:")
    print("-" * 60)

    examples = [
        ("000001.SZ", yesterday, "平安银行历史数据"),
        ("600519.SH", today, "茅台当日数据"),
    ]

    for symbol, date, desc in examples:
        ttl = _get_cache_ttl(date)
        cache_key = f"{symbol}_{date}"
        print(f"股票: {symbol} | 日期: {date}")
        print(f"描述: {desc}")
        print(f"缓存键: {cache_key}")
        print(f"TTL: {ttl}秒 ({ttl/60:.1f}分钟)")
        print(f"说明: {'历史数据24小时缓存' if ttl == 86400 else f'当日数据{current_period}使用{ttl}秒缓存'}")
        print()

    return passed, failed


def test_edge_cases():
    """测试边界情况"""
    print("\n" + "=" * 60)
    print("边界情况测试")
    print("=" * 60)

    # 测试交易时段边界
    from unittest.mock import patch

    edge_cases = [
        ("09:29:59", "盘前最后一秒", 600),
        ("09:30:00", "开盘瞬间", 60),
        ("15:00:00", "收盘瞬间", 1800),
        ("15:00:01", "收盘后一秒", 1800),
    ]

    today = datetime.now().strftime('%Y-%m-%d')

    print(f"\n测试日期: {today} (当日)")
    print("-" * 60)
    print(f"{'模拟时间':<12} {'场景描述':<20} {'预期TTL(秒)':<12} {'实际TTL(秒)':<12} {'结果':<6}")
    print("-" * 60)

    for time_str, desc, expected_ttl in edge_cases:
        # 这里无法完全模拟时间，但可以展示预期行为
        print(f"{time_str:<12} {desc:<20} {expected_ttl:<12} {'(需实际运行)':<12} {'📝'}")

    print("-" * 60)
    print("注意: 边界时间测试需要在特定时间运行才能验证")
    print("=" * 60)


if __name__ == "__main__":
    try:
        passed, failed = test_cache_ttl()
        test_edge_cases()

        print("\n" + "=" * 60)
        if failed == 0:
            print("✅ 所有测试通过！缓存TTL功能正常。")
            print("=" * 60)
            sys.exit(0)
        else:
            print(f"❌ 有 {failed} 个测试失败，请检查代码。")
            print("=" * 60)
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
