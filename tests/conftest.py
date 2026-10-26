"""Shared test setup: no test may call the real NVIDIA endpoint in the background (the check-in greeting), the
web search, or write the real web-search cache."""
import pytest

import config


@pytest.fixture(autouse=True)
def _no_ai_greeting(monkeypatch):
    monkeypatch.setattr(config, "AI_GREETING", False)


@pytest.fixture(autouse=True)
def _no_real_web_cache(monkeypatch, tmp_path):
    """No test may write the app's real web-search cache (.cache/websearch/): a fake result once ended up on screen."""
    import websearch
    monkeypatch.setattr(websearch, "CACHE", tmp_path / "websearch-cache.json")
    monkeypatch.setattr(websearch, "_post", lambda *a, **k: (_ for _ in ()).throw(OSError("no network in tests")))
