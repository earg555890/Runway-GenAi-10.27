"""Live evaluation of Ask Runway: 10 realistic questions against the real NVIDIA models (not part of pytest).

    .venv/Scripts/python eval_agent.py              # one run  -> eval_results.md / eval_results.json
    .venv/Scripts/python eval_agent.py 3 240        # 3 runs, 240 s apart -> also eval_summary.md

For each question: did PLAN pick the expected tool, is the verdict right, did every number and date pass
the check, did the model itself write every required fact (agent.required_facts: the same table the app
enforces), and did a Nemotron model write it. Expected verdicts come from the engine (deterministic). Answers
that needed Runway's deterministic fact lines are counted separately. Before each run the script waits until
the EXPLAIN endpoint answers a tiny request.
"""
import json
import sys
import time
from dataclasses import dataclass, field

import agent
import config
import engine
import llm_client
import normalize

SUBS = None


@dataclass
class Case:
    question: str
    tool: str | None
    args: dict = field(default_factory=dict)


CASES = [
    Case(agent.SUGGESTED[0], "can_afford", {"item": "flight home", "cost": 400, "date": "2026-11-10"}),
    Case(agent.SUGGESTED[1], "runway"),
    Case(agent.SUGGESTED[2], "find_leaks"),
    Case("What if I pick up a 5 hour shift on Nov 7?", "what_if",
         {"extra_shifts": [{"date": "2026-11-07", "hours": 5}]}),
    Case("Can I afford new headphones for $150?", "can_afford", {"item": "headphones", "cost": 150}),
    Case("Can I put a $120 concert ticket on my credit card on Nov 20?", "can_afford",
         {"item": "concert ticket", "cost": 120, "date": "2026-11-20", "account": "card"}),
    Case("What's the capital of France?", None),
    Case("am I ok?", "runway"),
    Case("Why is my refund on hold?", "refund_status"),
    Case("Is there a week coming up where money gets really tight?", "cash_crunches"),
]


def expected_verdict(case, ds):
    if case.tool is None:
        return None
    plan = agent.parse_plan({"intent": "x", "tool": case.tool, "args": case.args}, SUBS)
    return agent.execute(plan, engine.Scenario(), ds).verdict


def healthy(tries=10, wait_s=60):
    """Wait until the EXPLAIN model answers a tiny request (the endpoint has bad spells)."""
    for _ in range(tries):
        try:
            s = llm_client.stream_chat([{"role": "user", "content": "Say OK."}], thinking=False, retries=0, timeout=60)
            if "".join(c for k, c in s if k == "text").strip():
                return True
        except Exception as exc:
            print(f"  endpoint not healthy ({type(exc).__name__}), waiting {wait_s} s", flush=True)
        time.sleep(wait_s)
    return False


def run_once(ds, run_no):
    results = []
    for i, case in enumerate(CASES, start=1):
        start = time.perf_counter()
        a = agent.ask(case.question, engine.Scenario(), ds=ds, mode="live")
        want = expected_verdict(case, ds)
        tool_ok = a.plan["tool"] == case.tool
        verdict_ok = a.verdict == want
        check_ok = bool(a.check.get("ok")) if case.tool else True
        facts = a.facts or []
        appended = [f["label"] for f in facts if f["appended"]]
        facts_ok = not appended                                   # every required fact written by the model itself
        nvidia_error = a.explain_source == "template" or a.plan["source"] == "keywords"
        model_answer = case.tool is None or a.explain_source == "llm"
        passed = tool_ok and verdict_ok and check_ok and facts_ok and model_answer
        r = dict(run=run_no, n=i, question=case.question, expected_tool=case.tool, tool=a.plan["tool"],
                 plan_source=a.plan["source"], expected_verdict=want, verdict=a.verdict, tool_ok=tool_ok,
                 verdict_ok=verdict_ok, check_ok=check_ok, problems=a.check.get("problems"), facts_ok=facts_ok,
                 facts=len(facts), appended=appended, rewrites=a.retries.get("explain_rewrite", 0),
                 answered_by=a.models.get("answered_by"), explain_errors=a.models.get("explain_errors"),
                 nvidia_error=nvidia_error, passed=passed, mode=a.mode, retries=a.retries, timings=a.timings,
                 wall_s=round(time.perf_counter() - start, 1), answer=a.text, notes=a.notes)
        results.append(r)
        print(json.dumps({k: r[k] for k in ("run", "n", "tool", "verdict", "check_ok", "facts_ok", "appended", "answered_by",
                                            "passed", "timings")}), flush=True)
    return results


def _yes(ok):
    return "yes" if ok else "NO"


