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


@pytest.fixture(autouse=True)
def _no_real_meterless(monkeypatch):
    """No test may reach the real Meterless Runtime (Nightshift): no runtime token, and no shared clients. Tests
    that want a provider set it on purpose."""
    import llm_client
    monkeypatch.setattr(config, "METERLESS_RUNTIME_TOKEN", None)
    monkeypatch.setattr(config, "METERLESS_BASE_URL", "http://127.0.0.1:9/v1")       # nothing listens there
    monkeypatch.setattr(llm_client, "_clients", {})


@pytest.fixture(autouse=True)
def _traces_to_tmp(monkeypatch, tmp_path):
    """Per-question traces go to a temp folder, never the real logs/."""
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
