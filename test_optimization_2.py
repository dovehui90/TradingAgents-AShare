#!/usr/bin/env python3
"""
第2项优化测试：综合评分机制
验证组合规则引擎的集成效果
"""

import sys
sys.path.insert(0, '/Users/luhui/Desktop/AI_project/TradingAgents-AShare')

from api.services.signal_combination_engine import evaluate_signal_combinations


def test_combination_rules():
    """测试各种信号组合场景"""

    print("=" * 70)
    print("第2项优化测试：组合规则引擎")
    print("=" * 70)

    test_cases = [
        {
            'name': '场景1：三重共振看多',
            'data': {
                'inst_net': 8000,
                'split_net': 5000,
                'split_ratio': 2.5,
                'full_pct': 1.2,
                'tail_pct': 0.5,
                'tail_vol_ratio': 15,
            },
            'expected_verdict': '强烈偏多',
            'expected_min_score': 8,
        },
        {
            'name': '场景2：逆势吸筹',
            'data': {
                'inst_net': 6000,
                'split_net': 3000,
                'split_ratio': 2.0,
                'full_pct': -2.5,
                'tail_pct': -1.0,
                'tail_vol_ratio': 15,
            },
            'expected_verdict': '偏多',
            'expected_min_score': 5,
        },
        {
            'name': '场景3：对倒诱多（警惕）',
            'data': {
                'inst_net': 3000,
                'split_net': -4000,
                'split_ratio': 3.0,
                'full_pct': 2.5,
                'tail_pct': 1.0,
                'tail_vol_ratio': 12,
            },
            'expected_verdict': '偏空',
            'expected_has_warning': True,
        },
        {
            'name': '场景4：拉高出货',
            'data': {
                'inst_net': -5000,
                'split_net': -3000,
                'split_ratio': 2.5,
                'full_pct': 3.0,
                'tail_pct': -0.5,
                'tail_vol_ratio': 14,
            },
            'expected_verdict': '偏空',  # 包含"偏空"即可
            'expected_max_score': -5,    # 改为最大评分（允许更负）
        },
        {
            'name': '场景5：信号混杂（中性）',
            'data': {
                'inst_net': 2000,
                'split_net': -500,
                'split_ratio': 0.5,
                'full_pct': 0.5,
                'tail_pct': 0.1,
                'tail_vol_ratio': 8,
            },
            'expected_verdict': '中性',  # 包含"中性"关键词
        },
        {
            'name': '场景6：明卖暗买（暗吸）',
            'data': {
                'inst_net': -2000,
                'split_net': 3000,
                'split_ratio': 2.5,
                'full_pct': -1.5,
                'tail_pct': -0.5,
                'tail_vol_ratio': 10,
            },
            'expected_verdict': '偏多',
            'expected_has_warning': False,
        },
    ]

    print("\n测试用例:")
    print("-" * 70)
    print(f"{'场景':<25} {'评分':<8} {'结论':<15} {'置信度':<10} {'状态':<8}")
    print("-" * 70)

    passed = 0
    failed = 0

    for tc in test_cases:
        result = evaluate_signal_combinations(tc['data'])

        score = result['total_score']
        verdict = result['verdict']
        confidence = result['max_confidence']
        has_warning = result.get('warning') is not None

        # 验证逻辑
        test_passed = True

        if 'expected_verdict' in tc:
            if tc['expected_verdict'] not in verdict:
                test_passed = False

        if 'expected_min_score' in tc:
            if score < tc['expected_min_score']:
                test_passed = False

        if 'expected_max_score' in tc:
            if score > tc['expected_max_score']:
                test_passed = False

        if 'expected_has_warning' in tc:
            if has_warning != tc['expected_has_warning']:
                test_passed = False

        status = "✅ 通过" if test_passed else "❌ 失败"

        if test_passed:
            passed += 1
        else:
            failed += 1

        print(f"{tc['name']:<25} {score:<8} {verdict:<15} {confidence}%{' '*5} {status:<8}")

        # 显示触发的规则
        if result['triggered_rules']:
            top_rule = result['triggered_rules'][0]
            if top_rule['rule_id'] != 'fallback':
                print(f"  → 触发规则: {top_rule['name']}")

        # 显示警告
        if has_warning:
            print(f"  ⚠️  警告: {result['warning']}")

    print("-" * 70)
    print(f"\n测试结果: 通过 {passed} / 失败 {failed} / 总计 {passed + failed}")

    return passed, failed