def table(results):
    rows = [f"| {r['n']} | {r['question']} | {r['expected_tool'] or 'none (off-topic)'} / {_yes(r['tool_ok'])} | "
            f"{r['expected_verdict'] or '-'} / {_yes(r['verdict_ok'])} | {_yes(r['check_ok'])} | "
            f"{('all ' + str(r['facts'])) if not r['appended'] else (str(len(r['appended'])) + ' added')} | "
            f"{agent.model_name(r['answered_by']) if r['expected_tool'] else '-'} | "
            f"{r['retries']['plan_json']}+{r['retries'].get('explain_rewrite', 0)} | "
            f"{r['timings'].get('plan_s', '-')} | {r['timings'].get('explain_s', '-')} | "
            f"{r['timings'].get('total_s', '-')} | {'PASS' if r['passed'] else 'FAIL'} |" for r in results]
    head = ("| # | Question | Tool / right? | Verdict / right? | Check passed | Required facts by model | Written by | "
            "Retries (plan+rewrite) | PLAN s | EXPLAIN s | Total s | Result |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    return head + "\n".join(rows)


def _mistake(r):
    if not r["tool_ok"]:
        return "picked the wrong tool"
    if not r["verdict_ok"]:
        return "gave the wrong verdict"
    if not r["check_ok"]:
        return "used a number or date that didn't match the records"
    return "left out a required fact (Runway added it: " + ", ".join(r["appended"]) + ")"


def summary(runs):
    allr = [r for run in runs for r in run]
    n = len(allr)

    def count(key):
        return sum(bool(r[key]) for r in allr)

    fails = [r for r in allr if not r["passed"]]
    nvidia = [r for r in fails if r["nvidia_error"]]
    real = [r for r in fails if not r["nvidia_error"]]
    writers = {}
    for r in allr:
        if r["expected_tool"]:
            name = agent.model_name(r["answered_by"])
            writers[name] = writers.get(name, 0) + 1
    times = sorted(r["timings"]["explain_s"] for r in allr
                   if r["answered_by"] not in (None, "template") and "explain_s" in r["timings"])
    median = times[len(times) // 2] if times else None
    lines = [
        "# Ask Runway: how well it answers",
        "",
        f"We asked Runway {len(CASES)} realistic student questions, {len(runs)} separate times ({n} answers in all), "
        "using the real NVIDIA Nemotron models. Every answer was graded automatically against numbers that Runway's "
        "money engine computes on its own.",
        "",
        f"- **Picked the right tool:** {count('tool_ok')}/{n}",
        f"- **Gave the right verdict** (yes / no / yes-if; money runs out or not): {count('verdict_ok')}/{n}",
        f"- **Every dollar amount and date matched the student's records:** {count('check_ok')}/{n}",
        f"- **Full answers** (all of the above, and the model itself wrote every required fact): "
        f"{count('passed')}/{n}",
        f"- Answers that needed one rewrite after the check: {sum(1 for r in allr if r['rewrites'])}/{n}",
        f"- Answers where the model still left out a required fact, so Runway added a plain line built from the "
        f"numbers: {sum(1 for r in allr if r['appended'])}/{n}",
        "",
        (f"{len(fails)} answer{'s were' if len(fails) != 1 else ' was'} not a full answer: "
         f"{len(nvidia)} because of NVIDIA service errors (no model responded in time, so Runway showed a short "
         f"summary built from the numbers instead) and {len(real)} because of real mistakes"
         + (":" if real else ".") if fails else "Every answer was a full answer."),
    ]
    lines += [f"  - Run {r['run']}, \"{r['question']}\": {_mistake(r)}" for r in real]
    lines += ["", "Who wrote the answers: " + ", ".join(f"{k} {v}" for k, v in sorted(writers.items()))
              + " (the off-topic question gets a fixed reply and needs no writer).",
              f"Typical time to write an answer: {median} s (median). Planning takes about a second.", "",
              "The model never does the math: Runway's engine computes every number, and a checker rejects any "
              "amount or date the model didn't take from the student's records.", ""]
    for i, run in enumerate(runs, start=1):
        lines += [f"## Run {i}: {sum(r['passed'] for r in run)}/{len(run)} full answers", "", table(run), ""]
    return "\n".join(lines)


def main():
    global SUBS
    n_runs = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    gap_s = int(sys.argv[2]) if len(sys.argv) > 2 else 240
    ds = normalize.load()
    SUBS = [s.merchant for s in engine.subscriptions(ds)]
    print(f"models: plan {config.NVIDIA_PLAN_MODEL}, explain chain {agent.explain_chain()}", flush=True)
    runs = []
    for run_no in range(1, n_runs + 1):
        if run_no > 1:
            time.sleep(gap_s)
        if not healthy():
            print("endpoint still unhealthy; running anyway", flush=True)
        runs.append(run_once(ds, run_no))
        last = runs[-1]
        with open("eval_results.md", "w", encoding="utf-8") as f:
            f.write(f"# Ask Runway live evaluation (latest run)\n\nScore: **{sum(r['passed'] for r in last)}/"
                    f"{len(last)}**\n\n{table(last)}\n")
        with open("eval_results.json", "w", encoding="utf-8") as f:
            f.write(json.dumps(runs, indent=2, default=str))
    if n_runs > 1:
        text = summary(runs)
        with open("eval_summary.md", "w", encoding="utf-8") as f:
            f.write(text)
        print(text)


if __name__ == "__main__":
    main()
