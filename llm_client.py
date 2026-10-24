"""LLM client for NVIDIA Nemotron over the OpenAI-compatible API.

Models and base URL come from config. Three entry points, matching rule 9 in CLAUDE.md:

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

_client = None


def get_client():
    """Shared OpenAI client for the NVIDIA endpoint. The SDK's own retries are off; we do our own."""
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=config.require("NVIDIA_BASE_URL"),
            api_key=config.require("NVIDIA_API_KEY"),
            max_retries=0,
        )
    return _client


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


def _is_retryable(exc):
    if isinstance(exc, openai.APITimeoutError):
        return True
    return isinstance(exc, openai.APIStatusError) and exc.status_code >= 500


def _request_kwargs(messages, thinking, model, timeout, max_tokens, temperature, extra):
    kwargs = dict(
        model=model or config.require("NVIDIA_EXPLAIN_MODEL"),
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        extra_body={"chat_template_kwargs": {"enable_thinking": thinking}},
    )
    kwargs.update(extra)
    return kwargs


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
        "llm call model=%s thinking=%s duration=%.1fs prompt_tokens=%s completion_tokens=%s retries=%d",
        result.model, "on" if result.thinking else "off", result.duration_s,
        result.prompt_tokens, result.completion_tokens, result.retries,
    )


def chat(messages, thinking=False, *, model=None, timeout=DEFAULT_TIMEOUT_S, retries=DEFAULT_RETRIES,
         max_tokens=DEFAULT_MAX_TOKENS, temperature=DEFAULT_TEMPERATURE, client=None, **extra):
    """One normal (non-streaming) call. Returns an LLMResult with the answer and the reasoning trace."""
    client = client or get_client()
    kwargs = _request_kwargs(messages, thinking, model, timeout, max_tokens, temperature, extra)
    start = time.perf_counter()
    resp, retries_used = _with_retries(lambda: client.chat.completions.create(**kwargs), retries)
    message = resp.choices[0].message
    usage = getattr(resp, "usage", None)
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


def parse_json(text):
    """Parse a JSON answer, tolerating a ```json fence around it and forgotten closing brackets. Raises ValueError."""
    text = text.strip()
    match = _FENCE.match(text)
    if match:
        text = match.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(repair_brackets(text))


def chat_json(messages, thinking=False, *, validate=None, **kwargs):
    """A call whose answer must be JSON (the PLAN call).

    validate, if given, is called with the parsed value and should raise ValueError if the
    shape is wrong. On invalid JSON (or a failed validate) the call is retried once, with the
    error message sent back to the model. Raises InvalidJSONError if the second answer is
    invalid too.
    """
    if not kwargs.get("model"):
        kwargs["model"] = config.require("NVIDIA_PLAN_MODEL")
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
    _start_call: object
    _kwargs: dict
    _thinking: bool
    _retries: int
    result: LLMResult | None = None
    _reasoning: list = field(default_factory=list)
    _text: list = field(default_factory=list)

    def __iter__(self):
        start = time.perf_counter()
        # Retry only while opening the stream; once chunks arrive, a mid-stream failure is raised.
        stream, retries_used = _with_retries(self._start_call, self._retries)
        prompt_tokens = completion_tokens = finish_reason = None
        for chunk in stream:
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
            model=self._kwargs["model"],
            thinking=self._thinking,
            duration_s=time.perf_counter() - start,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            retries=retries_used,
            finish_reason=finish_reason,
        )
        _log(self.result)

    def text_chunks(self):
        for kind, chunk in self:
            if kind == "text":
                yield chunk


def stream_chat(messages, thinking=True, *, model=None, timeout=DEFAULT_TIMEOUT_S, retries=DEFAULT_RETRIES,
                max_tokens=DEFAULT_MAX_TOKENS, temperature=DEFAULT_TEMPERATURE, client=None, **extra):
    """A streaming call (the EXPLAIN call). Nothing is sent until the returned LLMStream is iterated."""
    client = client or get_client()
    kwargs = _request_kwargs(messages, thinking, model, timeout, max_tokens, temperature, extra)
    kwargs["stream"] = True
    return LLMStream(lambda: client.chat.completions.create(**kwargs), kwargs, thinking, retries)
