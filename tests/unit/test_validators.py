"""Tests for tradingagents/llm_clients/validators.py."""

import pytest
from tradingagents.llm_clients.validators import validate_model


class TestValidateModel:
    def test_ollama_accepts_anything(self):
        assert validate_model("ollama", "any-model") is True
        assert validate_model("ollama", "") is True

    def test_openrouter_accepts_anything(self):
        assert validate_model("openrouter", "any-model") is True

    def test_openai_valid_model(self):
        assert validate_model("openai", "gpt-4o") is True

    def test_openai_invalid_model(self):
        assert validate_model("openai", "nonexistent-model-xyz") is False

    def test_anthropic_valid_model(self):
        assert validate_model("anthropic", "claude-sonnet-4-20250514") is True

    def test_anthropic_invalid_model(self):
        assert validate_model("anthropic", "nonexistent-model-xyz") is False

    def test_deepseek_valid_model(self):
        assert validate_model("deepseek", "deepseek-chat") is True

    def test_unknown_provider_accepts_anything(self):
        """Unknown providers should be permissive."""
        assert validate_model("unknown-provider", "any-model") is True

    def test_case_insensitive_provider(self):
        assert validate_model("OpenAI", "gpt-4o") is True
        assert validate_model("DEEPSEEK", "deepseek-chat") is True
