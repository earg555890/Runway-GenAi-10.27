"""Pre-generate the committed demo answers in demo_answers/ (live NVIDIA calls).

    .venv/Scripts/python pregenerate_answers.py            # all of them
    .venv/Scripts/python pregenerate_answers.py "money last"   # only questions containing this text
    .venv/Scripts/python pregenerate_answers.py "leaking" "nothing changed"   # ...and only this what-if

Each suggested question is answered twice: with nothing changed, and with the "Do these" fixes applied (refund
form sent tomorrow + Spotify cancelled), matching the what-ifs the UI builds. The extra-shift question is
answered once, with nothing changed. Answers that fail the number check, that a fallback model wrote, or that
stop mid-sentence (the model ran out of output) are retried (up to 3 tries) and never saved. Reasoning traces
are trimmed to keep the files small. ANSWER_MODE=replay serves only these files; cached serves .cache/answers/ first, then these.
"""
import sys
from datetime import timedelta

import agent
import config
import engine
import normalize

SCENARIOS = {
    "nothing changed": engine.Scenario(refund_submit_date=config.DEMO_TODAY + timedelta(days=1)),
    "fixes applied": engine.Scenario(refund_released=True, refund_submit_date=config.DEMO_TODAY + timedelta(days=1),
                                     cancel_subscriptions=("Spotify",)),
}
EXTRA = [("What if I pick up a 5 hour shift on Nov 7?", "nothing changed")]
REASONING_HEAD, REASONING_TAIL = 2000, 1000          # characters of the reasoning trace kept


def trim(reasoning):
    if len(reasoning) <= REASONING_HEAD + REASONING_TAIL:
        return reasoning
    return (reasoning[:REASONING_HEAD].rstrip() + "\n\n[... trimmed for the repo ...]\n\n"
            + reasoning[-REASONING_TAIL:].lstrip())


def main():
    ds = normalize.load()
    only = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    only_scenario = sys.argv[2] if len(sys.argv) > 2 else None
    jobs = [(q, name) for q, name in [(q, name) for name in SCENARIOS for q in agent.SUGGESTED] + EXTRA
            if only in q.lower() and only_scenario in (None, name)]
    failed = 0
    for q, name in jobs:
        for attempt in range(1, 4):
            a = agent.ask(q, SCENARIOS[name], ds=ds, mode="live")
            saved = (a.mode == "live" and a.check.get("ok")
                     and a.models.get("answered_by") == config.NVIDIA_EXPLAIN_MODEL       # not a fallback model
                     and a.text.rstrip()[-1:] in ".!?])")                                # not cut off
            print(f"[{name}] {q}\n  try {attempt}: {a.mode}, check {'ok' if a.check.get('ok') else a.check}, "
                  f"{a.timings}, by {a.models.get('answered_by')}, {'saved' if saved else 'NOT saved'}", flush=True)
            if saved:
                a.reasoning = trim(a.reasoning)
                agent.save_cached(a, SCENARIOS[name], config.DEMO_ANSWERS_DIR)
                break
        else:
            failed += 1
    print(f"\n{len(jobs) - failed}/{len(jobs)} answers saved in {config.DEMO_ANSWERS_DIR}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
