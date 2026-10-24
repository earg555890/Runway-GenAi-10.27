"""Live evaluation of Ask Runway: 10 realistic questions against the real NVIDIA models (not part of pytest).

    .venv/Scripts/python eval_agent.py          # writes eval_results.md and eval_results.json

For each question: did PLAN pick the expected tool, is the verdict right, did every number and date pass
the check, do the key numbers appear in the answer. Expected verdicts and numbers come from the engine
(deterministic), run with the arguments a correct plan would have.
"""
import json
import time
from dataclasses import dataclass, field
from decimal import Decimal

import agent
import engine
import normalize

SUBS = None


@dataclass
class Case:
    question: str
    tool: str | None
    args: dict = field(default_factory=dict)
    numbers: list = field(default_factory=list)       # dollar amounts that must appear in the answer
    words: list = field(default_factory=list)         # phrases that must appear (case-insensitive)


CASES = [
    Case(agent.SUGGESTED[0], "can_afford", {"item": "flight home", "cost": 400, "date": "2026-11-10"},
         ["5.81", "1850.00", "23.98"]),
    Case(agent.SUGGESTED[1], "runway", {}, ["359.53"], ["Nov 9"]),
    Case(agent.SUGGESTED[2], "find_leaks", {}, ["22.98", "23.98"]),
    Case("What if I pick up a 5 hour shift on Nov 7?", "what_if",
         {"extra_shifts": [{"date": "2026-11-07", "hours": 5}]}, ["71.69"]),
    Case("Can I afford new headphones for $150?", "can_afford", {"item": "headphones", "cost": 150}, [],
         ["Oct 27"]),
    Case("Can I put a $120 concert ticket on my credit card on Nov 20?", "can_afford",
         {"item": "concert ticket", "cost": 120, "date": "2026-11-20", "account": "card"}, []),
    Case("What's the capital of France?", None),
    Case("am I ok?", "runway", {}, [], ["Nov 9"]),
    Case("Why is my refund on hold?", "refund_status", {}, ["1850.00"]),
    Case("Is there a week coming up where money gets really tight?", "cash_crunches", {}, ["200.00", "114.70"]),
]


def expected_verdict(case, ds):
    if case.tool is None:
        return None
    plan = agent.parse_plan({"intent": "x", "tool": case.tool, "args": case.args}, SUBS)
    return agent.execute(plan, engine.Scenario(), ds).verdict


def main():
    global SUBS
    ds = normalize.load()
    SUBS = [s.merchant for s in engine.subscriptions(ds)]
    rows, results = [], []
    for i, case in enumerate(CASES, start=1):
        start = time.perf_counter()
        a = agent.ask(case.question, engine.Scenario(), ds=ds, mode="live")
        wall = time.perf_counter() - start
        want = expected_verdict(case, ds)
        amounts = {abs(v) for _, v in agent.find_amounts(a.text)}
        tool_ok = a.plan["tool"] == case.tool
        verdict_ok = a.verdict == want
        check_ok = bool(a.check.get("ok")) if case.tool else True
        numbers_ok = all(Decimal(n) in amounts for n in case.numbers) and \
            all(wd.lower() in a.text.lower() for wd in case.words)
        llm_ok = a.mode in ("live", "off_topic") and a.explain_source in ("llm", "none")
        passed = tool_ok and verdict_ok and check_ok and numbers_ok and llm_ok
        r = dict(n=i, question=case.question, expected_tool=case.tool, tool=a.plan["tool"], plan_source=a.plan["source"],
                 expected_verdict=want, verdict=a.verdict, check_ok=a.check.get("ok"), problems=a.check.get("problems"),
                 numbers_ok=numbers_ok, mode=a.mode, explain_source=a.explain_source, retries=a.retries,
                 timings=a.timings, wall_s=round(wall, 1), passed=passed, answer=a.text, notes=a.notes)
        results.append(r)
        print(json.dumps({k: r[k] for k in ("n", "tool", "verdict", "check_ok", "numbers_ok", "passed", "timings")}),
              flush=True)
        mark = lambda ok: "yes" if ok else "NO"     # noqa: E731
        rows.append(f"| {i} | {case.question} | {case.tool or 'none (off-topic)'} / {mark(tool_ok)} | "
                    f"{want or '-'} / {mark(verdict_ok)} | {mark(check_ok)} | {mark(numbers_ok)} | "
                    f"{a.retries['plan_json']}+{a.retries['explain_rewrite']} | {a.timings.get('plan_s', '-')} | "
                    f"{a.timings.get('explain_s', '-')} | {a.timings.get('total_s', '-')} | "
                    f"{'PASS' if passed else 'FAIL'} |")
    score = sum(r["passed"] for r in results)
    table = ("| # | Question | Tool / right? | Verdict / right? | Check passed | Key numbers | Retries (plan+explain) "
             "| PLAN s | EXPLAIN s | Total s | Result |\n|---|---|---|---|---|---|---|---|---|---|---|\n"
             + "\n".join(rows))
    report = f"# Ask Runway live evaluation\n\nScore: **{score}/{len(CASES)}**\n\n{table}\n"
    open("eval_results.md", "w", encoding="utf-8").write(report)
    open("eval_results.json", "w", encoding="utf-8").write(json.dumps(results, indent=2, default=str))
    print(report)


if __name__ == "__main__":
    main()
