"""Shared test setup: no test may call the real NVIDIA endpoint in the background (the check-in greeting)."""
import pytest

import config


@pytest.fixture(autouse=True)
def _no_ai_greeting(monkeypatch):
    monkeypatch.setattr(config, "AI_GREETING", False)
