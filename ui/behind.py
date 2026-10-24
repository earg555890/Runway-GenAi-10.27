"""Behind the scenes (for judges): where the data came from, every calculation, and a live Zetaris query."""
import streamlit as st

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


def render(ledger, ds):
    with st.expander("Behind the scenes", icon=":material/engineering:"):
        sources(ds)
        st.divider()
        explain.render(ledger, ds)
        st.divider()
        live_zetaris.render()
