"""One-question health check before recording the live demo: asks Runway "How long will my money last?" live, in
fast mode, on Maya's local files, and prints whether the AI answer came back and passed the checks, and how long it
took. Exit code 0 = ready, 1 = the NVIDIA endpoint is slow or failing right now (try again in a few minutes).

    .venv/Scripts/python demo_check.py
"""
import sys

import agent
import config
import engine
import normalize

QUESTION = "How long will my money last?"
SLOW_S = 10


def main():
    if not config.NVIDIA_API_KEY:
        print("NVIDIA check: no NVIDIA_API_KEY in .env, so live answers can't work.")
        return 1
    ds = normalize.load()
    answer = None
    for kind, payload in agent.run(QUESTION, engine.Scenario(), ds=ds, mode="live", typing_s=0):
        if kind == "answer":
            answer = payload
    t = answer.timings
    by = answer.models.get("answered_by") or "none"
    ok = answer.explain_source == "llm" and answer.check.get("ok") and t.get("total_s", 99) <= SLOW_S
    print(f"NVIDIA check: \"{QUESTION}\" quick answer {t.get('quick_s')} s, full answer {t.get('total_s')} s, "
          f"written by {agent.model_name(by) if by != 'template' else 'the quick answer (AI fallback)'}, "
          f"checks {'passed' if answer.check.get('ok') else 'FAILED'}.")
    print("NVIDIA check: READY to record." if ok else
          "NVIDIA check: NOT READY. The AI answer was slow or fell back. Wait a few minutes and run it again.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
