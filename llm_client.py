"""LLM client for NVIDIA Nemotron, through the Meterless Runtime (served by the Nightshift desktop app) by default.

Two OpenAI-compatible providers (config.AI_PROVIDER):
    meterless  the primary: Meterless Runtime 0.90.0 at config.METERLESS_BASE_URL, Authorization: Bearer <runtime
               token>, meterless-app: runway on every request, meterless-scope: user on chat. The NVIDIA key lives
               inside Nightshift, not here. Each answer carries a meterless.compute_receipt.v1 naming the routed model.
    nvidia     NVIDIA's API directly. Used as the provider only if AI_PROVIDER=nvidia; otherwise only as a labelled
               fallback when the Meterless Runtime is unreachable or refuses the token (and NVIDIA_API_KEY is set).

Models come from config. Three entry points, matching rule 9 in CLAUDE.md:

    chat(messages, thinking=False)        -> LLMResult             normal call    (default model: NVIDIA_EXPLAIN_MODEL)
    chat_json(messages, thinking=False)   -> LLMResult (.data)     PLAN call      (default model: NVIDIA_PLAN_MODEL)
    stream_chat(messages, thinking=True)  -> LLMStream             EXPLAIN call   (default model: NVIDIA_EXPLAIN_MODEL)

Pass model= to override per call.

Every call has a timeout (default 90 s) and up to 2 retries with exponential backoff on 5xx
errors and timeouts, and writes one log line: model, thinking, duration, tokens, retries.
"""
import json
import logging
import re
import time
from dataclasses import dataclass, field

import openai
from openai import OpenAI

import config

log = logging.getLogger("llm_client")

DEFAULT_TIMEOUT_S = 90.0
DEFAULT_RETRIES = 2
BACKOFF_BASE_S = 2.0  # waits 2 s, then 4 s
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.2

# Patched in tests so retries don't really wait.
sleep = time.sleep

_clients = {}
PROVIDER_NAMES = {"meterless": "Meterless Nightshift", "nvidia": "NVIDIA API (direct)"}


def get_client(provider=None):
    """Shared OpenAI client per provider. The SDK's own retries are off; we do our own."""
    provider = provider or config.AI_PROVIDER
    if provider not in _clients:
        if provider == "meterless":
            if not config.METERLESS_RUNTIME_TOKEN:
                raise config.MissingSetting("Setting METERLESS_RUNTIME_TOKEN is missing (the Runtime API key from "
                                            "Nightshift's Console / Setup > Runtime). Add it to .env.")
            _clients[provider] = OpenAI(base_url=config.METERLESS_BASE_URL, api_key=config.METERLESS_RUNTIME_TOKEN,
                                        max_retries=0, timeout=config.METERLESS_TIMEOUT_S,
                                        default_headers={"meterless-app": config.METERLESS_APP})
        else:
            _clients[provider] = OpenAI(base_url=config.require("NVIDIA_BASE_URL"),
                                        api_key=config.require("NVIDIA_API_KEY"), max_retries=0)
    return _clients[provider]


def providers():
    """Providers to try in order: the configured one, then direct NVIDIA as a fallback if Meterless is the
    provider and an NVIDIA key is set."""
    order = [config.AI_PROVIDER]
    if config.AI_PROVIDER == "meterless" and config.NVIDIA_API_KEY:
        order.append("nvidia")
    return order


def runtime_down(exc):
    """The Meterless Runtime itself is unreachable or refuses our token (not a model or NVIDIA error behind it):
    the only case where the direct NVIDIA fallback is used."""
    if isinstance(exc, (config.MissingSetting, openai.APIConnectionError)):
        return True
    if isinstance(exc, openai.APIStatusError) and exc.status_code in (401, 403):
        body = exc.body if isinstance(exc.body, dict) else {}
        err = body.get("error", body)
        return isinstance(err, dict) and (err.get("layer") == "meterless-runtime"
                                          or str(err.get("code", "")).startswith("runtime_token"))
    return False


def fallback_model(model, provider):
    """The model to ask on the direct NVIDIA fallback: the Think harder model maps to NVIDIA_EXPLAIN_MODEL."""
    if provider == "nvidia" and model == config.THINK_MODEL and config.NVIDIA_EXPLAIN_MODEL:
        return config.NVIDIA_EXPLAIN_MODEL
    return model


