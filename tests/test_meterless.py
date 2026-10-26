"""The Meterless Runtime provider contract (0.90.0): URL normalisation, the token, headers, status from /v1/models,
Auto Detect, receipts (the routed model) and the labelled direct-NVIDIA fallback. A local HTTP server stands in for
the runtime; no real network."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import httpx2
import openai
import pytest

import config
import llm_client
import meterless

TOKEN = "good-token"
MODELS = {"object": "list", "data": [{"id": "meterless/auto"}, {"id": "meterless/fast"}, {"id": "meterless/new-mode"},
                                     {"id": "nvidia/nemotron-3.5-lightning-30b-a3b"}]}


@pytest.fixture
def runtime():
    """A fake Meterless Runtime: /healthz always 200; /v1/models 401 without the right token; records headers."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen.append({k.lower(): v for k, v in self.headers.items()})
            if self.path == "/healthz":
                return self._send(200, {"status": "ok", "engine": "meterless"})
            if self.path == "/v1/models":
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    return self._send(401, {"error": {"code": "runtime_token_mismatch", "layer": "meterless-runtime"}})
                return self._send(200, MODELS)
            self._send(404, {})

        def _send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield SimpleNamespace(url=f"http://127.0.0.1:{server.server_port}", seen=seen)
    server.shutdown()


@pytest.mark.parametrize("pasted", ["127.0.0.1:8088", "http://127.0.0.1:8088", "http://127.0.0.1:8088/",
                                    "http://127.0.0.1:8088/v1", "http://127.0.0.1:8088/v1/",
                                    "http://127.0.0.1:8088/v1/chat/completions", "http://127.0.0.1:8088/v1/models",
                                    "http://127.0.0.1:8088/healthz", "  http://127.0.0.1:8088/v1/v1  "])
def test_any_pasted_url_becomes_host_v1_never_v1_v1(pasted):
    assert config.normalize_meterless_url(pasted) == "http://127.0.0.1:8088/v1"


def test_default_url_and_token_rules(tmp_path):
    assert config.normalize_meterless_url("") == config.METERLESS_DEFAULT_URL == "http://127.0.0.1:8088/v1"
    assert config.meterless_token("rt-local", tmp_path) is None                  # the placeholder is rejected
    assert config.meterless_token(" abc ", tmp_path) == "abc"
    assert config.meterless_token("", tmp_path) is None
    (tmp_path / "proxy-token").write_text("from-the-runtime\n")
    assert config.meterless_token("", tmp_path) == "from-the-runtime"         # <stateDir>/proxy-token


def test_wrong_token_is_unauthorized_not_offline(runtime):
    assert meterless.status(runtime.url, "wrong").state == "unauthorized"
    assert meterless.status(runtime.url, None).state == "unauthorized"
    assert runtime.seen[-1]["meterless-app"] == "runway"                          # on every request


def test_right_token_is_online_and_unknown_modes_are_kept(runtime):
    st = meterless.status(runtime.url + "/v1/chat/completions", TOKEN)
    assert st.state == "online" and st.base_url == runtime.url + "/v1"
    assert st.routing_modes == ["meterless/auto", "meterless/fast", "meterless/new-mode"]
    assert st.models == ["nvidia/nemotron-3.5-lightning-30b-a3b"]
    assert meterless.healthz(runtime.url)[0] == 200


def test_nothing_listening_is_offline():
    assert meterless.status("http://127.0.0.1:9", TOKEN, timeout=1).state == "offline"


def test_auto_detect_tries_the_contract_ports_and_saves_the_first_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(meterless, "SAVED", tmp_path / "rt.json")
    assert meterless.candidates()[:3] == ["http://127.0.0.1:8088/v1", "http://localhost:8088/v1",
                                          "http://[::1]:8088/v1"]
    assert {u.rsplit(":", 1)[1] for u in meterless.candidates()} == {"8088/v1", "8090/v1", "8787/v1", "11434/v1"}
    hit = "http://localhost:8787/v1"
    found = meterless.auto_detect(TOKEN, probe=lambda url, tok: meterless.Status(
        url, "unauthorized" if url == hit else "offline"))
    assert found.base_url == hit and json.loads((tmp_path / "rt.json").read_text())["base_url"] == hit
    assert meterless.auto_detect(TOKEN, probe=lambda u, t: meterless.Status(u, "offline")) is None


