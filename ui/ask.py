"""Ask PocketMoney: a floating chat button (bottom-left, on every tab) opens a chat panel (st.dialog) with the thread
(newest at the bottom), suggested questions while it's empty, the question box, "Think harder", "New chat" and "What
PocketMoney remembers". The thread lives in session state, so closing and reopening the panel keeps it, and a question
still being answered when the panel closes is asked again when it reopens.

Each reply first shows the instant quick answer (built from the engine), then the AI answer streams in over it;
if the AI answer doesn't pass the checks, the quick answer stays."""
import json
import re
import time
from types import SimpleNamespace

import pandas as pd
import streamlit as st

import agent
import config
import engine
from ui import checkin, fmt, memory, state

CITE = re.compile(r"\[((?:[CE]\d+)(?:\s*[,;]\s*[CE]\d+)*)\]")
MAX_TURNS = state.MAX_TURNS


def _queue(q):
    st.session_state.ask_pending = q


def new_chat():
    st.session_state.history = []


def _footnotes(a):
    """Cited pack ids in order of first use -> footnote numbers 1, 2, 3..."""
    ids = {it["id"] for it in a.pack["items"]}
    order = []
    for m in CITE.finditer(a.text):
        for cid in re.split(r"\s*[,;]\s*", m.group(1)):
            if cid in ids and cid not in order:
                order.append(cid)
    return {cid: n for n, cid in enumerate(order, start=1)}


def _chipify(text, notes):
    def sub(m):
        nums = [notes[c] for c in re.split(r"\s*[,;]\s*", m.group(1)) if c in notes]
        return " " + " ".join(f":blue-badge[{n}]" for n in nums) if nums else ""
    return re.sub(r"\s*" + CITE.pattern, sub, fmt.md(fmt.strip_ids(text)))


def _current_evidence(src, ds):
    """The evidence for this source's query in the dataset loaded NOW (so it says Zetaris when the app runs on
    Zetaris, even for an answer recorded on the local files). Same rows either way."""
    return next((ev for ev in (ds.evidence if ds else []) if ev.query == src.get("query")), None)


def _proof(item, a, key, ds=None):
    """One cited fact, in plain words, like the "Show proof" sections."""
    items = {it["id"]: it for it in a.pack["items"]}
    if item["kind"] == "calc":
        st.markdown(f"**{fmt.md(item['value'])}**")
        st.markdown(fmt.md(fmt.strip_ids(item["how"])))
        sources = [items[u] for u in item.get("uses", []) if u in items and items[u]["kind"] == "source"]
    else:
        sources = [item]
    for src in sources:
        where = src["title"].split(" (")[0]
        st.caption(f"From {fmt.md(where[0].lower() + where[1:])}")
        st.dataframe(pd.DataFrame([{"What": r["what"], "Amount": r["amount"], "Date": r["date"]} for r in src["rows"]]),
                     hide_index=True, width="stretch", column_config=fmt.PROOF_COLUMNS)
        if src.get("more"):
            st.caption(f"...and {src['more']} more records like these.")
    if st.toggle("Details for nerds", key=f"nerd_{key}_{item['id']}"):
        for src in sources:
            ev = _current_evidence(src, ds)
            backend = ev.backend if ev else src["backend"]
            took = f"{(ev.duration_s if ev else src['duration_s']):.3f} s"
            original = ev.original_duration_s if ev else src.get("original_duration_s")
            if original is not None:
                took += f" (original Zetaris query {original:.1f} s)"
            st.markdown(f"`{item['id']}` · query **{src['query']}** · {backend} · {took} · rows "
                        + ", ".join(src["row_ids"]))
            st.code(ev.sql if ev else src["sql"], language="sql", wrap_lines=True)


def _mode_words(a):
    think = getattr(a, "think", False)
    name = agent.model_name((a.models or {}).get("explain")
                            or (config.think_model() if think else config.fast_explain_model()))
    return f"Think harder: {name}, thinking on" if think else f"Fast: {name}, thinking off"


