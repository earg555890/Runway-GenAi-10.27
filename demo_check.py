"""One-question health check before recording the live demo: the Meterless Nightshift checks (connection,
authorization, model discovery, text requests), then PocketMoney asks "How long will my money last?" live, in fast mode,
on Maya's local files, and prints which provider and model answered, whether it passed the checks, and how long it
took. Exit code 0 = ready, 1 = Nightshift or NVIDIA is slow or failing right now (try again in a few minutes).

    .venv/Scripts/python demo_check.py
"""
import sys

import agent
import config
import engine
import normalize

QUESTION = "How long will my money last?"
SLOW_S = 25                  # demo-friendly: a full answer within ~25 s


def main():
    if not config.ai_configured():
        print("NVIDIA check: no Meterless Runtime token (METERLESS_RUNTIME_TOKEN) and no NVIDIA key, so live answers "
              "can't work.")
        return 1
    if config.AI_PROVIDER == "meterless":
        import meterless
        r = meterless.run_checks([config.NVIDIA_PLAN_MODEL])
        st = r["status"]
        print(f"Nightshift: {st['base_url']} {st['state']} (healthz {r['healthz']}, wrong token -> "
              f"{r['wrong_token_state']}); {len(r['discovered_nemotron'])} Nemotron models discovered.")
    ds = normalize.load()
    answer = None
    for kind, payload in agent.run(QUESTION, engine.Scenario(), ds=ds, mode="live", typing_s=0):
        if kind == "answer":
            answer = payload
    t = answer.timings
    by = answer.models.get("answered_by") or "none"
    call = answer.models.get("answered_by_call")
    ok = answer.explain_source == "llm" and answer.check.get("ok") and t.get("total_s", 99) <= SLOW_S
    print(f"NVIDIA check: \"{QUESTION}\" quick answer {t.get('quick_s')} s, full answer {t.get('total_s')} s, "
          f"written by {agent.handled_by(call) if call and by != 'template' else 'the quick answer (AI fallback)'}, "
          f"checks {'passed' if answer.check.get('ok') else 'FAILED'}.")
    print("NVIDIA check: READY to record." if ok else
          "NVIDIA check: NOT READY. The AI answer was slow or fell back. Wait a few minutes and run it again.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