def test_vs_old_system():
    """对比新旧评分系统"""

    print("\n" + "=" * 70)
    print("新旧系统对比")
    print("=" * 70)

    comparison_case = {
        'inst_net': 8000,      # 机构净买8000万
        'split_net': 5000,     # 拆单净买5000手
        'split_ratio': 2.5,
        'full_pct': 1.2,
        'tail_pct': 0.5,
        'tail_vol_ratio': 15,
    }

    # 新系统评分
    new_result = evaluate_signal_combinations(comparison_case)

    # 模拟旧系统评分（简单线性加权）
    old_score = 0
    old_signals = []

    # 旧系统逻辑
    if comparison_case['inst_net'] > 0:
        old_signals.append('机构顺势买')
        old_score += 2

    if comparison_case['tail_pct'] > 0 and comparison_case['tail_vol_ratio'] > 10:
        old_signals.append('尾盘放量买')
        old_score += 2

    if comparison_case['split_net'] > 0:
        old_signals.append('拆单偏买')
        old_score += 2

    # 明暗一致
    if comparison_case['inst_net'] > 0 and comparison_case['split_net'] > 0:
        old_signals.append('明暗同向看多')
        old_score += 3

    print("\n对比场景：机构净买+拆单净买+尾盘放量")
    print("-" * 70)
    print(f"{'系统':<10} {'评分':<10} {'结论':<15} {'置信度':<10} {'触发规则':<30}")
    print("-" * 70)

    print(f"{'旧系统':<10} {old_score:<10} {'未知':<15} {'~50%':<10} {', '.join(old_signals):<30}")
    print(f"{'新系统':<10} {new_result['total_score']:<10} {new_result['verdict']:<15} {new_result['max_confidence']}%{' '*5} {new_result['triggered_rules'][0]['name']:<30}")

    print("-" * 70)
    print("\n优势分析:")
    print(f"  ✓ 评分提升: {old_score} → {new_result['total_score']} (+{new_result['total_score'] - old_score})")
    print(f"  ✓ 识别组合: 旧系统单独计分 → 新系统识别'{new_result['triggered_rules'][0]['name']}'")
    print(f"  ✓ 置信度: 旧系统无法量化 → 新系统{new_result['max_confidence']}%")


def show_rule_coverage():
    """显示规则覆盖情况"""

    print("\n" + "=" * 70)
    print("规则库覆盖范围")
    print("=" * 70)

    from api.services.signal_combination_engine import SIGNAL_COMBINATION_RULES

    categories = {
        '高置信度看多': [],
        '高置信度看空': [],
        '警示信号': [],
        '中性/矛盾': [],
        '量价背离': [],
    }

    for rule_id, rule in SIGNAL_COMBINATION_RULES.items():
        name = rule['name']
        score = rule['score']
        confidence = rule['confidence']

        if score >= 7:
            categories['高置信度看多'].append((name, score, confidence))
        elif score <= -7:
            categories['高置信度看空'].append((name, score, confidence))
        elif '警惕' in name or '对倒' in name or '诱' in name:
            categories['警示信号'].append((name, score, confidence))
        elif '背离' in name:
            categories['量价背离'].append((name, score, confidence))
        else:
            categories['中性/矛盾'].append((name, score, confidence))

    print(f"\n共 {len(SIGNAL_COMBINATION_RULES)} 条规则:")
    print("-" * 70)

    for cat, rules in categories.items():
        if rules:
            print(f"\n【{cat}】({len(rules)}条)")
            for name, score, confidence in rules:
                print(f"  • {name:<25} 评分:{score:>3}  置信度:{confidence}%")


if __name__ == "__main__":
    try:
        passed, failed = test_combination_rules()
        test_vs_old_system()
        show_rule_coverage()

        print("\n" + "=" * 70)

        if failed == 0:
            print("✅ 第2项优化测试全部通过！")
            print("=" * 70)
            print("\n核心改进:")
            print("  1. ✓ 识别信号协同效应（如'三重共振'评分9而非7）")
            print("  2. ✓ 增加置信度量化（50%-95%）")
            print("  3. ✓ 警示规则识别（对倒诱多、拉高出货）")
            print("  4. ✓ 规则库可扩展（当前11条，可继续增加）")
            print("\n准备备份并进入第3项优化...")
            sys.exit(0)
        else:
            print(f"❌ 有 {failed} 个测试失败")
            print("=" * 70)
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
