"""Behind the scenes (for judges): where the data came from, every calculation, and a live Zetaris query."""
import pandas as pd
import streamlit as st

import config

from ui import data, explain, live_zetaris, provider


def sources(ds):
    if ds.backend.startswith("mydata"):
        st.markdown("#### Your data")
        ev = ds.evidence[0] if ds.evidence else None
        st.markdown(fmt_rows(ds, ev))
        return
    st.markdown(f"#### Maya's {len(data.SOURCES)} data sources")
    st.caption("Each source stays separate. Runway reads them through named queries, "
               + ("from local copies of the files." if ds.backend == "local" else "federated by Zetaris."))
    counts = data.rows_per_source(ds)
    where = {"local": "local file", "zetaris": "Zetaris", "zetaris-cached": "Zetaris (cached)"}
    cols = st.columns(3)
    for i, (source, name) in enumerate(data.SOURCES.items()):
        backends = sorted({where.get(ev.backend, ev.backend) for ev in ds.evidence if source in ev.sources})
        dot = ":green[●]" if counts[source] else ":red[●]"
        cols[i % 3].markdown(f"{dot} **{name}**  \n:gray[{counts[source]} records · {', '.join(backends)}]")


def answers():
    st.markdown("#### Ask Runway")
    st.caption(f"Answer mode: **{config.ANSWER_MODE}** (live = always ask the models; cached = reuse a saved answer "
               "for the same question and what-ifs; replay = saved answers only, typed out). PLAN model: "
               f"`{config.NVIDIA_PLAN_MODEL}` (thinking off). EXPLAIN model: the same, thinking off (fast, the "
               f"default); with Think harder, `{config.think_model()}` (thinking on). All through "
               + ("Meterless Nightshift. " if config.AI_PROVIDER == "meterless" else "the NVIDIA API. ")
               + "At most two model calls per question, plus one rewrite if the number check fails.")
    history = [a for a in st.session_state.get("history") or [] if a.mode != "event"]
    if not history:
        st.caption("No questions asked yet.")
        return
    rows = []
    for a in history:
        t = a.timings
        how = {"live": "live", "cached": "cached (original timings)", "replay": "replayed (original timings)",
               "fallback": "fallback (no AI)" if a.explain_source == "template" else "fallback (keywords)",
               "off_topic": "off-topic (one model call)",
               "no_key": "not answered (no saved answer; live answers need a key)"}.get(a.mode, a.mode)
        rows.append({"question": a.question, "answer came from": how, "plan": a.plan.get("tool") or "none",
                     "plan by": a.plan.get("source"), "PLAN s": t.get("plan_s"), "math s": t.get("execute_s"),
                     "EXPLAIN s": t.get("explain_s"), "total s": t.get("total_s"),
                     "retries (plan JSON / rewrite)": f"{a.retries.get('plan_json', 0)} / "
                                                      f"{a.retries.get('explain_rewrite', 0)}",
                     "written by": ((a.models.get("answered_by_call") or {}).get("routed_model")
                                    or a.models.get("answered_by") or "-"),
                     "provider": (a.models.get("answered_by_call") or {}).get("provider") or "-",
                     "number check": "passed" if a.check.get("ok") else ("failed" if a.check else "-")})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def action_log():
    st.markdown("#### Actions")
    st.caption("What Runway prepared for Maya, and what she approved or marked done. Runway never sends, buys or "
               "cancels anything itself: every action is a click by the student.")
    log = st.session_state.get("action_log") or []
    if not log:
        st.caption("Nothing yet.")
        return
    words = {"prepared": "Runway prepared", "approved": "Maya approved", "done": "Maya marked done",
             "undone": "Maya undid"}
    st.dataframe(pd.DataFrame([{"when": x["when"], "who": words.get(x["kind"], x["kind"]), "what": x["what"]}
                               for x in reversed(log)]), hide_index=True, width="stretch",
                 column_config={"what": st.column_config.TextColumn(width="large")})


def fmt_rows(ds, ev):
    where = "Zetaris (RUNWAY_MYDATA)" if ds.backend.endswith("zetaris") else "the local file in user_data/"
    return (f":green[●] **Your bank file**  \n:gray[{len(ds.checking_txns)} transactions, read from {where}"
            + (f" in {ev.duration_s:.2f} s" if ev else "") + ". It stays on this computer.]")


def render(ledger, ds):
    with st.expander("Behind the scenes", icon=":material/engineering:"):
        sources(ds)
        st.divider()
        action_log()
        st.divider()
        provider.render()
        st.divider()
        answers()
        st.divider()
        explain.render(ledger, ds)
        st.divider()
        if not ds.backend.startswith("mydata"):
            live_zetaris.render()
