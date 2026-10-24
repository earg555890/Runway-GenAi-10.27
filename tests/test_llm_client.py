"""llm_client with a fake OpenAI client. No real API calls."""
from types import SimpleNamespace

import httpx2
import openai
import pytest

import llm_client

MODEL = "test-model"
REQUEST = httpx2.Request("POST", "https://example.invalid/v1/chat/completions")


def server_error(status=500):
    return openai.InternalServerError("server error", response=httpx2.Response(status, request=REQUEST), body=None)


def bad_request():
    return openai.BadRequestError("bad request", response=httpx2.Response(400, request=REQUEST), body=None)


def timeout_error():
    return openai.APITimeoutError(request=REQUEST)


def completion(content, reasoning=None, prompt_tokens=10, completion_tokens=5):
    message = SimpleNamespace(content=content, reasoning_content=reasoning)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def chunk(content=None, reasoning=None, usage=None):
    delta = SimpleNamespace(content=content, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)


class FakeClient:
    """Mimics client.chat.completions.create. Each outcome is returned, or raised if it is an exception."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    waits = []
    monkeypatch.setattr(llm_client, "sleep", waits.append)
    return waits


# retries and timeouts ----------------------------------------------------------

def test_retries_on_500_then_succeeds(no_real_sleep):
    client = FakeClient(server_error(500), completion("hello"))
    result = llm_client.chat([{"role": "user", "content": "hi"}], model=MODEL, client=client)
    assert result.text == "hello"
    assert result.retries == 1
    assert len(client.calls) == 2
    assert no_real_sleep == [2.0]


def test_gives_up_after_two_retries_with_exponential_backoff(no_real_sleep):
    client = FakeClient(server_error(502), server_error(503), server_error(500))
    with pytest.raises(openai.InternalServerError):
        llm_client.chat([{"role": "user", "content": "hi"}], model=MODEL, client=client)
    assert len(client.calls) == 3
    assert no_real_sleep == [2.0, 4.0]


def test_retries_on_timeout_then_succeeds(no_real_sleep):
    client = FakeClient(timeout_error(), timeout_error(), completion("late but here"))
    result = llm_client.chat([{"role": "user", "content": "hi"}], model=MODEL, client=client)
    assert result.text == "late but here"
    assert result.retries == 2


def test_timeout_raised_after_retries_exhausted():
    client = FakeClient(timeout_error(), timeout_error(), timeout_error())
    with pytest.raises(openai.APITimeoutError):
        llm_client.chat([{"role": "user", "content": "hi"}], model=MODEL, client=client)
    assert len(client.calls) == 3


def test_timeout_is_passed_per_call():
    client = FakeClient(completion("a"), completion("b"))
    llm_client.chat([{"role": "user", "content": "hi"}], model=MODEL, client=client)
    llm_client.chat([{"role": "user", "content": "hi"}], model=MODEL, client=client, timeout=12)
    assert client.calls[0]["timeout"] == 90.0
    assert client.calls[1]["timeout"] == 12


def test_client_error_is_not_retried():
    client = FakeClient(bad_request(), completion("never reached"))
    with pytest.raises(openai.BadRequestError):
        llm_client.chat([{"role": "user", "content": "hi"}], model=MODEL, client=client)
    assert len(client.calls) == 1


# thinking toggle ---------------------------------------------------------------

def test_thinking_toggle_and_reasoning_trace():
    client = FakeClient(completion("8", reasoning="120 / 15 = 8"), completion("8"))
    on = llm_client.chat([{"role": "user", "content": "q"}], thinking=True, model=MODEL, client=client)
    off = llm_client.chat([{"role": "user", "content": "q"}], thinking=False, model=MODEL, client=client)
    assert client.calls[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}}
    assert client.calls[1]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert on.reasoning == "120 / 15 = 8"
    assert off.reasoning == ""
    assert (on.prompt_tokens, on.completion_tokens) == (10, 5)


# structured JSON ---------------------------------------------------------------

def test_invalid_json_then_valid_json():
    client = FakeClient(
        completion("Sure! I'd run get_balance."),
        completion('{"tools": [{"name": "get_balance", "arguments": {"account": "checking"}}]}'),
    )
    result = llm_client.chat_json([{"role": "user", "content": "plan"}], model=MODEL, client=client)
    assert result.data == {"tools": [{"name": "get_balance", "arguments": {"account": "checking"}}]}
    assert result.json_retries == 1
    second_messages = client.calls[1]["messages"]
    assert second_messages[-2] == {"role": "assistant", "content": "Sure! I'd run get_balance."}
    assert "not valid JSON" in second_messages[-1]["content"]


def test_invalid_json_twice_raises():
    client = FakeClient(completion("nope"), completion("still nope"))
    with pytest.raises(llm_client.InvalidJSONError) as exc:
        llm_client.chat_json([{"role": "user", "content": "plan"}], model=MODEL, client=client)
    assert exc.value.raw_text == "still nope"
    assert len(client.calls) == 2


def test_validate_failure_triggers_json_retry():
    def validate(data):
        if "tools" not in data:
            raise ValueError("missing 'tools'")

    client = FakeClient(completion('{"plan": []}'), completion('{"tools": []}'))
    result = llm_client.chat_json([{"role": "user", "content": "plan"}], model=MODEL, client=client, validate=validate)
    assert result.data == {"tools": []}
    assert "missing 'tools'" in client.calls[1]["messages"][-1]["content"]


def test_json_in_code_fence_is_accepted():
    client = FakeClient(completion('```json\n{"tools": []}\n```'))
    result = llm_client.chat_json([{"role": "user", "content": "plan"}], model=MODEL, client=client)
    assert result.data == {"tools": []}
    assert result.json_retries == 0


# streaming ---------------------------------------------------------------------

def test_stream_yields_reasoning_and_text_and_builds_result():
    chunks = [
        chunk(reasoning="Rent is due first. "),
        chunk(content="You can't "),
        chunk(content="afford it [5]."),
        chunk(usage=SimpleNamespace(prompt_tokens=50, completion_tokens=30)),
    ]
    client = FakeClient(iter(chunks))
    stream = llm_client.stream_chat([{"role": "user", "content": "explain"}], model=MODEL, client=client)
    assert client.calls == []  # nothing sent until iterated
    events = list(stream)
    assert events == [("reasoning", "Rent is due first. "), ("text", "You can't "), ("text", "afford it [5].")]
    assert client.calls[0]["stream"] is True
    assert client.calls[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}}
    assert stream.result.text == "You can't afford it [5]."
    assert stream.result.reasoning == "Rent is due first. "
    assert stream.result.completion_tokens == 30


def test_stream_retries_opening_on_500_and_text_chunks():
    client = FakeClient(server_error(500), iter([chunk(content="ok")]))
    stream = llm_client.stream_chat([{"role": "user", "content": "explain"}], model=MODEL, client=client)
    assert list(stream.text_chunks()) == ["ok"]
    assert stream.result.retries == 1


# default models (rule 9 split) -------------------------------------------------

@pytest.fixture
def split_models(monkeypatch):
    monkeypatch.setenv("NVIDIA_PLAN_MODEL", "plan-model")
    monkeypatch.setenv("NVIDIA_EXPLAIN_MODEL", "explain-model")


def test_chat_json_defaults_to_plan_model(split_models):
    client = FakeClient(completion('{"tools": []}'))
    llm_client.chat_json([{"role": "user", "content": "plan"}], client=client)
    assert client.calls[0]["model"] == "plan-model"


def test_chat_and_stream_default_to_explain_model(split_models):
    client = FakeClient(completion("a"), iter([chunk(content="b")]))
    llm_client.chat([{"role": "user", "content": "x"}], client=client)
    list(llm_client.stream_chat([{"role": "user", "content": "x"}], client=client))
    assert [c["model"] for c in client.calls] == ["explain-model", "explain-model"]


def test_parse_json_repairs_a_forgotten_closing_brace():
    # seen live from Lightning for "What if I pick up a 5 hour shift on Nov 7?"
    raw = ('{"resolved_question": "What if I pick up a 5 hour shift on Nov 7?", "intent": "what_if", "calls": '
           '[{"tool": "what_if", "args": {"extra_shifts": [{"date": "2026-11-07", "hours": 5}]}]}')
    data = llm_client.parse_json(raw)
    assert data["calls"][0]["args"]["extra_shifts"] == [{"date": "2026-11-07", "hours": 5}]
    assert llm_client.parse_json('{"a": "}]", "b": [1, 2') == {"a": "}]", "b": [1, 2]}   # strings untouched
