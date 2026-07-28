#!/usr/bin/env python3
"""
快速验证测试：不依赖网络，直接测试缓存TTL逻辑
"""

import sys
from datetime import datetime, timedelta, time


def test_get_cache_ttl_logic():
    """测试 _get_cache_ttl 函数的核心逻辑"""

    # 导入函数
    sys.path.insert(0, '/Users/luhui/Desktop/AI_project/TradingAgents-AShare')
    from api.services.market_analysis_service import _get_cache_ttl

    print("=" * 70)
    print("快速验证：缓存TTL逻辑测试")
    print("=" * 70)

    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    last_week = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

    current_time = datetime.now().time()

    # 确定当前时段
    if current_time >= time(15, 0):
        current_period = "盘后（15:00后）"
        today_expected = 1800
    elif time(9, 30) <= current_time <= time(15, 0):
        current_period = "盘中（9:30-15:00）"
        today_expected = 60
    elif current_time < time(9, 30):
        current_period = "盘前（9:30前）"
        today_expected = 600
    else:
        current_period = "其他"
        today_expected = 300

    print(f"\n当前时间: {datetime.now().strftime('%H:%M:%S')}")
    print(f"当前时段: {current_period}")
    print(f"当日预期TTL: {today_expected}秒\n")

    test_cases = [
        ("昨天", yesterday, 86400),
        ("上周", last_week, 86400),
        ("今天", today, today_expected),
        ("明天", tomorrow, 300),
        ("错误格式", "invalid", 300),
    ]

    print("-" * 70)
    print(f"{'场景':<15} {'日期':<15} {'实际TTL':<12} {'预期TTL':<12} {'状态':<10}")
    print("-" * 70)

    all_passed = True

    for name, date, expected in test_cases:
        actual = _get_cache_ttl(date)
        status = "✅ 通过" if actual == expected else "❌ 失败"

        if actual != expected:
            all_passed = False

        print(f"{name:<15} {date:<15} {actual:<12} {expected:<12} {status:<10}")

    print("-" * 70)

    if all_passed:
        print("\n✅ 所有测试通过！")
        print("\n功能验证成功：")
        print("  ✓ 历史数据使用 24小时 缓存")
        print(f"  ✓ 当日数据使用 {today_expected}秒 缓存（{current_period}）")
        print("  ✓ 未来/错误日期使用 5分钟 默认缓存")
        print("  ✓ 边界情况处理正确")
        return True
    else:
        print("\n❌ 有测试失败，请检查代码")
        return False


def verify_code_changes():
    """验证代码修改是否正确"""

    print("\n" + "=" * 70)
    print("代码修改验证")
    print("=" * 70)

    with open('/Users/luhui/Desktop/AI_project/TradingAgents-AShare/api/services/market_analysis_service.py', 'r', encoding='utf-8') as f:
        content = f.read()

    checks = [
        ("_get_cache_ttl 函数存在", "def _get_cache_ttl(analysis_date: str) -> int:" in content),
        ("历史数据返回86400", "return 86400" in content),
        ("盘后返回1800", "return 1800" in content),
        ("盘中返回60", "return 60" in content),
        ("盘前返回600", "return 600" in content),
        ("调用 _get_cache_ttl", "ttl = _get_cache_ttl(date)" in content),
        ("使用动态TTL检查", "if datetime.now().timestamp() - cached_time < ttl:" in content),
    ]

    print("\n检查项:")
    print("-" * 70)

    all_passed = True
    for desc, passed in checks:
        status = "✅" if passed else "❌"
        print(f"{status} {desc}")
        if not passed:
            all_passed = False

    print("-" * 70)

    if all_passed:
        print("\n✅ 所有代码修改验证通过")
        return True
    else:
        print("\n❌ 部分检查未通过")
        return False


def show_summary():
    """显示修改摘要"""

    print("\n" + "=" * 70)
    print("📋 修改摘要")
    print("=" * 70)

    print("\n修改的文件:")
    print("  • api/services/market_analysis_service.py")

    print("\n新增的函数:")
    print("  • _get_cache_ttl(analysis_date: str) -> int")

    print("\n修改的逻辑:")
    print("  • 原来: 统一使用 _CACHE_TTL = 300 秒")
    print("  • 现在: 根据日期和时间段动态计算TTL")

    print("\nTTL 策略:")
    print("  • 历史数据（往日）    : 86400秒 (24小时)")
    print("  • 盘中数据（9:30-15:00）: 60秒 (1分钟)")
    print("  • 盘后数据（15:00后）  : 1800秒 (30分钟)")
    print("  • 盘前数据（9:30前）   : 600秒 (10分钟)")
    print("  • 未来/错误日期       : 300秒 (5分钟)")

    print("\n预期效果:")
    print("  ✓ 历史数据分析：缓存命中率提升 ↑↑↑")
    print("  ✓ 盘中实时分析：数据时效性提升 ↑↑")
    print("  ✓ 盘后复盘分析：API调用次数减少 ↓↓")
    print("  ✓ 服务器负载降低，响应速度提升")


if __name__ == "__main__":
    try:
        # 运行逻辑测试
        logic_passed = test_get_cache_ttl_logic()

        # 验证代码修改
        code_passed = verify_code_changes()

        # 显示摘要
        show_summary()

        print("\n" + "=" * 70)

        if logic_passed and code_passed:
            print("✅ 第1项优化完成并验证通过！")
            print("=" * 70)
            print("\n📦 下一步：备份当前代码")
            print("   建议命令：")
            print("   git add api/services/market_analysis_service.py")
            print("   git commit -m 'feat: 实现差异化缓存TTL策略'")
            print("   git tag v1.0-cache-ttl-optimization")
            print("\n然后可以开始第2项优化：优化综合评分机制")
            sys.exit(0)
        else:
            print("❌ 验证未通过，请检查")
            print("=" * 70)
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
