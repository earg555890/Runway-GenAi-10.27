"""Optional AI lines (the check-in greeting, the Budget tab summary) computed in a background thread, so the page
never waits: the deterministic line shows at once and a small fragment swaps the AI line in when it's ready."""
import threading

import streamlit as st


@st.cache_resource(show_spinner=False)
def _store():
    """{key: "pending" | text | None} shared across reruns and sessions (keys say what the line is about)."""
    return {}


def start(key, work):
    """Run work() once per key in a background thread; it returns the AI line or None."""
    store = _store()
    if key in store:
        return
    store[key] = "pending"

    def run():
        try:
            store[key] = work()
        except Exception:
            store[key] = None

    threading.Thread(target=run, daemon=True).start()


def line(key, fallback):
    got = _store().get(key)
    return got if got and got != "pending" else fallback


def slot(key, fallback, show):
    """show(text) now with the AI line or the fallback; while the AI line is pending, poll every 1.5 s and rerun
    the page once it lands."""
    if _store().get(key) == "pending":
        @st.fragment(run_every=1.5)
        def poll():
            if _store().get(key) != "pending":
                st.rerun(scope="app")
            show(fallback)
        poll()
    else:
        show(line(key, fallback))