# --- llm_client on the Meterless provider ----------------------------------------------------------------------

REQ = httpx2.Request("POST", "http://127.0.0.1:8088/v1/chat/completions")
RECEIPT = {"schema": "meterless.compute_receipt.v1", "receipt_id": "rcpt_req_1", "routed_model": "nvidia/routed"}


class FakeClient:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def completion(text, receipt=None, model="nvidia/requested"):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text, reasoning_content=None),
                                                    finish_reason="stop")],
                           usage=None, model=model, model_extra={"meterless": receipt} if receipt else {})


def chunk(text=None, receipt=None):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text, reasoning_content=None),
                                                    finish_reason=None)] if text else [],
                           usage=None, model="nvidia/requested", model_extra={"meterless": receipt} if receipt else {})


@pytest.fixture
def on_meterless(monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", "meterless")
    monkeypatch.setattr(config, "NVIDIA_API_KEY", "direct-key")
    monkeypatch.setattr(config, "THINK_MODEL", "nvidia/think")
    monkeypatch.setattr(config, "NVIDIA_EXPLAIN_MODEL", "nvidia/super")
    monkeypatch.setattr(llm_client, "sleep", lambda s: None)


def test_meterless_call_sends_scope_long_timeout_room_and_records_the_routed_model(on_meterless):
    client = FakeClient(completion("OK", RECEIPT))
    r = llm_client.chat([{"role": "user", "content": "x"}], model="nvidia/requested", client=client, timeout=20,
                        max_tokens=20)
    kw = client.calls[0]
    assert kw["extra_headers"] == {"meterless-scope": "user"}
    assert kw["timeout"] == 180 and kw["max_tokens"] == 400                       # contract timeout; room to think
    assert (r.provider, r.routed_model, r.receipt_id, r.fallback) == ("meterless", "nvidia/routed", "rcpt_req_1", False)
    assert r.call_record("plan")["routed_model"] == "nvidia/routed"


def test_meterless_stream_takes_the_receipt_from_the_last_chunk(on_meterless):
    client = FakeClient(iter([chunk("O"), chunk("K"), chunk(receipt=RECEIPT)]))
    s = llm_client.stream_chat([{"role": "user", "content": "x"}], thinking=False, client=client)
    assert "".join(c for k, c in s if k == "text") == "OK"
    assert (s.result.routed_model, s.result.receipt_id, s.result.provider) == ("nvidia/routed", "rcpt_req_1",
                                                                               "meterless")


def _down():
    return openai.APIConnectionError(request=REQ)


def _unauthorized():
    return openai.AuthenticationError("unauthorized", response=httpx2.Response(401, request=REQ),
                                      body={"error": {"code": "runtime_token_mismatch", "layer": "meterless-runtime"}})


def _provider_502():
    return openai.InternalServerError("bad gateway", response=httpx2.Response(502, request=REQ),
                                      body={"error": {"code": "provider_error"}})


@pytest.mark.parametrize("failure", [_down, _unauthorized])
def test_direct_nvidia_only_when_the_runtime_is_down_and_labelled(on_meterless, monkeypatch, failure):
    met, direct = FakeClient(failure(), failure(), failure()), FakeClient(completion("OK", model="nvidia/super"))
    monkeypatch.setattr(llm_client, "get_client", lambda p=None: met if p == "meterless" else direct)
    r = llm_client.chat([{"role": "user", "content": "x"}], thinking=True)       # default: the Think harder model
    assert met.calls[0]["model"] == "nvidia/think"
    assert direct.calls[0]["model"] == "nvidia/super" and "extra_headers" not in direct.calls[0]
    assert (r.provider, r.fallback, r.routed_model) == ("nvidia", True, "nvidia/super")


def test_a_model_error_behind_the_runtime_does_not_go_direct(on_meterless, monkeypatch):
    met, direct = FakeClient(_provider_502(), _provider_502(), _provider_502()), FakeClient()
    monkeypatch.setattr(llm_client, "get_client", lambda p=None: met if p == "meterless" else direct)
    with pytest.raises(openai.InternalServerError):
        llm_client.chat([{"role": "user", "content": "x"}], model="nvidia/requested")
    assert not direct.calls


def test_no_direct_fallback_without_an_nvidia_key(on_meterless, monkeypatch):
    monkeypatch.setattr(config, "NVIDIA_API_KEY", None)
    assert llm_client.providers() == ["meterless"]
    monkeypatch.setattr(config, "NVIDIA_API_KEY", "k")
    assert llm_client.providers() == ["meterless", "nvidia"]


# --- the per-question trace -----------------------------------------------------------------------------------

def test_every_live_answer_writes_a_trace_with_plan_queries_model_calls_and_checks(tmp_path, monkeypatch):
    import agent
    import engine
    import normalize
    from test_agent import FLIGHT_PLAN, GOOD_FLIGHT, FakeLLM
    monkeypatch.setattr(config, "ANSWER_CACHE_DIR", tmp_path / "answers")
    ds = normalize.load()
    a = agent.ask("Can I afford a $400 flight home for Thanksgiving if I book it Nov 10?", engine.Scenario(), ds=ds,
                  mode="live", llm=FakeLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT]), typing_s=0)
    lines = (config.LOGS_DIR / "traces.jsonl").read_text(encoding="utf-8").splitlines()
    t = json.loads(lines[-1])
    assert t["trace"] == "runway.trace.v1" and t["question"] == a.question
    assert t["plan"]["calls"][0]["tool"] == "can_afford"
    assert t["queries"] and all(q["query"] and q["rows"] >= 0 for q in t["queries"])
    assert [c["role"] for c in t["model_calls"]] == ["plan", "explain"]
    assert t["check"]["ok"] is True and t["verdict"] == "yes_if" and t["timings"]["total_s"] >= 0


