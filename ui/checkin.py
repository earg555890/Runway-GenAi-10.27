"""The check-in, right under the status card: "Hi Maya. N things need your attention.", one friendly line, the
top 3 items as compact cards (title, one sentence, actions), and "See all" for the rest. Built from
engine.attention_items for what the student has actually done (not the what-ifs being explored)."""
import threading

import streamlit as st

import actions
import engine
import greeting
from ui import fmt

TOP = 3


@st.cache_resource(show_spinner=False)
def _lines():
    """{items signature: AI line or None} shared across reruns, filled by a background thread."""
    return {}


def _signature(items):
    return "|".join(f"{it.kind}:{it.due.value}" for it in items[:TOP])


def _start_greeting(items):
    store, sig = _lines(), _signature(items)
    if sig in store or not greeting.enabled():
        return
    store[sig] = "pending"

    def work():
        store[sig] = greeting.ai_line(items)

    threading.Thread(target=work, daemon=True).start()


def line(items):
    """The AI line if it's ready and passed its check, else the fixed one. Never waits."""
    got = _lines().get(_signature(items))
    return got if got and got != "pending" else greeting.fallback(items)


def heading(items):
    n = len(items)
    if not n:
        return "Hi Maya. You're all caught up."
    return f"Hi Maya. {fmt.things(n)} need{'s' if n == 1 else ''} your attention."


def _card(item, key):
    title, sentence = actions.text(item)
    with st.container(border=True, key=f"ci_card_{key}"):
        st.markdown(f'<div class="rw-ci-title">{fmt.html(title)}</div>'
                    f'<div class="rw-ci-text">{fmt.html(sentence)}</div>', unsafe_allow_html=True)


def _greeting_slot(items):
    if _lines().get(_signature(items)) == "pending":
        @st.fragment(run_every=1.5)
        def poll():
            if _lines().get(_signature(items)) != "pending":
                st.rerun(scope="app")
            st.markdown(f'<div class="rw-ci-line">{fmt.html(greeting.fallback(items))}</div>', unsafe_allow_html=True)
        poll()
    else:
        st.markdown(f'<div class="rw-ci-line">{fmt.html(line(items))}</div>', unsafe_allow_html=True)


def render(ds, done_scenario):
    items = engine.attention_items(done_scenario, ds)
    _start_greeting(items)
    with st.container(key="checkin"):
        st.markdown(f'<div class="rw-ci-head">{fmt.html(heading(items))}</div>', unsafe_allow_html=True)
        if items:
            _greeting_slot(items)
        cols = st.columns(TOP)
        for i, it in enumerate(items[:TOP]):
            with cols[i]:
                _card(it, it.kind)
        if len(items) > TOP:
            with st.expander(f"See all ({len(items) - TOP} more)"):
                for it in items[TOP:]:
                    _card(it, it.kind)
    return items
