"""
综合评分优化方案 - 组合规则引擎

当前问题：
1. 简单线性加权（conf += 2, conf += 3）
2. 忽略信号协同效应
3. 阈值硬编码（如 inst_net > 0, tail_vol_ratio > 10）

优化方案：
1. 定义信号组合规则库
2. 识别高置信度组合（如"三重共振"）
3. 动态调整评分权重
"""

# ========== 信号组合规则库 ==========

SIGNAL_COMBINATION_RULES = {
    # ===== 高置信度看多组合 =====
    'triple_bullish_resonance': {
        'name': '三重共振看多',
        'conditions': [
            ('inst_net', '>', 0),           # 机构净买入
            ('split_net', '>', 0),          # 拆单偏买
            ('tail_pct', '>', 0.3),         # 尾盘上涨
            ('split_ratio', '>', 1.0),      # 拆单占比显著
        ],
        'score': 9,  # 协同效应：不是3+2+2=7，而是9
        'confidence': 95,
        'description': '机构明买、暗盘净买、尾盘拉升，三维度共振，主力做多意图明确',
    },

    'reverse_accumulation': {
        'name': '逆势吸筹（高级）',
        'conditions': [
            ('inst_net', '>', 5000),        # 大额机构净买（>5000万）
            ('full_pct', '<', -2.0),        # 股价跌幅>2%
            ('split_net', '>', 0),          # 拆单也偏买
            ('tail_vol_ratio', '>', 12),    # 尾盘放量
        ],
        'score': 8,
        'confidence': 90,
        'description': '价跌+大额机构买入+暗盘吸筹+尾盘放量，典型的压价建仓',
    },

    'dark_light_consensus': {
        'name': '明暗一致强势',
        'conditions': [
            ('inst_net', '>', 0),
            ('split_net', '>', 0),
            ('full_pct', '>', 0),           # 价格上涨
            ('inst_net', '>', 3000),        # 机构买入规模>3000万
        ],
        'score': 7,
        'confidence': 85,
        'description': '价涨+机构买+暗盘买，明暗一致且趋势配合',
    },

    # ===== 高置信度看空组合 =====
    'triple_bearish_resonance': {
        'name': '三重共振看空',
        'conditions': [
            ('inst_net', '<', 0),
            ('split_net', '<', 0),
            ('tail_pct', '<', -0.3),
        ],
        'score': -9,
        'confidence': 95,
        'description': '机构净卖、暗盘净卖、尾盘跳水，三维度看空',
    },

    'pump_and_dump': {
        'name': '拉高出货',
        'conditions': [
            ('full_pct', '>', 2.0),         # 涨幅>2%
            ('inst_net', '<', -3000),       # 机构大额净卖
            ('split_net', '<', 0),          # 拆单偏卖
            ('tail_pct', '<', 0),           # 尾盘回落
        ],
        'score': -8,
        'confidence': 90,
        'description': '价涨+机构卖出+暗盘派发+尾盘回落，拉高出货特征',
    },

    # ===== 警示组合 =====
    'dark_divergence_trap': {
        'name': '明买暗卖（对倒诱多）',
        'conditions': [
            ('inst_net', '>', 0),           # 明面买入
            ('split_net', '<', 0),          # 暗盘卖出
            ('split_ratio', '>', 2.0),      # 拆单占比>2%（显著）
            ('full_pct', '>', 0),           # 价格上涨
        ],
        'score': -6,
        'confidence': 80,
        'description': '明面买入制造人气，暗盘实际派发，警惕对倒诱多',
    },

    'fake_weakness': {
        'name': '明卖暗买（暗吸）',
        'conditions': [
            ('inst_net', '<', 0),           # 明面卖出
            ('split_net', '>', 0),          # 暗盘买入
            ('split_ratio', '>', 2.0),
            ('full_pct', '<', -1.0),        # 价格下跌
        ],
        'score': 5,
        'confidence': 75,
        'description': '明面打压制造恐慌，暗盘实际吸筹，可能低位建仓',
    },

    # ===== 中性/矛盾组合 =====
    'mixed_signals_weak': {
        'name': '信号混杂（弱势）',
        'conditions': [
            ('inst_net', '>', 0),
            ('tail_pct', '<', -0.5),        # 尾盘跳水
            ('tail_vol_ratio', '>', 12),    # 且尾盘放量
        ],
        'score': -2,
        'confidence': 50,
        'description': '机构买入但尾盘放量跳水，多头力量不足',
    },

    'tail_manipulation': {
        'name': '尾盘砸盘',
        'conditions': [
            ('tail_pct', '<', -1.0),        # 尾盘大幅下跌
            ('tail_vol_ratio', '>', 15),    # 尾盘放量
            ('full_pct', '>', 0),           # 但全日仍上涨
        ],
        'score': -3,
        'confidence': 60,
        'description': '全日上涨但尾盘砸盘，可能洗盘或主力撤退',
    },

    # ===== 量价背离组合 =====
    'volume_price_divergence_bullish': {
        'name': '放量不涨（警惕）',
        'conditions': [
            ('inst_net', '>', 0),
            ('full_pct', '<', 0.5),         # 涨幅很小
            ('tail_vol_ratio', '>', 12),    # 但放量
        ],
        'score': -1,
        'confidence': 55,
        'description': '放量但价格不涨，可能遇阻力或主力派发',
    },
}


# ========== 评分引擎函数 ==========