def _thinking(a, key):
    with st.expander("How PocketMoney thought about this", icon=":material/psychology:"):
        plan = agent.Plan(**a.plan)
        st.markdown("**What PocketMoney checked:** " + fmt.md(agent.plan_words(plan))
                    + ("  \n:gray[Matched by keywords because the planner wasn't available.]"
                       if plan.source == "keywords" else ""))
        t = a.timings or {}
        parts = ([f"quick answer in {t['quick_s']} s"] if t.get("quick_s") is not None else []) +             ([f"full answer in {t['total_s']} s"] if t.get("total_s") is not None else [])
        if parts:
            saved = " (a saved answer; these are its original times)" if a.mode in ("cached", "replay") else ""
            st.markdown(f"**Time:** {', '.join(parts)}{saved}. {_mode_words(a)}.")
        by, calls = a.models.get("answered_by"), a.models.get("calls") or []
        plan_call = next((x for x in calls if x.get("role") == "plan" and x.get("routed_model")), None)
        if plan_call:
            st.markdown("**Planned by:** " + fmt.md(agent.handled_by(plan_call)))
        if plan.tool:
            done_by = a.models.get("answered_by_call")
            st.markdown("**Written by:** " + (fmt.md(agent.handled_by(done_by)) if done_by and by != "template" else
                                               f"{agent.model_name(by)} (`{by}`)" if by and by != "template" else
                                               "the quick answer, built from your numbers"))
        c = a.check
        if c and a.mode != "no_key":
            st.markdown("**Number check:** " + (
                f"all {c['amounts']} dollar amounts and {c['dates']} dates match your records."
                if c["ok"] else "these didn't match your records: " + fmt.md("; ".join(c["problems"]))))
        facts = getattr(a, "facts", None) or []
        if facts:
            added = [f["label"] for f in facts if f["appended"]]
            st.markdown(f"**Required facts:** {len(facts) - len(added)} of {len(facts)} written by the model"
                        + (f"; PocketMoney added the rest from your numbers ({fmt.md(', '.join(added))})." if added
                           else ".") + (" One rewrite was needed." if a.retries.get("explain_rewrite") else ""))
        recalled = a.models.get("memories") or []
        if recalled:
            st.markdown("**Remembered from earlier (used to understand your question, not for numbers):** "
                        + fmt.md("; ".join(f"“{x['content']}”" for x in recalled)))
        if a.retries.get("repaired"):
            st.markdown(f"**Repaired:** {a.retries['repaired']} (no words were added or changed).")
        if a.reasoning:
            st.markdown("**Nemotron's reasoning**")
            with st.container(height=220):
                st.text(a.reasoning)
        if plan.tool and st.toggle("Details for nerds", key=f"nerd_plan_{key}"):
            st.caption("The plan Nemotron wrote (checked by PocketMoney before any tool ran):" if plan.source == "llm"
                       else "The plan PocketMoney matched by keywords (the planner wasn't available):")
            st.code(json.dumps({"resolved_question": plan.resolved_question, "calls": plan.calls,
                                "assumptions": plan.assumptions}, indent=2, default=str),
                    language="json", wrap_lines=True)
            if calls:
                st.caption("Every model call (provider, the model that actually answered, the Meterless receipt):")
                st.code(json.dumps(calls, indent=2, default=str), language="json", wrap_lines=True)


def _todo_cards(act, key, ds):
    """An action_plan answer: the same cards and buttons as the check-in, for the items it's about."""
    if ds is None:
        return
    done = st.session_state.get("done") or {}
    items = {it.kind: it for it in engine.attention_items(state.done_scenario(ds), ds)}
    for kind in act["items"]:
        if kind in done:
            st.caption(f":material/check: {fmt.md(done[kind]['label'])}: done.")
        elif kind in items:
            checkin.card(items[kind], ds, f"chat{key}_{kind}", compact=True)


def _actions(a, key, ds=None):
    for act in (x for x in a.actions if x["kind"] == "attention"):
        _todo_cards(act, key, ds)
    drafts = [x for x in a.actions if x["kind"] != "attention"]
    if not drafts:
        return
    label = " and ".join(["a ready-made email" if x["kind"] == "email" else "a to-do list" for x in drafts])
    with st.expander(label[0].upper() + label[1:], icon=":material/edit_note:"):
        _action_cards(a, key)


def _action_cards(a, key):
    for act in (x for x in a.actions if x["kind"] != "attention"):
        with st.container(border=True, key=f"card_act_{key}_{act['id']}"):
            if act["kind"] == "email":
                st.markdown(f"**:material/mail: Draft email to {fmt.md(act['to'])}**")
                st.markdown(f"Subject: {fmt.md(act['subject'])}")
                st.code(act["body"], language=None, wrap_lines=True)
                st.caption("PocketMoney never sends anything. Use the copy button, then send it from your student email.")
                st.checkbox("Mark as done", key=f"done_{key}_{act['id']}")
            else:
                st.markdown(f"**:material/checklist: {fmt.md(act['title'])}**")
                for i, item in enumerate(act["items"]):
                    st.checkbox(fmt.md(item), key=f"done_{key}_{act['id']}_{i}")
                with st.popover("Copy list", icon=":material/content_copy:"):
                    st.code("\n".join(f"- {x}" for x in act["items"]), language=None, wrap_lines=True)


