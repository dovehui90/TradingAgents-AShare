"""主线 A：每日复盘图装配

优化版本：5个分析师并行执行，大幅提升效率。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .config import make_llm
from .roles import ROLES
from .state import DuanxianReviewState
from .synthesizer import create_review_judge

_JUDGE = "复盘裁判"
_JOIN = "分析师汇聚"  # 汇聚节点，等待所有分析师完成


def _join_analysts(state: dict) -> dict:
    """汇聚节点：等待所有分析师完成，不做任何处理。

    LangGraph 的 fan-out/fan-in 模式需要一个汇聚节点来
    确保所有并行节点都完成后再继续。
    """
    return {}


def build_review_graph():
    """构建复盘图。

    优化后的执行流程：
    1. START → 5个分析师（并行执行）
    2. 汇聚节点 → 等待所有分析师完成
    3. 复盘裁判 → 综合所有报告
    4. END
    """
    quick = make_llm(deep=False)   # 五个分析师
    deep = make_llm(deep=True)     # 复盘裁判

    g = StateGraph(DuanxianReviewState)

    # 添加所有分析师节点
    for role in ROLES:
        g.add_node(role.title, role.factory(quick))

    # 添加汇聚节点
    g.add_node(_JOIN, _join_analysts)

    # 添加裁判节点
    g.add_node(_JUDGE, create_review_judge(deep))

    # Fan-out: START → 所有分析师（并行）
    for role in ROLES:
        g.add_edge(START, role.title)

    # Fan-in: 所有分析师 → 汇聚节点
    for role in ROLES:
        g.add_edge(role.title, _JOIN)

    # 汇聚节点 → 裁判
    g.add_edge(_JOIN, _JUDGE)

    # 裁判 → END
    g.add_edge(_JUDGE, END)

    return g.compile()
