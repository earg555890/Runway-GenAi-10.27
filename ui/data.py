"""Loading Maya's data once (shared by every session), with visible per-source progress."""
import socket
import time

import streamlit as st

import config
import data_access as da
import normalize

SOURCES = {
    "checking": "Checking account",
    "card": "Credit card",
    "aid": "Financial aid",
    "bursar": "Student account (bursar)",
    "lease": "Lease",
    "shifts": "Campus job shifts",
}


@st.cache_resource(show_spinner=False)
def _store():
    return {}


def _run_all(backend, box):
    results = {}
    for name, params in normalize.queries():
        q = da.REGISTRY[name]
        src = ", ".join(SOURCES[s] for s in sorted({s for s, _ in q.tables}))
        line = box.empty()
        line.markdown(f":hourglass_flowing_sand: **{src}**: {q.description}")
        start = time.perf_counter()
        results[name] = da.run(name, backend=backend, **params)
        ev = results[name].evidence
        line.markdown(f":white_check_mark: **{src}**: {len(ev.row_ids)} rows, {time.perf_counter() - start:.1f} s "
                      f"({ev.backend})")
    return normalize.build(results, backend)


def load_dataset():
    """The Dataset for config.DATA_BACKEND, loaded on first use. On Zetaris this also warms the query
    cache with normalize.queries(). Falls back to local files if Zetaris fails. Returns (ds, note)."""
    store, backend = _store(), config.DATA_BACKEND
    if backend not in store:
        where = "Zetaris" if backend == "zetaris" else "local files"
        with st.status(f"Loading Maya's six sources from {where}...", expanded=True) as status:
            if backend == "zetaris":
                st.caption("The first load from Zetaris takes about a minute on this laptop; after that it is cached.")
            try:
                ds, note = _run_all(backend, status), None
            except Exception as exc:              # Zetaris down: the local files are the fallback (rule 4)
                note = f"Zetaris was not reachable ({type(exc).__name__}), so Runway is using the local files."
                st.warning(note)
                ds = _run_all("local", status)
            status.update(label=f"Loaded Maya's data ({len(ds.evidence)} queries)", state="complete", expanded=False)
        store[backend] = (ds, note)
    return store[backend]


def backend_label(ds):
    if ds.backend == "local":
        return "Local files"
    if all(ev.backend == "zetaris-cached" for ev in ds.evidence):
        return "Zetaris (cached)"
    return "Data via Zetaris"


def rows_per_source(ds):
    counts = {s: 0 for s in SOURCES}
    for ev in ds.evidence:
        for s in ev.sources:
            counts[s] += len(ev.row_ids)
    return counts


def zetaris_address():
    url = config.ZETARIS_JDBC_URL or ""
    host, _, port = url.rsplit("@", 1)[-1].partition(":")
    return host, int(port) if port.isdigit() else None


@st.cache_data(ttl=30, show_spinner=False)
def zetaris_reachable():
    host, port = zetaris_address()
    if not host or not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False