def _chip(cid, notes, items):
    """Footnote chip label in plain words: "2 · $1,850", "4 · $1,862 below zero", "1 · The answer",
    "7 · Your checking account". Exact cents are inside the proof itself."""
    it = items[cid]
    if it["kind"] == "source":
        return f"{notes[cid]} · {it['title'].split(' (')[0]}"
    if it.get("unit") == "USD":
        return f"{notes[cid]} · {fmt.balance(it['raw'])}"
    return f"{notes[cid]} · " + (it["value"] if it.get("unit") not in ("text", "flag") else "The answer")


def _html_cited(text, notes):
    """Escaped text with [C#]/[E#] turned into small, light footnote numbers."""
    def sub(m):
        nums = [notes[c] for c in re.split(r"\s*[,;]\s*", m.group(1)) if c in notes]
        return "".join(f'<sup class="rw-fn">{n}</sup>' for n in nums)
    return re.sub(r"\s*" + CITE.pattern, sub, fmt.html(fmt.strip_ids(text)))


def sections_html(sec, notes):
    """ANSWER big and bold; WHY as bullets; DO THIS numbered; NOTE small (one HTML block)."""
    out = (f'<div class="rw-ans">{_html_cited(sec["answer"], notes)}</div>'
           + '<ul class="rw-why-list">' + "".join(f"<li>{_html_cited(x, notes)}</li>" for x in sec["why"]) + "</ul>")
    if sec.get("do"):
        out += ('<div class="rw-do-head">Do this</div><ol class="rw-do-list">'
                + "".join(f"<li>{_html_cited(x, notes)}</li>" for x in sec["do"]) + "</ol>")
    if sec.get("note"):
        out += f'<div class="rw-note">{_html_cited(sec["note"], notes)}</div>'
    return out


def _structured(a, notes, key, latest, ds=None):
    """The answer, with "Do these" beside DO THIS when the answer's fixes aren't all on yet."""
    sec, s = a.sections, st.session_state
    fixes = [SimpleNamespace(**f) for f in a.fixes] if a.verdict == "yes_if" else []
    show_do = latest and fixes and not all(s.wf_refund if f.kind == "refund" else s.get(state.cancel_key(f.name))
                                           for f in fixes)
    head = {"answer": sec["answer"], "why": sec["why"], "do": [], "note": ""}
    st.markdown(sections_html(head, notes), unsafe_allow_html=True)
    if sec["do"]:
        steps = ('<div class="rw-do-head">Do this</div><ol class="rw-do-list">'
                 + "".join(f"<li>{_html_cited(x, notes)}</li>" for x in sec["do"]) + "</ol>")
        if show_do:
            left, right = st.columns([4, 1], vertical_alignment="center")
            left.markdown(steps, unsafe_allow_html=True)
            right.button("Do these", type="primary", key=f"ans_do_{key}", on_click=state.apply_fixes, args=(fixes,))
        else:
            st.markdown(steps, unsafe_allow_html=True)
    elif show_do:
        st.button("Do these", type="primary", key=f"ans_do_{key}", on_click=state.apply_fixes, args=(fixes,))
    note = sec.get("note") or " ".join(a.plan.get("assumptions") or [])
    if note:
        st.markdown(f'<div class="rw-note">{_html_cited(note, notes)}</div>', unsafe_allow_html=True)
    _shift_button(a, key, latest)
    _meal_button(a, key, latest, ds)


def answer_meal_log(a):
    """(meals, points) a meal_plan answer offers to log ("I just used 2 meals"), or None. Only when the answer
    showed what's left after logging them (nothing to log, or it couldn't be logged: no button)."""
    if not any(f.get("key") == "after" for f in getattr(a, "facts", None) or []):
        return None
    call = next((c for c in a.plan.get("calls") or [] if c.get("tool") == "meal_plan"), None)
    meals, points = agent.meal_log_offer((call or {}).get("args") or {})
    return (meals, points) if meals or points else None


