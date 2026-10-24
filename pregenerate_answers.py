"""Pre-generate cached Ask Runway answers for the suggested questions (live NVIDIA calls).

    .venv/Scripts/python pregenerate_answers.py

Each question is answered twice: with nothing changed, and with the "Do these" fixes applied (refund form
sent tomorrow + Spotify cancelled), matching the what-ifs the UI builds. Answers that fail the number
check are retried (up to 3 tries) and never cached. Saved in config.ANSWER_CACHE_DIR; ANSWER_MODE=cached
or replay then serves them.
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


def main():
    ds = normalize.load()
    failed = 0
    for name, scenario in SCENARIOS.items():
        for q in agent.SUGGESTED:
            for attempt in range(1, 4):
                a = agent.ask(q, scenario, ds=ds, mode="live")
                saved = a.mode == "live" and a.check.get("ok")
                print(f"[{name}] {q}\n  try {attempt}: {a.mode}, check {'ok' if a.check.get('ok') else a.check}, "
                      f"{a.timings}, {'saved' if saved else 'NOT saved'}", flush=True)
                if saved:
                    break
            else:
                failed += 1
    total = len(SCENARIOS) * len(agent.SUGGESTED)
    print(f"\n{total - failed}/{total} answers cached in {config.ANSWER_CACHE_DIR}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
