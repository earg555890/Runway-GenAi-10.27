"""Live evaluation of Ask Runway: 20 realistic questions against the real NVIDIA models (not part of pytest).

    .venv/Scripts/python eval_agent.py                       # one fast run -> eval_results.md / eval_results.json
    .venv/Scripts/python eval_agent.py fast,fast,think 240   # 3 runs (fast, fast, Think harder), 240 s apart
                                                             #   -> also eval_summary.md
    .venv/Scripts/python eval_agent.py fast,think 0 "this week"   # only questions containing this text (and the
                                                             #   ones they follow) -> .cache/eval_one.json only

For each question: did PLAN pick the expected tool(s) (and, for follow-ups, the right arguments), is the verdict
right, did the answer pass every check (numbers, dates, citations, reasons, repetition, cut-off), did the model
itself write every required fact (agent.required_facts: the same table the app enforces), and did a Nemotron
model write it (not the quick answer standing in). Follow-ups are asked after the question they follow, with that
answer as the conversation so far. Expected verdicts come from the engine (deterministic). Before each run the
script waits until the endpoint answers a tiny request.
"""
import json
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import agent
import config
import engine
import llm_client
import normalize

SUBS = None
FLIGHT = "Can I afford a $400 flight home for Thanksgiving if I book it Nov 10?"


@dataclass
class Case:
    question: str
    tools: tuple                  # expected tool(s), in any order; () = off-topic
    args: dict = field(default_factory=dict)     # expected args of the first call (only the ones given are checked)
    after: str | None = None      # a follow-up to this earlier question (asked first, in the same run)
    new: bool = False             # one of the 10 questions added for the chat version


CASES = [
    Case(FLIGHT, ("can_afford",), {"cost": "400.00", "date": "2026-11-10"}),
    Case(agent.SUGGESTED[1], ("runway",)),
    Case(agent.SUGGESTED[2], ("find_leaks",)),
    Case("What if I pick up a 5 hour shift on Nov 7?", ("what_if",)),
    Case("Can I afford new headphones for $150?", ("can_afford",), {"cost": "150.00"}),
    Case("Can I put a $120 concert ticket on my credit card on Nov 20?", ("can_afford",),
         {"cost": "120.00", "date": "2026-11-20", "account": "card"}),
    Case("What's the capital of France?", ()),
    Case("am I ok?", ("runway",)),
    Case("Why is my refund on hold?", ("refund_status",)),
    Case("Is there a week coming up where money gets really tight?", ("cash_crunches",)),
    Case("How much did I spend on each category in October?", ("spending_summary",), {"start": "2026-10-01"},
         new=True),
    Case("How much did I spend at Kroger?", ("find_transactions",), {"query": "kroger"}, new=True),
    Case("What bills are due next week?", ("upcoming_bills",), new=True),
    Case("How many hours did I work in October?", ("work_summary",), {"start": "2026-10-01"}, new=True),
    Case("What will my balance be on Thanksgiving?", ("balance_on",), {"date": "2026-11-26"}, new=True),
    Case("What can I do to make money before this?", ("money_ideas",), after=agent.SUGGESTED[1], new=True),
    Case("what about Nov 17 instead?", ("can_afford",), {"cost": "400.00", "date": "2026-11-17"}, after=FLIGHT,
         new=True),
    Case("Help me get through the semester", ("runway", "money_ideas", "find_leaks"), new=True),
    Case("What is FAFSA verification?", ("general_info",), new=True),
    Case("money stuff is stressing me out", ("runway",), new=True),
    Case("What should I do this week?", ("action_plan",), {"start": "2026-10-26", "end": "2026-11-01"}, new=True),
]


def expected_verdict(case, ds):
    if not case.tools or case.tools == ("general_info",):
        return None
    calls = [{"tool": t, "args": dict(case.args) if i == 0 else {}} for i, t in enumerate(case.tools)]
    if case.tools[0] == "what_if":
        calls[0]["args"] = {"extra_shifts": [{"date": "2026-11-07", "hours": 5}]}
    if case.tools[0] == "can_afford":
        calls[0]["args"] = {"item": "it", **{k: v for k, v in case.args.items()}}
    plan = agent.parse_plan({"calls": calls}, SUBS)
    results = agent.execute_all(plan, engine.Scenario(), ds)
    return next((r.verdict for r in results if r.verdict), None)


def _args_ok(case, plan):
    if not case.args or not plan.get("calls"):
        return True
    got = plan["calls"][0]["args"]
    return all(str(got.get(k, "")).lower() == str(v).lower() for k, v in case.args.items())