def _meal_button(a, key, latest, ds=None):
    """ "Log 2 meals": one tap logs what she said she used. PocketMoney never logs it without her tap."""
    offer = answer_meal_log(a)
    if not (latest and offer):
        return
    if key in (st.session_state.get("meal_logged") or ()):
        st.caption(":material/check: Logged in your meal plan.")
        return
    st.button(state.meal_log_label(*offer), key=f"ans_meal_{key}", icon=":material/restaurant:", type="primary",
              on_click=state.log_meal_from_chat, args=(offer, key, ds))


def answer_shifts(a):
    """The extra shifts a what-if answer was about: [{"date": "YYYY-MM-DD", "hours": "4.00"}]."""
    return [x for c in a.plan.get("calls") or [] if c.get("tool") == "what_if"
            for x in (c.get("args") or {}).get("extra_shifts") or []]


def _shift_button(a, key, latest):
    items = answer_shifts(a)
    if not (latest and items) or state.mine():
        return
    have = {(x["date"].isoformat(), float(x["hours"])) for x in st.session_state.get("wf_shifts") or []}
    if all((x["date"], float(x["hours"])) in have for x in items):
        st.caption("These shifts are in your shift planner.")
        return
    st.button("Add these to my shift planner" if len(items) > 1 else "Add this to my shift planner",
              key=f"ans_shifts_{key}", icon=":material/schedule:", on_click=state.add_shifts, args=(items,))


def _is_general(a):
    calls = a.plan.get("calls") or []
    return bool(calls) and all(c["tool"] == "general_info" for c in calls)


def reply(a, latest=True, ds=None):
    """PocketMoney's message: the answer, notes, proof chips, drafts and how it thought."""
    key = str(int(a.created * 1000))
    notes = _footnotes(a)
    if _is_general(a):
        st.badge("General info", color="gray", icon=":material/info:")
    if getattr(a, "sections", None):
        _structured(a, notes, key, latest, ds)
    else:                                                    # off-topic, no-key and older saved answers
        if a.verdict_label:
            st.badge(a.verdict_label, color="green" if a.verdict in ("yes", "covered") else "orange")
        st.markdown(_chipify(a.text, notes))
    for n in a.notes:
        st.caption(fmt.md(n))
    if notes:
        items = {it["id"]: it for it in a.pack["items"]}
        pick = st.pills("Proof", list(notes), key=f"proof_{key}", format_func=lambda cid: _chip(cid, notes, items))
        if pick:
            _proof(items[pick], a, key, ds)
    _actions(a, key, ds)
    if a.plan.get("tool") or a.mode == "no_key":
        _thinking(a, key)


def _resolved(a):
    r = (a.plan or {}).get("resolved_question")
    return r if r and agent.normalize_question(r) != agent.normalize_question(a.question) else None


def student(question, resolved=None):
    with st.chat_message("user"):
        st.markdown(fmt.md(question))
        if resolved:
            st.caption(f"Answering: {fmt.md(resolved)}")


def _ask(question, ds, scenario):
    """Run the agent inside PocketMoney's message: friendly stages, the quick answer at once, then the AI answer
    streaming over it."""
    s = st.session_state
    student(question)
    answer, text, quick = None, "", ""
    with st.chat_message("assistant"):
        status = st.status(agent.STAGES["plan"], expanded=False)
        box, caption = st.empty(), st.empty()
        earlier = list(reversed([a for a in s.history if a.mode != "event"][:3]))
        for kind, payload in agent.run(question, scenario, ds=ds, history=earlier, think=s.get("ask_think", False),
                                       done=tuple(s.get("done") or {}),
                                       budget=state.budget() if state.has_budget() else None, private=state.mine(),
                                       memory=memory.recall(question)):
            if kind == "stage":
                status.update(label=payload)
            elif kind == "quick":
                quick = payload
                sec = agent.parse_sections(quick)
                box.markdown(sections_html(sec, {}) if sec else fmt.md(agent.strip_citations(quick)),
                             unsafe_allow_html=bool(sec))
                caption.caption("Quick answer from your numbers. Writing the full answer...")
            elif kind == "text":
                text += payload
                sec = agent.parse_sections(text + " ▌", partial=True)     # laid out like the finished answer
                box.markdown(sections_html(sec, {}) if sec else fmt.md(agent.strip_citations(text)) + " ▌",
                             unsafe_allow_html=bool(sec))
            elif kind == "restart":
                text = ""
                if payload:                                              # "Double-checking the numbers..."
                    status.update(label=payload)
                if quick:
                    sec = agent.parse_sections(quick)
                    box.markdown(sections_html(sec, {}) if sec else fmt.md(quick), unsafe_allow_html=bool(sec))
            elif kind == "answer":
                answer = payload
        status.update(label="Done", state="complete")
    s.history = ([answer] + s.history)[:MAX_TURNS]
    if answer and answer.mode not in ("no_key", "event") and not state.mine():
        memory.conversation(answer)


