"""What PocketMoney remembers (Meterless H-MEM, runway_memory.py): one shared memory for this computer, the hooks the UI
calls when Maya does something worth remembering, the check-in's "Last time..." line, and the small "What PocketMoney
remembers" section with Forget controls. Off in My data mode (her own data is never remembered, rule 7)."""
import time

import streamlit as st

import agent
import config
import runway_memory
from ui import fmt, state

VERBS = {"reminder": "set a reminder for this", "email": "opened the email draft for this",
         "cancel": "opened the cancel page"}


@st.cache_resource(show_spinner=False)
def _memory():
    return runway_memory.RunwayMemory()


def get():
    """The memory, or None in My data mode. The hosted demo gives each visitor their own memory for the session (no
    shared file every judge writes to); so does a disk that can't be written."""
    if state.mine():
        return None
    if not config.HOSTED_DEMO:
        try:
            return _memory()
        except OSError:
            pass
    if "memory_session" not in st.session_state:
        st.session_state.memory_session = runway_memory.RunwayMemory(persist=False)
    return st.session_state.memory_session


def session_start():
    return st.session_state.setdefault("memory_session_ms", int(time.time() * 1000))


def safe(fn, *args):
    """Memory never breaks the app: a failed write is skipped."""
    mem = get()
    if mem is None:
        return None
    try:
        return fn(mem, *args)
    except Exception:
        return None


# --- hooks (called from state.py callbacks and the chat) --------------------------------------------------------
def done(kind, label, title):
    safe(lambda m: m.remember_done(kind, label, title))


def undone(kind, label, title):
    safe(lambda m: m.remember_undone(kind, label, title))


def intent(kind, how, title):
    safe(lambda m: m.remember_intent(kind, f"{'Set a reminder' if how == 'reminder' else 'Opened the email draft' if how == 'email' else 'Opened the cancel page'}: {title}"))


def budget(amounts):
    safe(lambda m: m.remember_budget(amounts))


def shifts(planned):
    safe(lambda m: m.remember_shifts(planned, fmt.day))


def meal_plan(text):
    safe(lambda m: m.remember_meal_plan(text))


def college(text):
    safe(lambda m: m.remember_college(text) if text else m.forget_college())


def think_harder(on):
    safe(lambda m: m.remember_preference("Prefers Think harder answers (slower, with reasoning)." if on else
                                         "Prefers fast answers.", "think"))


def conversation(answer):
    line = (answer.sections or {}).get("answer") or answer.text.split("\n")[0]
    line = agent.strip_citations(fmt.strip_ids(line)).replace("ANSWER:", "").strip()
    safe(lambda m: m.remember_conversation(answer.question, line[:140], st.session_state.get("memory_session_id")))


def recall(question):
    """H-MEM recall for PLAN, or None."""
    mem = get()
    if mem is None or not mem.items():
        return None
    try:
        return mem.engine.query(question, top_n=runway_memory.PLAN_TOP_N, threshold=runway_memory.PLAN_THRESHOLD)
    except Exception:
        return None


# --- the check-in's "Last time..." line ----------------------------------------------------------------------------
def last_time(kind):
    """"Last time you set a reminder for this. Did you do it?" for a check-in item, from an earlier session."""
    mem = get()
    if mem is None:
        return None
    since = session_start()
    d = mem.done_before(kind, since)
    if d:
        label = d.content.split(":", 1)[1].split("(")[0].strip()
        return f"Last time you clicked “{label}”. Still true? Click it again."
    i = mem.intent_before(kind, since)
    if i:
        how = "reminder" if i.content.startswith("Set a reminder") else "email" if "email" in i.content else "cancel"
        return f"Last time you {VERBS[how]}. Did you do it?"
    return None


# --- "What PocketMoney remembers" --------------------------------------------------------------------------------------
def _forget(memory_id):
    safe(lambda m: m.forget(memory_id))


def _wrong(memory_id):
    safe(lambda m: m.mark_wrong(memory_id))


def _forget_all():
    safe(lambda m: m.forget_all())


def render():
    mem = get()
    if mem is None:
        return
    items = mem.items()
    with st.expander(f"What PocketMoney remembers ({len(items)})", icon=":material/memory:"):
        if not items:
            st.caption("Nothing yet. PocketMoney remembers what you mark done, your budget, the shifts you plan and "
                       "short notes from your chats, so it can pick up where you left off.")
            return
        st.caption("PocketMoney uses these to understand your questions. Your numbers always come from your records.")
        for m in items[:12]:
            left, right = st.columns([7, 2], vertical_alignment="center")
            when = runway_memory.when_words(m.provenance.get("learnedAt") or m.timestamp)
            flag = " :orange[(marked not right)]" if "review" in m.tags else ""
            left.markdown(f"{fmt.md(m.content)}{flag}  \n:gray[{fmt.md(m.provenance.get('label', m.source))}, {when}]")
            with right.container(horizontal=True, gap="xsmall"):
                st.button("", key=f"mem_forget_{m.id}", icon=":material/delete:", type="tertiary",
                          help="Forget this", on_click=_forget, args=(m.id,))
                if "review" not in m.tags:
                    st.button("", key=f"mem_wrong_{m.id}", icon=":material/thumb_down:", type="tertiary",
                              help="This isn't right", on_click=_wrong, args=(m.id,))
        st.button("Forget everything", key="mem_forget_all", type="tertiary", icon=":material/delete_sweep:",
                  on_click=_forget_all)
        st.caption(f"Stored only on this computer. Every change is logged ({mem.ledger_size()} entries).")
