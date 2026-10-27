"""The check-in, right under the status card: "Hi Maya. N things need your attention.", one friendly line, the
top 3 items as compact cards (title, one sentence, actions), and "See all" for the rest. Built from
engine.attention_items for what the student has actually done (not the what-ifs being explored)."""
import streamlit as st

import actions
import engine
import greeting
from ui import background, fmt, memory, state

TOP = 3
MIME_ICS = "text/calendar"


def _key(items):
    return "greeting|" + "|".join(f"{it.kind}:{it.due.value}" for it in items[:TOP])


def _start_greeting(items):
    if greeting.enabled() and items and not state.mine():      # her own data: no AI call she didn't ask for
        background.start(_key(items), lambda: greeting.ai_line(items))


def line(items):
    """The AI line if it's ready and passed its check, else the fixed one. Never waits."""
    return background.line(_key(items), greeting.fallback(items))


def heading(items, name="Maya", runs_out=False):
    hi = f"Hi {name}." if name else "Hi."
    n = len(items)
    if not n:
        return f"{hi} See the ways to fix it below." if runs_out else f"{hi} You're all caught up."
    return f"{hi} {fmt.things(n)} need{'s' if n == 1 else ''} your attention."


def _email(act, key, kind):
    with st.popover("Email", icon=":material/mail:", type="tertiary"):
        st.markdown(f"**To:** {fmt.md(act.extra['to'])}  \n**Subject:** {fmt.md(act.extra['subject'])}")
        st.caption("A demo address: Maya's data is made up. Use your real financial aid office's address.")
        st.link_button(act.label, act.url, icon=":material/open_in_new:", key=f"ci_mail_{key}",
                       on_click=state.opened, args=(kind, "email", act.extra["subject"],
                                                    f"Opened the email to {act.extra['to']} in the email app "
                                                    "(not sent by PocketMoney)"))
        st.code(act.data, language=None, wrap_lines=True)
        st.caption("Or copy it with the button above. PocketMoney never sends anything.")


def actions_row(item, ds, key):
    """1-2 actions, then "mark as done". Each one is a click; nothing happens on its own."""
    with st.container(horizontal=True, gap="xsmall", key=f"ci_acts_{key}"):
        for act in actions.for_item(item, ds):
            if act.kind == "email":
                state.prepared(f"email-{key}", f"Email to {act.extra['to']}: \"{act.extra['subject']}\" (draft)")
                _email(act, key, item.kind)
            elif act.kind == "cancel":
                state.prepared(f"cancel-{key}", f"Link to {act.extra['name']}'s official cancel page")
                st.link_button("Cancel page", act.url, icon=":material/open_in_new:", key=f"ci_cancel_{key}",
                               help=act.label, type="tertiary", on_click=state.opened,
                               args=(item.kind, "cancel", f"cancel {act.extra['name']}",
                                     f"Opened {act.extra['name']}'s cancel page"))
            elif act.kind == "calendar":
                state.prepared(f"cal-{key}", f"Calendar reminder: {act.extra['title']} ({fmt.day(act.extra['day'])})")
                st.download_button("Remind", act.data, file_name=act.file_name, mime=MIME_ICS, type="tertiary",
                                   icon=":material/event:", key=f"ci_cal_{key}", help="Add a reminder to your calendar",
                                   on_click=state.opened,
                                   args=(item.kind, "reminder", act.extra["title"],
                                         f"Downloaded the calendar reminder: {act.extra['title']}"))
        st.button(actions.done_label(item), key=f"ci_done_{key}", icon=":material/check:",
                  help="Mark as done", on_click=state.mark_done, args=(item, ds))


def card(item, ds, key, compact=False):
    """Title, one sentence, actions. compact (under a chat answer that already says it): title and actions."""
    title, sentence = actions.text(item)
    recalled = None if compact else memory.last_time(item.kind)
    with st.container(border=True, key=f"ci_card_{key}"):
        st.markdown(f'<div class="rw-ci-title">{fmt.html(title)}</div>'
                    + ("" if compact else f'<div class="rw-ci-text">{fmt.html(sentence)}</div>')
                    + (f'<div class="rw-ci-memory">{fmt.html(recalled)}</div>' if recalled else ""),
                    unsafe_allow_html=True)
        actions_row(item, ds, key)


def _done_buttons():
    """What was marked done, each with Undo (in the row under the cards)."""
    for kind, d in (st.session_state.get("done") or {}).items():
        st.button(f"Done: {d['label']} · Undo", key=f"ci_undo_{kind}", type="tertiary", icon=":material/undo:",
                  on_click=state.undo, args=(kind,), help=f"Undo \"{d['label']}\"")


def _greeting_slot(items):
    background.slot(_key(items), greeting.fallback(items),
                    lambda t: st.markdown(f'<div class="rw-ci-line">{fmt.html(t)}</div>', unsafe_allow_html=True))


SHOWN_ABOVE = ("run_out",)        # the status card right above already says when the money runs out


def pending(ds, done_scenario, shown_above=SHOWN_ABOVE):
    """Items still open: fixes marked done are already out (the scenario has them); others are filtered here.
    Items the status card already shows are left out (one fact, once per screen)."""
    done = st.session_state.get("done") or {}
    return [it for it in engine.attention_items(done_scenario, ds) if it.kind not in done
            and it.kind not in shown_above]


def render(ds, done_scenario):
    items = pending(ds, done_scenario)
    runs_out = not items and any(it.kind == "run_out" for it in pending(ds, done_scenario, ()))
    _start_greeting(items)
    with st.container(key="checkin"):
        name = None if state.mine() else "Maya"
        st.markdown(f'<div class="rw-ci-head">{fmt.html(heading(items, name, runs_out))}</div>',
                    unsafe_allow_html=True)
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
                                   file_name="pocketmoney-deadlines.ics", mime=MIME_ICS, icon=":material/calendar_add_on:",
                                   type="tertiary", key="ci_cal_all", on_click=state.log,
                                   args=(f"Downloaded all {len(items)} deadlines as one calendar file",))
            _done_buttons()
    return items