def evaluate_signal_combinations(market_data: dict) -> dict:
    """
    基于组合规则的评分引擎

    Args:
        market_data: 包含各维度数据的字典
            - inst_net: 机构净流入（万元）
            - split_net: 拆单净手数
            - split_ratio: 拆单占比（%）
            - full_pct: 全日涨跌幅（%）
            - tail_pct: 尾盘涨跌幅（%）
            - tail_vol_ratio: 尾盘成交占比（%）

    Returns:
        {
            'total_score': int,
            'triggered_rules': list,
            'max_confidence': int,
            'verdict': str,
            'warning': str or None,
        }
    """
    triggered = []
    total_score = 0
    max_confidence = 0
    warnings = []

    # 遍历所有规则
    for rule_id, rule in SIGNAL_COMBINATION_RULES.items():
        if _check_rule_conditions(market_data, rule['conditions']):
            triggered.append({
                'rule_id': rule_id,
                'name': rule['name'],
                'score': rule['score'],
                'confidence': rule['confidence'],
                'description': rule['description'],
            })
            total_score += rule['score']
            max_confidence = max(max_confidence, rule['confidence'])

            # 收集警告信号
            if '警惕' in rule['name'] or '对倒' in rule['name']:
                warnings.append(rule['name'])

    # 如果没有触发任何组合规则，使用基础线性评分
    if not triggered:
        total_score, base_signals = _fallback_linear_score(market_data)
        max_confidence = 50  # 基础评分置信度较低
        triggered = [{
            'rule_id': 'fallback',
            'name': '基础评分',
            'score': total_score,
            'confidence': max_confidence,
            'description': f"触发信号: {', '.join(base_signals)}",
        }]

    # 判定结论
    verdict = _score_to_verdict(total_score)

    return {
        'total_score': total_score,
        'triggered_rules': triggered,
        'max_confidence': max_confidence,
        'verdict': verdict,
        'warning': warnings[0] if warnings else None,
    }


def _check_rule_conditions(data: dict, conditions: list) -> bool:
    """检查规则条件是否全部满足"""
    for field, operator, threshold in conditions:
        value = data.get(field, 0)

        if operator == '>':
            if not (value > threshold):
                return False
        elif operator == '<':
            if not (value < threshold):
                return False
        elif operator == '>=':
            if not (value >= threshold):
                return False
        elif operator == '<=':
            if not (value <= threshold):
                return False
        elif operator == '==':
            if not (value == threshold):
                return False

    return True


def _fallback_linear_score(data: dict) -> tuple:
    """回退到基础线性评分（当没有触发组合规则时）"""
    score = 0
    signals = []

    inst_net = data.get('inst_net', 0)
    full_pct = data.get('full_pct', 0)
    tail_pct = data.get('tail_pct', 0)
    tail_vol_ratio = data.get('tail_vol_ratio', 0)
    split_net = data.get('split_net', 0)

    # 机构资金
    if inst_net > 0 and full_pct < 0:
        signals.append('机构逆势买')
        score += 3
    elif inst_net > 0:
        signals.append('机构顺势买')
        score += 2
    elif inst_net < 0 and full_pct > 0:
        signals.append('机构逆势卖')
        score -= 3
    elif inst_net < 0:
        signals.append('机构顺势卖')
        score -= 2

    # 尾盘
    if tail_pct > 0 and tail_vol_ratio > 10:
        signals.append('尾盘放量买')
        score += 2
    elif tail_pct < -0.3 and tail_vol_ratio > 10:
        signals.append('尾盘放量卖')
        score -= 2

    # 拆单
    if split_net > 0:
        signals.append('拆单偏买')
        score += 1
    elif split_net < 0:
        signals.append('拆单偏卖')
        score -= 1

    return score, signals


def _score_to_verdict(score: int) -> str:
    """评分转为结论"""
    if score >= 8: return '强烈偏多'
    elif score >= 5: return '偏多'
    elif score >= 2: return '中性偏多'
    elif score >= -1: return '中性/观望'
    elif score >= -4: return '中性偏空'
    elif score >= -7: return '偏空'
    else: return '强烈偏空'


# ========== 使用示例 ==========

if __name__ == "__main__":
    # 测试案例1：三重共振看多
    test_data_1 = {
        'inst_net': 8000,      # 机构净买8000万
        'split_net': 5000,     # 拆单净买5000手
        'split_ratio': 2.5,    # 拆单占比2.5%
        'full_pct': 1.2,       # 全日涨1.2%
        'tail_pct': 0.5,       # 尾盘涨0.5%
        'tail_vol_ratio': 15,  # 尾盘占比15%
    }

    result = evaluate_signal_combinations(test_data_1)
    print("测试案例1：三重共振看多")
    print(f"  总分: {result['total_score']}")
    print(f"  结论: {result['verdict']}")
    print(f"  置信度: {result['max_confidence']}%")
    print(f"  触发规则: {result['triggered_rules'][0]['name']}")
    print()

    # 测试案例2：对倒诱多
    test_data_2 = {
        'inst_net': 3000,      # 机构净买3000万
        'split_net': -4000,    # 但拆单净卖4000手
        'split_ratio': 3.0,
        'full_pct': 2.5,       # 价格上涨
        'tail_pct': 1.0,
        'tail_vol_ratio': 12,
    }

    result = evaluate_signal_combinations(test_data_2)
    print("测试案例2：对倒诱多")
    print(f"  总分: {result['total_score']}")
    print(f"  结论: {result['verdict']}")
    print(f"  警告: {result['warning']}")
    print()
