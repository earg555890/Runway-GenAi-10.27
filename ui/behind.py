"""Behind the scenes (for judges): where the data came from, every calculation, and a live Zetaris query."""
import pandas as pd
import streamlit as st

import config

from ui import data, explain, live_zetaris


def sources(ds):
    st.markdown("#### Maya's six data sources")
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
               f"`{config.NVIDIA_PLAN_MODEL}` (thinking off). EXPLAIN model: `{config.NVIDIA_EXPLAIN_MODEL}` "
               "(thinking on). At most two model calls per question, plus one rewrite if the number check fails.")
    history = st.session_state.get("history") or []
    if not history:
        st.caption("No questions asked yet.")
        return
    rows = []
    for a in history:
        t = a.timings
        how = {"live": "live", "cached": "cached (original timings)", "replay": "replayed (original timings)",
               "fallback": "fallback (no AI)" if a.explain_source == "template" else "fallback (keywords)",
               "off_topic": "off-topic (one model call)"}.get(a.mode, a.mode)
        rows.append({"question": a.question, "answer came from": how, "plan": a.plan.get("tool") or "none",
                     "plan by": a.plan.get("source"), "PLAN s": t.get("plan_s"), "math s": t.get("execute_s"),
                     "EXPLAIN s": t.get("explain_s"), "total s": t.get("total_s"),
                     "retries (plan JSON / rewrite)": f"{a.retries.get('plan_json', 0)} / "
                                                      f"{a.retries.get('explain_rewrite', 0)}",
                     "number check": "passed" if a.check.get("ok") else ("failed" if a.check else "-")})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def render(ledger, ds):
    with st.expander("Behind the scenes", icon=":material/engineering:"):
        sources(ds)
        st.divider()
        answers()
        st.divider()
        explain.render(ledger, ds)
        st.divider()
        live_zetaris.render()
