"""Latency benchmark for Nemotron models on the NVIDIA endpoint. Measures only; not a test.

    .venv/Scripts/python benchmark_latency.py [runs]

For each model, `runs` times (default 3):
  plan    - structured-JSON tool plan, thinking off   (llm_client.chat_json)
  explain - short explanation from evidence, thinking on, streamed (llm_client.stream_chat)
Each call: 120 s timeout, no retries, so every sample is one real attempt.
The three models run in parallel threads; each model's calls run one after another.
"""
import logging
import statistics
import sys
import threading
import time
from datetime import datetime

import llm_client

MODELS = [
    "nvidia/nemotron-3.5-super-vl-120b-a12b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
]
TIMEOUT_S = 120
TOOL_NAMES = {"get_balance", "get_upcoming_bills", "get_income_schedule", "project_balance"}

PLAN_MESSAGES = [
    {"role": "system", "content": (
        "You plan which tools to run to answer a college student's money question. Available tools:\n"
        "- get_balance(account): current balance; account is one of checking, credit_card\n"
        "- get_upcoming_bills(days): bills due in the next N days\n"
        "- get_income_schedule(days): paychecks and aid disbursements expected in the next N days\n"
        "- project_balance(extra_expense, days): projected lowest balance over the next N days if extra_expense is spent today\n"
        'Reply with only JSON: {"tools": [{"name": "<tool>", "arguments": {...}}]}. No other text.'
    )},
    {"role": "user", "content": "Can I afford a $400 spring break trip?"},
]

EXPLAIN_MESSAGES = [
    {"role": "system", "content": "Explain the answer to the student in 3 short sentences, citing the evidence lines by number."},
    {"role": "user", "content": (
        "Question: Can I afford a $400 spring break trip?\n"
        "Evidence:\n"
        "[1] checking balance: $612.40 (source: checking, query: balance)\n"
        "[2] rent due Mar 1: $450.00 (source: lease)\n"
        "[3] paycheck Feb 28: $310.00 (source: work shifts)\n"
        "[4] credit card statement due Mar 3: $96.15 (source: credit card)\n"
        "[5] projected lowest balance if $400 is spent today: -$23.75 on Mar 3 (computed)\n"
        "Verdict (computed): not affordable without going negative."
    )},
]


def validate_plan(data):
    if not isinstance(data, dict) or not isinstance(data.get("tools"), list) or not data["tools"]:
        raise ValueError('expected {"tools": [ ... ]} with at least one tool')
    for t in data["tools"]:
        if not isinstance(t, dict) or t.get("name") not in TOOL_NAMES or not isinstance(t.get("arguments", {}), dict):
            raise ValueError(f"bad tool entry: {t!r}")


def run_plan(model):
    start = time.perf_counter()
    try:
        r = llm_client.chat_json(PLAN_MESSAGES, thinking=False, validate=validate_plan, model=model,
                                 timeout=TIMEOUT_S, retries=0, max_tokens=1024)
        return dict(ok=True, secs=time.perf_counter() - start, json_valid=True, json_retry=r.json_retries,
                    detail=r.text[:120])
    except llm_client.InvalidJSONError as e:
        return dict(ok=False, secs=time.perf_counter() - start, json_valid=False, detail=f"invalid JSON: {e.raw_text[:120]!r}")
    except Exception as e:
        return dict(ok=False, secs=time.perf_counter() - start, json_valid=None, detail=f"{type(e).__name__}: {str(e)[:120]}")


def run_explain(model):
    start = time.perf_counter()
    first_text = None
    try:
        stream = llm_client.stream_chat(EXPLAIN_MESSAGES, thinking=True, model=model, timeout=TIMEOUT_S,
                                        retries=0, max_tokens=2048)
        for kind, _ in stream:
            if kind == "text" and first_text is None:
                first_text = time.perf_counter() - start
        r = stream.result
        ok = bool(r.text)
        return dict(ok=ok, secs=time.perf_counter() - start, first_text=first_text,
                    reasoning_chars=len(r.reasoning), detail=r.text[:120] if ok else "empty answer")
    except Exception as e:
        return dict(ok=False, secs=time.perf_counter() - start, first_text=first_text,
                    detail=f"{type(e).__name__}: {str(e)[:120]}")


def bench_model(model, runs, out):
    for i in range(runs):
        for task, fn in (("plan", run_plan), ("explain", run_explain)):
            res = fn(model)
            res.update(model=model, task=task, run=i + 1)
            out.append(res)
            print(f"  {datetime.now():%H:%M:%S} {model} {task} run {i + 1}: "
                  f"{'ok' if res['ok'] else 'FAIL'} {res['secs']:.1f}s {res['detail']!r}", flush=True)


def fmt(x):
    return f"{x:.1f}" if x is not None else "-"


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    started = datetime.now().astimezone()
    print(f"started {started:%Y-%m-%d %H:%M %Z}, {runs} runs per model and task, timeout {TIMEOUT_S}s, no retries")
    results = []
    threads = [threading.Thread(target=bench_model, args=(m, runs, results)) for m in MODELS]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ended = datetime.now().astimezone()

    print(f"\nran {started:%Y-%m-%d %H:%M}-{ended:%H:%M %Z}")
    print("model | task | median s | min s | max s | failures | JSON valid | median first text s")
    for m in MODELS:
        for task in ("plan", "explain"):
            rows = [r for r in results if r["model"] == m and r["task"] == task]
            ok_times = [r["secs"] for r in rows if r["ok"]]
            fails = sum(not r["ok"] for r in rows)
            if task == "plan":
                valid = sum(r.get("json_valid") is True for r in rows)
                retried = sum(r.get("json_retry", 0) for r in rows)
                json_col = f"{valid}/{len(rows)}" + (f" ({retried} after retry)" if retried else "")
                first_col = "-"
            else:
                json_col = "n/a"
                firsts = [r["first_text"] for r in rows if r.get("first_text") is not None]
                first_col = fmt(statistics.median(firsts)) if firsts else "-"
            med = statistics.median(ok_times) if ok_times else None
            print(f"{m} | {task} | {fmt(med)} | {fmt(min(ok_times) if ok_times else None)} | "
                  f"{fmt(max(ok_times) if ok_times else None)} | {fails}/{len(rows)} | {json_col} | {first_col}")


if __name__ == "__main__":
    main()
