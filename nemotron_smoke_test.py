"""Smoke test for NVIDIA Nemotron through the OpenAI-compatible API.

    .venv/Scripts/python nemotron_smoke_test.py

Three checks, each printing PASS/FAIL with the time taken:
  a. plain chat
  b. tool calling (get_balance), run TOOL_TRIALS times
  c. reasoning on vs off via chat_template_kwargs.enable_thinking
Uses only the openai client and config.py.
"""
import json
import sys
import time

from openai import OpenAI

import config

TOOL_TRIALS = 3
FAKE_BALANCE = 1234.56

client = OpenAI(
    base_url=config.require("NVIDIA_BASE_URL"),
    api_key=config.require("NVIDIA_API_KEY"),
    timeout=180,
)
MODEL = config.require("NVIDIA_MODEL")


def chat(messages, thinking, **kwargs):
    """One non-streaming chat call. Returns (message, usage, seconds)."""
    start = time.perf_counter()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.2,
        max_tokens=4096,
        extra_body={"chat_template_kwargs": {"enable_thinking": thinking}},
        **kwargs,
    )
    return resp.choices[0].message, resp.usage, time.perf_counter() - start


def reasoning_text(message):
    """The reasoning trace, if the API returned one (non-standard field)."""
    extra = message.model_extra or {}
    return getattr(message, "reasoning_content", None) or extra.get("reasoning_content") or extra.get("reasoning") or ""


def report(name, ok, seconds, detail):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} ({seconds:.1f}s) {detail}")
    return ok


# a. plain chat ---------------------------------------------------------------
def check_chat():
    msg, _, secs = chat([{"role": "user", "content": "In one sentence, what is a budget?"}], thinking=False)
    reply = (msg.content or "").strip()
    return report("a. plain chat", bool(reply), secs, f"reply: {reply!r}")


# b. tool calling -------------------------------------------------------------
TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_balance",
        "description": "Get the current balance in US dollars of one of the student's accounts.",
        "parameters": {
            "type": "object",
            "properties": {"account": {"type": "string", "enum": ["checking", "savings", "credit_card"]}},
            "required": ["account"],
        },
    },
}]


def get_balance(account):
    return {"account": account, "balance_usd": FAKE_BALANCE}


def tool_trial(n):
    messages = [{"role": "user", "content": "What is the balance of my checking account? Use the tool."}]
    msg, _, secs1 = chat(messages, thinking=True, tools=TOOLS, tool_choice="auto")
    calls = msg.tool_calls or []
    if len(calls) != 1 or calls[0].function.name != "get_balance":
        return report(f"b. tool calling, trial {n}", False, secs1,
                      f"expected one get_balance call, got tool_calls={calls!r} content={msg.content!r}")
    call = calls[0]
    try:
        args = json.loads(call.function.arguments)
    except json.JSONDecodeError as e:
        return report(f"b. tool calling, trial {n}", False, secs1, f"arguments not valid JSON: {call.function.arguments!r} ({e})")
    if args.get("account") != "checking":
        return report(f"b. tool calling, trial {n}", False, secs1, f"wrong arguments: {args}")

    messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [{
        "id": call.id, "type": "function",
        "function": {"name": call.function.name, "arguments": call.function.arguments},
    }]})
    messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(get_balance(**args))})
    final, _, secs2 = chat(messages, thinking=True, tools=TOOLS)
    answer = (final.content or "").strip()
    used_number = "1234.56" in answer.replace(",", "")
    return report(f"b. tool calling, trial {n}", used_number, secs1 + secs2,
                  f"call args={call.function.arguments} -> answer: {answer!r}")


def check_tools():
    results = []
    for n in range(1, TOOL_TRIALS + 1):
        try:
            results.append(tool_trial(n))
        except Exception as e:  # report API errors as a failed trial, keep going
            results.append(report(f"b. tool calling, trial {n}", False, 0.0, f"error: {e}"))
    return all(results)


# c. reasoning on vs off ------------------------------------------------------
REASONING_Q = ("A student has $120 and spends $15 every week. After how many full weeks is the money gone? "
               "Answer with just the number at the end.")


def check_reasoning():
    out = {}
    for thinking in (True, False):
        msg, usage, secs = chat([{"role": "user", "content": REASONING_Q}], thinking=thinking)
        out[thinking] = (reasoning_text(msg), (msg.content or "").strip(), usage.completion_tokens, secs)
        r, c, toks, secs = out[thinking]
        print(f"      enable_thinking={thinking}: {secs:.1f}s, completion_tokens={toks}, "
              f"reasoning_chars={len(r)}, answer={c[-80:]!r}")
    on_r, _, on_toks, on_secs = out[True]
    off_r, _, off_toks, off_secs = out[False]
    toggle_works = bool(on_r) and not off_r
    return report("c. reasoning toggle", toggle_works, on_secs + off_secs,
                  f"on: reasoning={'yes' if on_r else 'no'} {on_secs:.1f}s / off: reasoning={'yes' if off_r else 'no'} "
                  f"{off_secs:.1f}s / difference {on_secs - off_secs:+.1f}s")


if __name__ == "__main__":
    print(f"model={MODEL} base_url={config.NVIDIA_BASE_URL}")
    results = []
    for check in (check_chat, check_tools, check_reasoning):
        try:
            results.append(check())
        except Exception as e:
            results.append(report(check.__name__, False, 0.0, f"error: {e}"))
    sys.exit(0 if all(results) else 1)