def healthy(think, tries=10, wait_s=60):
    """Wait until the endpoint answers a tiny request (it has bad spells)."""
    model = config.NVIDIA_EXPLAIN_MODEL if think else config.NVIDIA_PLAN_MODEL
    for _ in range(tries):
        try:
            s = llm_client.stream_chat([{"role": "user", "content": "Say OK."}], thinking=False, retries=0, timeout=60,
                                       model=model)
            if "".join(c for k, c in s if k == "text").strip():
                return True
        except Exception as exc:
            print(f"  endpoint not healthy ({type(exc).__name__}), waiting {wait_s} s", flush=True)
        time.sleep(wait_s)
    return False


def run_once(ds, run_no, think, cases=None):
    results, answers = [], {}
    for i, case in enumerate(cases or CASES, start=1):
        start = time.perf_counter()
        history = [answers[case.after]] if case.after else []
        a = agent.ask(case.question, engine.Scenario(), ds=ds, mode="live", history=history, think=think)
        answers[case.question] = a
        want = expected_verdict(case, ds)
        tools = tuple(c["tool"] for c in a.plan.get("calls") or [])
        tool_ok = sorted(tools) == sorted(case.tools) and _args_ok(case, a.plan)
        verdict_ok = a.verdict == want
        check_ok = bool(a.check.get("ok")) if case.tools else True
        facts = a.facts or []
        appended = [f["label"] for f in facts if f["appended"]]
        facts_ok = not appended                                   # every required fact written by the model itself
        nvidia_error = bool(a.models.get("explain_errors")) and a.explain_source == "template" \
            or a.plan["source"] == "keywords"
        model_answer = not case.tools or a.explain_source == "llm"
        passed = tool_ok and verdict_ok and check_ok and facts_ok and model_answer
        r = dict(run=run_no, think=think, n=i, question=case.question, new=case.new, after=case.after,
                 expected_tools=list(case.tools), tools=list(tools), plan_source=a.plan["source"],
                 resolved=a.plan.get("resolved_question"), expected_verdict=want, verdict=a.verdict, tool_ok=tool_ok,
                 verdict_ok=verdict_ok, check_ok=check_ok, problems=a.check.get("problems"), facts_ok=facts_ok,
                 facts=len(facts), appended=appended, rewrites=a.retries.get("explain_rewrite", 0),
                 answered_by=a.models.get("answered_by"), explain_errors=a.models.get("explain_errors"),
                 source=a.explain_source, nvidia_error=nvidia_error, passed=passed, mode=a.mode, retries=a.retries,
                 timings=a.timings, wall_s=round(time.perf_counter() - start, 1), answer=a.text, quick=a.quick,
                 notes=a.notes)
        results.append(r)
        print(json.dumps({k: r[k] for k in ("run", "n", "tools", "verdict", "check_ok", "facts_ok", "answered_by",
                                            "source", "passed", "timings")}), flush=True)
    return results