def test_her_own_data_is_never_traced(tmp_path, monkeypatch):
    import agent
    import engine
    import normalize
    from test_agent import FLIGHT_PLAN, GOOD_FLIGHT, FakeLLM
    agent.ask("Can I afford a $400 flight home?", engine.Scenario(), ds=normalize.load(), mode="live",
              llm=FakeLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT]), typing_s=0, private=True)
    assert not (config.LOGS_DIR / "traces.jsonl").exists()


def test_handled_by_names_the_routed_model_provider_and_receipt():
    import agent
    rec = {"provider": "meterless", "routed_model": "nvidia/nemotron-3-ultra-550b-a55b", "receipt_id": "rcpt_1"}
    assert agent.handled_by(rec) == ("Nemotron Ultra (nvidia/nemotron-3-ultra-550b-a55b) through Meterless "
                                     "Nightshift, receipt rcpt_1")
    assert "fallback" in agent.handled_by({**rec, "provider": "nvidia", "fallback": True, "receipt_id": None})


def test_her_own_data_answers_are_never_saved(tmp_path, monkeypatch):
    import agent
    import engine
    import normalize
    from test_agent import FLIGHT_PLAN, GOOD_FLIGHT, FakeLLM
    monkeypatch.setattr(config, "ANSWER_CACHE_DIR", tmp_path / "answers")
    agent.ask("Can I afford a $400 flight home?", engine.Scenario(), ds=normalize.load(), mode="live",
              llm=FakeLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT]), typing_s=0, private=True)
    assert not (tmp_path / "answers").exists() or not any((tmp_path / "answers").iterdir())
