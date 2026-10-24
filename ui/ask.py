"""Ask Runway: a chat thread under the status card. The student's messages and Runway's replies (newest at the
bottom), the question box below them, suggested questions while the thread is empty, "New chat" and "Think harder".

Each reply first shows the instant quick answer (built from the engine), then the AI answer streams in over it;
if the AI answer doesn't pass the checks, the quick answer stays."""
import re
from types import SimpleNamespace

import pandas as pd
import streamlit as st

import agent
from ui import fmt, state

CITE = re.compile(r"\[((?:[CE]\d+)(?:\s*[,;]\s*[CE]\d+)*)\]")
MAX_TURNS = 10


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
    return ("Think harder: Nemotron Super, thinking on" if getattr(a, "think", False) else
            "Fast: Nemotron Lightning, thinking off")


def _thinking(a):
    with st.expander("How Runway thought about this", icon=":material/psychology:"):
        plan = agent.Plan(**a.plan)
        st.markdown("**What Runway checked:** " + fmt.md(agent.plan_words(plan))
                    + ("  \n:gray[Matched by keywords because the planner wasn't available.]"
                       if plan.source == "keywords" else ""))
        t = a.timings or {}
        parts = ([f"quick answer in {t['quick_s']} s"] if t.get("quick_s") is not None else []) +             ([f"full answer in {t['total_s']} s"] if t.get("total_s") is not None else [])
        if parts:
            saved = " (a saved answer; these are its original times)" if a.mode in ("cached", "replay") else ""
            st.markdown(f"**Time:** {', '.join(parts)}{saved}. {_mode_words(a)}.")
        by = a.models.get("answered_by")
        if plan.tool:
            st.markdown("**Written by:** " + (f"{agent.model_name(by)} (`{by}`)" if by and by != "template" else
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
                        + (f"; Runway added the rest from your numbers ({fmt.md(', '.join(added))})." if added
                           else ".") + (" One rewrite was needed." if a.retries.get("explain_rewrite") else ""))
        if a.reasoning:
            st.markdown("**Nemotron's reasoning**")
            with st.container(height=220):
                st.text(a.reasoning)


def _actions(a, key):
    if not a.actions:
        return
    label = " and ".join(["a ready-made email" if x["kind"] == "email" else "a to-do list" for x in a.actions])
    with st.expander(label[0].upper() + label[1:], icon=":material/edit_note:"):
        _action_cards(a, key)


def _action_cards(a, key):
    for act in a.actions:
        with st.container(border=True):
            if act["kind"] == "email":
                st.markdown(f"**:material/mail: Draft email to {fmt.md(act['to'])}**")
                st.markdown(f"Subject: {fmt.md(act['subject'])}")
                st.code(act["body"], language=None, wrap_lines=True)
                st.caption("Runway never sends anything. Use the copy button, then send it from your student email.")
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


def _structured(a, notes, key, latest):
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


def _is_general(a):
    calls = a.plan.get("calls") or []
    return bool(calls) and all(c["tool"] == "general_info" for c in calls)


def reply(a, latest=True, ds=None):
    """Runway's message: the answer, notes, proof chips, drafts and how it thought."""
    key = str(int(a.created * 1000))
    notes = _footnotes(a)
    if _is_general(a):
        st.badge("General info", color="gray", icon=":material/info:")
    if getattr(a, "sections", None):
        _structured(a, notes, key, latest)
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
    _actions(a, key)
    if a.plan.get("tool") or a.mode == "no_key":
        _thinking(a)


def _resolved(a):
    r = (a.plan or {}).get("resolved_question")
    return r if r and agent.normalize_question(r) != agent.normalize_question(a.question) else None


def student(question, resolved=None):
    with st.chat_message("user"):
        st.markdown(fmt.md(question))
        if resolved:
            st.caption(f"Answering: {fmt.md(resolved)}")


def _ask(question, ds, scenario):
    """Run the agent inside Runway's message: friendly stages, the quick answer at once, then the AI answer
    streaming over it."""
    s = st.session_state
    student(question)
    answer, text, quick = None, "", ""
    with st.chat_message("assistant"):
        status = st.status(agent.STAGES["plan"], expanded=False)
        box, caption = st.empty(), st.empty()
        earlier = list(reversed(s.history[:3]))
        for kind, payload in agent.run(question, scenario, ds=ds, history=earlier, think=s.get("ask_think", False)):
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
                box.markdown(fmt.md(agent.strip_citations(text)) + " ▌")
            elif kind == "restart":
                text = ""
                if quick:
                    sec = agent.parse_sections(quick)
                    box.markdown(sections_html(sec, {}) if sec else fmt.md(quick), unsafe_allow_html=bool(sec))
            elif kind == "answer":
                answer = payload
        status.update(label="Done", state="complete")
    s.history = ([answer] + s.history)[:MAX_TURNS]


def render(ds, scenario):
    s = st.session_state
    s.setdefault("history", [])
    s.setdefault("ask_think", False)
    with st.container(key="ask_thread"):
        for i, a in enumerate(reversed(s.history)):
            student(a.question, _resolved(a))
            with st.chat_message("assistant"):
                reply(a, latest=(i == len(s.history) - 1), ds=ds)
        question = s.pop("ask_pending", None)
        if question:
            _ask(question, ds, scenario)
            st.rerun()
        if not s.history:
            with st.container(horizontal=True, gap="small"):
                for i, q in enumerate(agent.SUGGESTED):
                    st.button(q, key=f"ask_suggest_{i}", on_click=_queue, args=(q,), type="tertiary",
                              icon=":material/chat_bubble:")
        typed = st.chat_input("Ask about your money", key="ask_input")
        with st.container(horizontal=True, gap="small", key="ask_tools"):
            st.toggle("Think harder", key="ask_think",
                      help="Uses Nemotron Super with thinking on. Slower (about a minute), and shows its reasoning.")
            if s.history:
                st.button("New chat", key="ask_new", icon=":material/add_comment:", type="tertiary", on_click=new_chat)
        if typed:
            _queue(typed)
            st.rerun()