def _yes(ok):
    return "yes" if ok else "NO"


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    return xs[len(xs) // 2] if xs else None


def table(results):
    rows = [f"| {r['n']} | {r['question']}{' *(follow-up)*' if r['after'] else ''} | "
            f"{', '.join(r['expected_tools']) or 'none (off-topic)'} / {_yes(r['tool_ok'])} | "
            f"{r['expected_verdict'] or '-'} / {_yes(r['verdict_ok'])} | {_yes(r['check_ok'])} | "
            f"{('all ' + str(r['facts'])) if not r['appended'] else (str(len(r['appended'])) + ' added')} | "
            f"{agent.model_name(r['answered_by']) if r['expected_tools'] else '-'} | "
            f"{r['retries']['plan_json']}+{r['retries'].get('explain_rewrite', 0)} | "
            f"{r['timings'].get('quick_s', '-')} | {r['timings'].get('total_s', '-')} | "
            f"{'PASS' if r['passed'] else 'FAIL'} |" for r in results]
    head = ("| # | Question | Tools / right? | Verdict / right? | Checks passed | Required facts by model | "
            "Written by | Retries (plan+rewrite) | Quick answer s | Full answer s | Result |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|\n")
    return head + "\n".join(rows)


def _mistake(r):
    if not r["tool_ok"]:
        return f"picked {', '.join(r['tools']) or 'no tool'}" + (" with the wrong arguments" if
                                                                 sorted(r["tools"]) == sorted(r["expected_tools"])
                                                                 else "")
    if not r["verdict_ok"]:
        return "gave the wrong verdict"
    if not r["check_ok"]:
        return "failed a check: " + "; ".join((r["problems"] or [])[:2])
    if r["source"] != "llm" and r["expected_tools"]:
        return "the AI answer didn't pass the checks, so the quick answer stood in (" + \
            "; ".join(n for n in r["notes"] if "didn't pass" in n)[:160] + ")"
    return "left out a required fact (Runway added it: " + ", ".join(r["appended"]) + ")"


def mode_block(runs, think):
    allr = [r for run in runs for r in run if r["think"] == think]
    if not allr:
        return []
    n, k = len(allr), len([run for run in runs if run and run[0]["think"] == think])

    def count(key):
        return sum(bool(r[key]) for r in allr)

    fails = [r for r in allr if not r["passed"]]
    nvidia = [r for r in fails if r["nvidia_error"]]
    real = [r for r in fails if not r["nvidia_error"]]
    quick = _median(r["timings"].get("quick_s") for r in allr)
    full = _median(r["timings"].get("total_s") for r in allr if r["expected_tools"])
    name = ("Think harder (Nemotron Super, thinking on)" if think else
            "Fast (Nemotron Lightning, thinking off; the default)")
    lines = [f"## {name}: {count('passed')}/{n} full answers ({k} run{'s' if k != 1 else ''})", "",
             f"- **Picked the right tool(s):** {count('tool_ok')}/{n}",
             f"- **Gave the right verdict:** {count('verdict_ok')}/{n}",
             f"- **Passed every check** (numbers, dates, reasons, no repeats, not cut off): {count('check_ok')}/{n}",
             f"- **Full answers** (all of the above, written by the model with every required fact): "
             f"{count('passed')}/{n}",
             f"- Answers that needed one rewrite: {sum(1 for r in allr if r['rewrites'])}/{n}",
             f"- Answers where the quick answer stood in for the AI answer: "
             f"{sum(1 for r in allr if r['expected_tools'] and r['source'] != 'llm')}/{n}",
             f"- **Quick answer:** {quick} s median after sending. **Full AI answer:** {full} s median.", ""]
    if fails:
        lines.append(f"Not full answers: {len(nvidia)} because of NVIDIA service errors, {len(real)} because of "
                     "real mistakes" + (":" if real else "."))
        lines += [f"  - Run {r['run']}, \"{r['question']}\": {_mistake(r)}" for r in real]
        lines.append("")
    return lines


def summary(runs):
    total = sum(len(run) for run in runs)
    lines = ["# Ask Runway: how well it answers", "",
             f"We asked Runway {len(CASES)} realistic student questions (the original 10, plus "
             f"{sum(c.new for c in CASES)} new ones: spending, transactions, bills, work hours, a balance on a date, "
             "two follow-ups, a multi-step plan, a general question, a vague one and \"what should I do this "
             f"week?\"), {len(runs)} separate times ({total} answers in all), using the "
             "real NVIDIA Nemotron models. Every answer was graded automatically against numbers that Runway's money "
             "engine computes on its own. Follow-ups were asked after the question they follow, in the same chat.",
             "",
             "The model never does the math: Runway's engine computes every number, shows a quick answer from those "
             "numbers right away, and a checker rejects any AI answer with an amount, date or reason that doesn't "
             "match the student's records.", ""]
    for think in (False, True):
        lines += mode_block(runs, think)
    for i, run in enumerate(runs, start=1):
        mode = "Think harder" if run and run[0]["think"] else "Fast"
        lines += [f"## Run {i} ({mode}): {sum(r['passed'] for r in run)}/{len(run)} full answers", "", table(run), ""]
    return "\n".join(lines)


def main():
    global SUBS
    modes = (sys.argv[1] if len(sys.argv) > 1 else "fast").split(",")
    gap_s = int(sys.argv[2]) if len(sys.argv) > 2 else 240
    only = sys.argv[3].lower() if len(sys.argv) > 3 else ""
    picked = [c for c in CASES if only in c.question.lower()]
    cases = [c for c in CASES if c in picked or any(p.after == c.question for p in picked)] if only else None
    ds = normalize.load()
    SUBS = [s.merchant for s in engine.subscriptions(ds)]
    config.ANSWER_CACHE_DIR = Path(tempfile.mkdtemp(prefix="runway-eval-"))       # keep the app cache clean
    print(f"models: plan {config.NVIDIA_PLAN_MODEL}, modes {modes}", flush=True)
    runs = []
    for run_no, mode in enumerate(modes, start=1):
        think = mode.strip() == "think"
        if run_no > 1:
            time.sleep(gap_s)
        if not healthy(think):
            print("endpoint still unhealthy; running anyway", flush=True)
        runs.append(run_once(ds, run_no, think, cases))
        last = runs[-1]
        if only:                                       # a spot check: never overwrite the full results
            Path(".cache").mkdir(exist_ok=True)
            Path(".cache/eval_one.json").write_text(json.dumps(runs, indent=2, default=str), encoding="utf-8")
            continue
        with open("eval_results.md", "w", encoding="utf-8") as f:
            f.write(f"# Ask Runway live evaluation (latest run, {mode})\n\nScore: **{sum(r['passed'] for r in last)}/"
                    f"{len(last)}**\n\n{table(last)}\n")
        with open("eval_results.json", "w", encoding="utf-8") as f:
            f.write(json.dumps(runs, indent=2, default=str))
    if len(runs) > 1 and not only:
        text = summary(runs)
        with open("eval_summary.md", "w", encoding="utf-8") as f:
            f.write(text)
        print(text)


if __name__ == "__main__":
    main()
