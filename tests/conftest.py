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
def _memory_to_tmp(monkeypatch, tmp_path):
    """Runway's H-MEM memory lives in a temp folder per test, never the real .cache/memory/."""
    import runway_memory
    monkeypatch.setattr(runway_memory, "DIR", tmp_path / "memory")
    try:
        from ui import memory
        memory._memory.clear()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _traces_to_tmp(monkeypatch, tmp_path):
    """Per-question traces go to a temp folder, never the real logs/."""
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")


@pytest.fixture(autouse=True)
def _not_sample_mode(monkeypatch):
    """Tests set their own data and answer modes; sample mode (on in a fresh clone with no .env) would override them.
    tests/test_sample_mode.py checks sample mode itself, in a subprocess."""
    if config.SAMPLE_MODE:                                        # a fresh clone: restore the non-sample defaults
        monkeypatch.setattr(config, "DATA_BACKEND", (config.get("DATA_BACKEND") or "local").lower())
        monkeypatch.setattr(config, "ANSWER_MODE", (config.get("ANSWER_MODE") or "cached").lower())
    monkeypatch.setattr(config, "SAMPLE_MODE", False)


@pytest.fixture(autouse=True)
def _meal_plan_to_tmp(monkeypatch, tmp_path):
    """The meal plan settings and log live in a temp folder per test, never the real .cache/ or user_data/."""
    import mealplan
    monkeypatch.setattr(mealplan, "FOLDER", tmp_path / "mealplan")