def receipt_of(obj):
    """The meterless.compute_receipt.v1 fields on a response or a stream chunk ({} if none)."""
    if obj is None:
        return {}
    value = getattr(obj, "meterless", None)
    if value is None:
        value = (getattr(obj, "model_extra", None) or {}).get("meterless")
    return value if isinstance(value, dict) else {}


class LLMError(RuntimeError):
    """The call failed after all retries, or never returned usable output."""


class InvalidJSONError(LLMError):
    """The model did not return valid JSON, even after one corrective retry."""

    def __init__(self, message, raw_text):
        super().__init__(message)
        self.raw_text = raw_text


@dataclass
class LLMResult:
    text: str
    reasoning: str
    model: str
    thinking: bool
    duration_s: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    retries: int = 0
    data: object = None  # parsed JSON, chat_json only
    json_retries: int = 0  # chat_json only: 1 if the first answer was invalid JSON
    finish_reason: str | None = None  # "stop", or "length" when the answer hit max_tokens
    provider: str = "nvidia"  # "meterless" or "nvidia"
    fallback: bool = False  # True when direct NVIDIA answered because the Meterless Runtime was down
    routed_model: str | None = None  # the model that actually answered (Meterless receipt, or the response's model)
    receipt_id: str | None = None  # meterless.compute_receipt.v1 receipt id

    def call_record(self, role):
        """One model call, for "How Runway thought about this" and the trace."""
        return {"role": role, "provider": self.provider, "fallback": self.fallback, "requested_model": self.model,
                "routed_model": self.routed_model or self.model, "receipt_id": self.receipt_id,
                "thinking": self.thinking, "duration_s": round(self.duration_s, 2), "retries": self.retries,
                "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                "finish_reason": self.finish_reason}


def _is_retryable(exc):
    if isinstance(exc, openai.APITimeoutError):
        return True
    return isinstance(exc, openai.APIStatusError) and exc.status_code >= 500


MIN_MAX_TOKENS = 400  # a Nemotron call with thinking possible needs room, or the answer comes back empty


def _request_kwargs(messages, thinking, model, timeout, max_tokens, temperature, extra, provider="nvidia"):
    kwargs = dict(
        model=fallback_model(model or config.think_model(provider), provider),
        messages=messages,
        temperature=temperature,
        max_tokens=max(max_tokens, MIN_MAX_TOKENS),
        timeout=max(timeout, config.METERLESS_TIMEOUT_S) if provider == "meterless" else timeout,
        extra_body={"chat_template_kwargs": {"enable_thinking": thinking}},
    )
    if provider == "meterless":
        kwargs["extra_headers"] = {"meterless-scope": "user"}
    kwargs.update(extra)
    return kwargs


def _on_providers(make_call, client):
    """Run make_call(provider, client) on the first provider that works, moving to direct NVIDIA only when the
    Meterless Runtime is down. Returns (value, provider). A test client (client=...) is used as-is."""
    if client is not None:
        return make_call(config.AI_PROVIDER, client), config.AI_PROVIDER
    order = providers()
    for i, provider in enumerate(order):
        try:
            return make_call(provider, get_client(provider)), provider
        except Exception as exc:
            if provider != "meterless" or i == len(order) - 1 or not runtime_down(exc):
                raise
            log.warning("Meterless Runtime unavailable (%s); falling back to the NVIDIA API directly",
                        type(exc).__name__)


def _with_retries(do_call, retries):
    """Run do_call(), retrying retryable errors with exponential backoff. Returns (value, retries_used)."""
    for attempt in range(retries + 1):
        try:
            return do_call(), attempt
        except Exception as exc:
            if not _is_retryable(exc) or attempt == retries:
                raise
            wait = BACKOFF_BASE_S * (2 ** attempt)
            log.warning("llm retryable error (%s), retry %d/%d in %.0fs", type(exc).__name__, attempt + 1, retries, wait)
            sleep(wait)


def _reasoning_of(obj):
    """reasoning_content is not a standard OpenAI field; NVIDIA returns it as an extra."""
    if obj is None:
        return ""
    value = getattr(obj, "reasoning_content", None)
    if value is None:
        extra = getattr(obj, "model_extra", None) or {}
        value = extra.get("reasoning_content") or extra.get("reasoning")
    return value or ""


def _log(result):
    log.info(
        "llm call provider=%s%s model=%s routed=%s receipt=%s thinking=%s duration=%.1fs prompt_tokens=%s "
        "completion_tokens=%s retries=%d",
        result.provider, " (fallback)" if result.fallback else "", result.model, result.routed_model,
        result.receipt_id, "on" if result.thinking else "off", result.duration_s,
        result.prompt_tokens, result.completion_tokens, result.retries,
    )


def chat(messages, thinking=False, *, model=None, timeout=DEFAULT_TIMEOUT_S, retries=DEFAULT_RETRIES,
         max_tokens=DEFAULT_MAX_TOKENS, temperature=DEFAULT_TEMPERATURE, client=None, **extra):
    """One normal (non-streaming) call. Returns an LLMResult with the answer, the reasoning trace, the provider and
    the routed model."""
    start = time.perf_counter()

    def call(provider, c):
        kwargs = _request_kwargs(messages, thinking, model, timeout, max_tokens, temperature, extra, provider)
        resp, used = _with_retries(lambda: c.chat.completions.create(**kwargs), retries)
        return resp, used, kwargs

    (resp, retries_used, kwargs), provider = _on_providers(call, client)
    message = resp.choices[0].message
    usage = getattr(resp, "usage", None)
    receipt = receipt_of(resp)
    result = LLMResult(
        text=(message.content or "").strip(),
        reasoning=_reasoning_of(message),
        model=kwargs["model"],
        thinking=thinking,
        duration_s=time.perf_counter() - start,
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        retries=retries_used,
        finish_reason=getattr(resp.choices[0], "finish_reason", None),
        provider=provider,
        fallback=provider != config.AI_PROVIDER,
        routed_model=receipt.get("routed_model") or getattr(resp, "model", None) or kwargs["model"],
        receipt_id=receipt.get("receipt_id"),
    )
    _log(result)
    return result


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def repair_brackets(text):
    """Close brackets the model forgot: a "]" where a "}" is still open gets the "}" first, and anything left
    open at the end is closed. Strings are left alone. (Lightning sometimes writes `...5}]}]}` for `...5}]}}]}`.)"""
    out, stack, in_str, esc = [], [], False, False
    pairs = {"{": "}", "[": "]"}
    for ch in text:
        if in_str:
            in_str = not (ch == '"' and not esc)
            esc = ch == "\\" and not esc
        elif ch == '"':
            in_str = True
        elif ch in pairs:
            stack.append(pairs[ch])
        elif ch in "}]":
            while stack and stack[-1] != ch:
                out.append(stack.pop())
            if stack:
                stack.pop()
        out.append(ch)
    return "".join(out) + "".join(reversed(stack))


def swapped_closers(text):
    """Versions of the text with one adjacent pair of different closing brackets swapped, outside strings.
    (Lightning sometimes writes `...5}]}]}, "clarifying_question"` for `...5}]}}], "clarifying_question"`.)"""
    in_str = esc = False
    for i, ch in enumerate(text[:-1]):
        if in_str:
            in_str = not (ch == '"' and not esc)
            esc = ch == "\\" and not esc
        elif ch == '"':
            in_str = True
        elif ch in "}]" and text[i + 1] in "}]" and text[i + 1] != ch:
            yield text[:i] + text[i + 1] + ch + text[i + 2:]


def parse_json(text):
    """Parse a JSON answer, tolerating a ```json fence around it, forgotten closing brackets and one pair of swapped
    closing brackets. Raises ValueError. The caller still validates the shape."""
    text = text.strip()
    match = _FENCE.match(text)
    if match:
        text = match.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as first:
        try:
            return json.loads(repair_brackets(text))
        except json.JSONDecodeError:
            for candidate in swapped_closers(text):
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
            raise first


def chat_json(messages, thinking=False, *, validate=None, **kwargs):
    """A call whose answer must be JSON (the PLAN call).

    validate, if given, is called with the parsed value and should raise ValueError if the
    shape is wrong. On invalid JSON (or a failed validate) the call is retried once, with the
    error message sent back to the model. Raises InvalidJSONError if the second answer is
    invalid too.
    """
    if not kwargs.get("model"):
        kwargs["model"] = config.NVIDIA_PLAN_MODEL
    total_start = time.perf_counter()
    result = chat(messages, thinking, **kwargs)
    total_retries = result.retries
    for json_attempt in range(2):
        try:
            data = parse_json(result.text)
            if validate is not None:
                validate(data)
            result.data = data
            result.json_retries = json_attempt
            result.retries = total_retries
            result.duration_s = time.perf_counter() - total_start
            return result
        except ValueError as exc:  # json.JSONDecodeError is a ValueError
            if json_attempt == 1:
                raise InvalidJSONError(f"model did not return valid JSON after one retry: {exc}", result.text) from exc
            log.warning("llm invalid JSON (%s), retrying once with the error", exc)
            messages = list(messages) + [
                {"role": "assistant", "content": result.text},
                {"role": "user", "content": f"That was not valid JSON for the requested format: {exc}. "
                                            "Reply again with only the JSON, no other text."},
            ]
            result = chat(messages, thinking, **kwargs)
            total_retries += result.retries


@dataclass
class LLMStream:
    """Iterate to receive ("reasoning" | "text", chunk) events as they arrive. After the
    iteration ends, .result holds the full LLMResult.

        stream = stream_chat(messages)
        for kind, chunk in stream:
            ...
        stream.result.text, stream.result.reasoning

    text_chunks() yields only the answer text (for st.write_stream).
    """
    _start_call: object  # (provider, client) -> (stream, kwargs)
    _client: object
    _thinking: bool
    _retries: int
    result: LLMResult | None = None
    _reasoning: list = field(default_factory=list)
    _text: list = field(default_factory=list)

    def __iter__(self):
        start = time.perf_counter()
        # Retry only while opening the stream; once chunks arrive, a mid-stream failure is raised.
        def open_stream(provider, c):
            kwargs = self._start_call(provider)
            stream, used = _with_retries(lambda: c.chat.completions.create(**kwargs), self._retries)
            return stream, used, kwargs
        (stream, retries_used, kwargs), provider = _on_providers(open_stream, self._client)
        prompt_tokens = completion_tokens = finish_reason = None
        receipt, routed = {}, None
        for chunk in stream:
            receipt = receipt_of(chunk) or receipt
            routed = getattr(chunk, "model", None) or routed
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                prompt_tokens = getattr(usage, "prompt_tokens", prompt_tokens)
                completion_tokens = getattr(usage, "completion_tokens", completion_tokens)
            for choice in chunk.choices or []:
                finish_reason = getattr(choice, "finish_reason", None) or finish_reason
                delta = choice.delta
                reasoning = _reasoning_of(delta)
                if reasoning:
                    self._reasoning.append(reasoning)
                    yield "reasoning", reasoning
                if delta.content:
                    self._text.append(delta.content)
                    yield "text", delta.content
        self.result = LLMResult(
            text="".join(self._text).strip(),
            reasoning="".join(self._reasoning),
            model=kwargs["model"],
            thinking=self._thinking,
            duration_s=time.perf_counter() - start,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            retries=retries_used,
            finish_reason=finish_reason,
            provider=provider,
            fallback=provider != config.AI_PROVIDER,
            routed_model=receipt.get("routed_model") or routed or kwargs["model"],
            receipt_id=receipt.get("receipt_id"),
        )
        _log(self.result)

    def text_chunks(self):
        for kind, chunk in self:
            if kind == "text":
                yield chunk


def stream_chat(messages, thinking=True, *, model=None, timeout=DEFAULT_TIMEOUT_S, retries=DEFAULT_RETRIES,
                max_tokens=DEFAULT_MAX_TOKENS, temperature=DEFAULT_TEMPERATURE, client=None, **extra):
    """A streaming call (the EXPLAIN call). Nothing is sent until the returned LLMStream is iterated."""
    def kwargs_for(provider):
        kwargs = _request_kwargs(messages, thinking, model, timeout, max_tokens, temperature, extra, provider)
        kwargs["stream"] = True
        return kwargs
    return LLMStream(kwargs_for, client, thinking, retries)