def render(ds, scenario):
    s = st.session_state
    s.setdefault("history", [])
    s.setdefault("ask_think", False)
    with st.container(key="ask_thread"):
        newest = next((a for a in s.history if a.mode != "event"), None)   # its buttons stay live under events
        for a in reversed(s.history):
            if a.mode == "event":                         # PocketMoney speaking up (e.g. after "mark as done")
                with st.chat_message("assistant"):
                    st.markdown(fmt.md(a.text))
                continue
            student(a.question, _resolved(a))
            with st.chat_message("assistant"):
                reply(a, latest=a is newest, ds=ds)
        question = s.get("ask_pending")
        if question:                                  # kept until answered: closing the panel mid-reply loses nothing
            _ask(question, ds, scenario)
            s.pop("ask_pending", None)
            st.rerun()
        if not s.history:
            with st.container(horizontal=True, gap="small"):
                for i, q in enumerate(agent.MYDATA_SUGGESTED if state.mine() else agent.SUGGESTED):
                    st.button(q, key=f"ask_suggest_{i}", on_click=_queue, args=(q,), type="tertiary",
                              icon=":material/chat_bubble:")
        if state.mine() and config.AI_PROVIDER == "meterless" and not config.SAMPLE_MODE:
            st.caption(":material/lock: Your questions go through Meterless Nightshift on this computer, which keeps "
                       "a local log of requests.")
        typed = st.chat_input("Ask about your money", key="ask_input")
        with st.container(horizontal=True, gap="small", key="ask_tools"):
            st.toggle("Think harder", key="ask_think", on_change=lambda: memory.think_harder(s.get("ask_think")),
                      help="Uses the bigger Nemotron model with thinking on. Slower (a minute or more), and shows "
                           "its reasoning.")
            if s.history:
                st.button("New chat", key="ask_new", icon=":material/add_comment:", type="tertiary", on_click=new_chat)
        memory.render()
        if typed:
            _queue(typed)
            st.rerun()


# --- the floating button and the panel --------------------------------------------------------------------------------
UPDATED = "Done. Your forecast is updated."


def forecast_sig():
    """Everything the main page's forecast depends on (what-ifs, done items, budget): a button in the panel that
    changes it needs the whole page to rerun."""
    s = st.session_state
    keys = sorted(str(k) for k in s.keys() if str(k).startswith(("wf_", "bud_amt_", "opp_")))
    return repr([(k, s.get(k)) for k in keys] + [("done", sorted((s.get("done") or {}).keys())),
                                                 ("meal", s.get("meal_data"))])


def _open():
    st.session_state.chat_open = True
    st.session_state.pop("panel_sig", None)


def _closed():
    st.session_state.chat_open = False
    st.session_state.pop("panel_sig", None)


def fab():
    """The round "Ask PocketMoney" button, fixed bottom-left by style.py (keyed container, not a fragile selector)."""
    with st.container(key="chat_fab"):
        st.button("Ask PocketMoney", key="chat_fab_btn", icon=":material/forum:", on_click=_open, type="primary",
                  help="Ask PocketMoney about your money")


@st.dialog("Ask PocketMoney", width="large", on_dismiss=_closed)
def _panel(ds, scenario):
    s = st.session_state
    sig = forecast_sig()
    if s.get("panel_sig") not in (None, sig):                              # a button here changed the forecast
        last = (s.get("history") or [None])[0]
        if not (last and last.mode == "event" and time.time() - last.created < 10):   # mark_done says it already
            s.history = ([agent.event_answer(UPDATED)] + s.get("history", []))[:MAX_TURNS]
    s.panel_sig = sig
    if s.get("page_sig") is not None and sig != s.page_sig:                # only the panel reran: update the page
        st.rerun()                                                          # (the panel reopens itself)
    with st.container(key="chat_panel"):
        render(ds, scenario)


def panel(ds, scenario):
    """Call at the end of every full page run: records the forecast inputs and reopens the panel if it's open."""
    st.session_state.page_sig = forecast_sig()
    fab()
    if st.session_state.get("chat_open"):
        _panel(ds, scenario)
