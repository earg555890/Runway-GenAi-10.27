"""Loading Maya's data once per server process, with one friendly progress line."""
import socket

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
    "shifts": "Work schedule",
}


@st.cache_resource(show_spinner=False)
def _store():
    return {}


def _source_of(name):
    return da.REGISTRY[name].tables[0][0]


def _run_all(backend, slot):
    queries = normalize.queries()
    uncached = backend == "zetaris" and not all(da.is_cached(q, **p) for q, p in queries)
    with slot.container():
        bar = st.progress(0.0, text="Connecting your accounts... 0 of 6")
        if uncached:
            st.caption("Connecting to Zetaris for the first time takes about a minute. After that it's instant.")
        results = {}
        for i, source in enumerate(SOURCES, start=1):
            for name, params in queries:
                if _source_of(name) == source:
                    results[name] = da.run(name, backend=backend, **params)
            bar.progress(i / len(SOURCES), text=f"Connecting your accounts... {i} of {len(SOURCES)}")
    return normalize.build(results, backend)


def load_dataset():
    """(Dataset, note). Loads every engine query on first use; on Zetaris that also fills the query cache.
    Falls back to the local files (with a note) if Zetaris fails."""
    store, backend = _store(), config.DATA_BACKEND
    if backend not in store:
        slot = st.empty()
        try:
            store[backend] = (_run_all(backend, slot), None)
        except Exception as exc:                 # Zetaris down: the local files are the fallback (rule 4)
            note = f"Couldn't reach Zetaris ({type(exc).__name__}), so this is running on the local copy of the data."
            store[backend] = (_run_all("local", slot), note)
        slot.empty()
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
