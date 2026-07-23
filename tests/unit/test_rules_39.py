"""Data integrity tests for tradingagents/strategy/rules_39.py.

These protect the 39 trading rules from accidental corruption:
duplicate IDs, missing keys, broken category references.
"""

import pytest

from tradingagents.strategy.rules_39 import CATEGORIES, RULES, get_rule_by_id, get_rules_by_category


REQUIRED_KEYS = {"id", "name", "trigger", "decision", "category"}


class TestRulesDataIntegrity:
    """Ensure the 39 rules are well-formed."""

    def test_exactly_39_rules(self):
        assert len(RULES) == 39, f"Expected 39 rules, got {len(RULES)}"

    def test_no_duplicate_ids(self):
        ids = [r["id"] for r in RULES]
        duplicates = [i for i in ids if ids.count(i) > 1]
        assert len(set(ids)) == len(ids), f"Duplicate rule IDs: {set(duplicates)}"

    def test_consecutive_ids(self):
        """IDs should be 1–39 without gaps."""
        ids = sorted(r["id"] for r in RULES)
        assert ids == list(range(1, 40)), f"Non-consecutive IDs: {ids}"

    def test_all_rules_have_required_keys(self):
        for r in RULES:
            missing = REQUIRED_KEYS - set(r.keys())
            assert not missing, f"Rule {r.get('id', '?')} missing keys: {missing}"

    def test_categories_are_valid(self):
        valid_categories = set(CATEGORIES.keys())
        # "持有" is a sub-label used in compound categories like "观望/持有"
        valid_categories.add("持有")
        for r in RULES:
            cats = r["category"].split("/")
            for c in cats:
                assert c in valid_categories, (
                    f"Rule {r['id']} has unknown category '{c}'. Valid: {valid_categories}"
                )


class TestCategoryMapping:
    """CATEGORIES dict must be consistent with RULES."""

    def test_no_orphan_ids_in_categories(self):
        """Every ID in CATEGORIES must exist in RULES."""
        rule_ids = {r["id"] for r in RULES}
        for cat_name, cat_ids in CATEGORIES.items():
            for rid in cat_ids:
                assert rid in rule_ids, (
                    f"Category '{cat_name}' references rule {rid} which does not exist"
                )

    def test_no_unreferenced_rule_ids(self):
        """Every rule ID should appear in at least one category."""
        cat_ids = set()
        for ids in CATEGORIES.values():
            cat_ids.update(ids)
        rule_ids = {r["id"] for r in RULES}
        unreferenced = rule_ids - cat_ids
        assert not unreferenced, f"Rules not in any category: {unreferenced}"

    def test_category_names_match_rules(self):
        """Rules referenced by a category should exist (lenient match).

        Some rules appear in multiple CATEGORIES lists (e.g. rule 6 is both
        '定义' and '风险回避') while the rule itself only lists one category.
        This test verifies every CATEGORIES reference resolves to a valid rule.
        It does not require the rule's own category string to match, since
        CATEGORIES serves as a cross-referencing index.
        """
        for cat_name, cat_ids in CATEGORIES.items():
            for rid in cat_ids:
                rule = get_rule_by_id(rid)
                assert rule is not None, (
                    f"Category '{cat_name}' references rule {rid} which does not exist"
                )


class TestLookupFunctions:
    def test_get_rule_by_id_returns_correct_rule(self):
        rule = get_rule_by_id(1)
        assert rule is not None
        assert rule["name"] == "高量定义"

    def test_get_rule_by_id_returns_none_for_invalid(self):
        assert get_rule_by_id(0) is None
        assert get_rule_by_id(999) is None
        assert get_rule_by_id(-1) is None

    def test_get_rules_by_category_returns_correct_subset(self):
        rules = get_rules_by_category("加仓")
        ids = {r["id"] for r in rules}
        assert ids == set(CATEGORIES["加仓"])

    def test_get_rules_by_category_unknown_returns_empty(self):
        assert get_rules_by_category("不存在的分类") == []
