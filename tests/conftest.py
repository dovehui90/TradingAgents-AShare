"""Shared pytest fixtures for TradingAgents-AShare."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def app():
    """FastAPI app instance (session-scoped, created once)."""
    from api.main import app as _app
    return _app


@pytest.fixture
def client(app):
    """TestClient bound to the FastAPI app."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
