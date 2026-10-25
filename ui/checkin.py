"""The check-in, right under the status card: "Hi Maya. N things need your attention.", one friendly line, the
top 3 items as compact cards (title, one sentence, actions), and "See all" for the rest. Built from
engine.attention_items for what the student has actually done (not the what-ifs being explored)."""
import threading

import streamlit as st

import actions
import engine
import greeting
from ui import fmt, state

TOP = 3
MIME_ICS = "text/calendar"


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


def _email(act, key):
    with st.popover("Email", icon=":material/mail:", type="tertiary"):
        st.markdown(f"**To:** {fmt.md(act.extra['to'])}  \n**Subject:** {fmt.md(act.extra['subject'])}")
        st.caption("A demo address: Maya's data is made up. Use your real financial aid office's address.")
        st.link_button(act.label, act.url, icon=":material/open_in_new:", key=f"ci_mail_{key}",
                       on_click=state.log, args=(f"Opened the email to {act.extra['to']} in the email app "
                                                 "(not sent by Runway)",))
        st.code(act.data, language=None, wrap_lines=True)
        st.caption("Or copy it with the button above. Runway never sends anything.")


def _actions(item, ds, key):
    """1-2 actions, then "mark as done". Each one is a click; nothing happens on its own."""
    with st.container(horizontal=True, gap="xsmall", key=f"ci_acts_{key}"):
        for act in actions.for_item(item, ds):
            if act.kind == "email":
                state.prepared(f"email-{key}", f"Email to {act.extra['to']}: \"{act.extra['subject']}\" (draft)")
                _email(act, key)
            elif act.kind == "cancel":
                state.prepared(f"cancel-{key}", f"Link to {act.extra['name']}'s official cancel page")
                st.link_button("Cancel page", act.url, icon=":material/open_in_new:", key=f"ci_cancel_{key}",
                               help=act.label, type="tertiary", on_click=state.log,
                               args=(f"Opened {act.extra['name']}'s cancel page",))
            elif act.kind == "calendar":
                state.prepared(f"cal-{key}", f"Calendar reminder: {act.extra['title']} ({fmt.day(act.extra['day'])})")
                st.download_button("Remind", act.data, file_name=act.file_name, mime=MIME_ICS, type="tertiary",
                                   icon=":material/event:", key=f"ci_cal_{key}", help="Add a reminder to your calendar",
                                   on_click=state.log,
                                   args=(f"Downloaded the calendar reminder: {act.extra['title']}",))
        st.button(actions.done_label(item), key=f"ci_done_{key}", icon=":material/check:",
                  help="Mark as done", on_click=state.mark_done, args=(item, ds))


def card(item, ds, key, compact=False):
    """Title, one sentence, actions. compact (under a chat answer that already says it): title and actions."""
    title, sentence = actions.text(item)
    with st.container(border=True, key=f"ci_card_{key}"):
        st.markdown(f'<div class="rw-ci-title">{fmt.html(title)}</div>'
                    + ("" if compact else f'<div class="rw-ci-text">{fmt.html(sentence)}</div>'),
                    unsafe_allow_html=True)
        _actions(item, ds, key)


def _done_buttons():
    """What was marked done, each with Undo (in the row under the cards)."""
    for kind, d in (st.session_state.get("done") or {}).items():
        st.button(f"Done: {d['label']} · Undo", key=f"ci_undo_{kind}", type="tertiary", icon=":material/undo:",
                  on_click=state.undo, args=(kind,), help=f"Undo \"{d['label']}\"")


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


def pending(ds, done_scenario):
    """Items still open: fixes marked done are already out (the scenario has them); others are filtered here."""
    done = st.session_state.get("done") or {}
    return [it for it in engine.attention_items(done_scenario, ds) if it.kind not in done]


def render(ds, done_scenario):
    items = pending(ds, done_scenario)
    _start_greeting(items)
    with st.container(key="checkin"):
        st.markdown(f'<div class="rw-ci-head">{fmt.html(heading(items))}</div>', unsafe_allow_html=True)
        if items:
            _greeting_slot(items)
        with st.container(key="ci_top"):              # on a phone: one row you swipe through (style.py)
            cols = st.columns(TOP)
            for i, it in enumerate(items[:TOP]):
                with cols[i]:
                    card(it, ds, it.kind)
        with st.container(horizontal=True, gap="small", vertical_alignment="center", key="ci_more"):
            if len(items) > TOP:
                with st.expander(f"See all ({len(items) - TOP} more)"):
                    for it in items[TOP:]:
                        card(it, ds, it.kind)
            if items:
                st.download_button("Add all deadlines to my calendar", actions.all_deadlines(items),
                                   file_name="runway-deadlines.ics", mime=MIME_ICS, icon=":material/calendar_add_on:",
                                   type="tertiary", key="ci_cal_all", on_click=state.log,
                                   args=(f"Downloaded all {len(items)} deadlines as one calendar file",))
            _done_buttons()
    return items
