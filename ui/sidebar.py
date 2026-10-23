import streamlit as st

from ui import data, fmt


def render(ds):
    with st.sidebar:
        st.subheader("Maya Rivera")
        st.markdown("Sophomore at State University  \n"
                    "Lives off campus (shared 2-bedroom)  \n"
                    f"Campus cafe job, {fmt.money(ds.job.hourly_rate)}/hour")
        st.divider()
        st.markdown("**Connected sources**")
        counts = data.rows_per_source(ds)
        where = {"local": "local file", "zetaris": "Zetaris", "zetaris-cached": "Zetaris, cached"}
        for source, name in data.SOURCES.items():
            backends = {ev.backend for ev in ds.evidence if source in ev.sources}
            dot = ":green[●]" if counts[source] else ":red[●]"
            st.markdown(f"{dot} **{name}**  \n:gray[{counts[source]} rows · "
                        f"{', '.join(sorted(where.get(b, b) for b in backends))}]")
        st.caption("All data is synthetic. Runway never connects to a real bank.")
