"""Ask Runway: the question box under the status card, the streamed answer, and the answer cards."""
import re
from types import SimpleNamespace

import pandas as pd
import streamlit as st

import agent
from ui import fmt, state

CITE = re.compile(r"\[((?:[CE]\d+)(?:\s*[,;]\s*[CE]\d+)*)\]")
HISTORY = 3


def _queue(q):
    st.session_state.ask_pending = q


def _ask(question, ds, scenario):
    """Run the agent, showing friendly stages and the answer as it streams."""
    answer, text = None, ""
    with st.status(agent.STAGES["plan"], expanded=True) as status:
        box = st.empty()
        for kind, payload in agent.run(question, scenario, ds=ds):
            if kind == "stage":
                status.update(label=payload)
            elif kind == "text":
                text += payload
                box.markdown(fmt.md(CITE.sub("", text)) + " ▌")
            elif kind == "restart":
                text = ""
                box.markdown(fmt.md(payload) if payload else "")
            elif kind == "answer":
                answer = payload
        status.update(label="Done", state="complete", expanded=False)
    st.session_state.history = [answer] + st.session_state.history[:HISTORY - 1]


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
    return re.sub(r"\s*" + CITE.pattern, sub, fmt.md(text))


def _proof(item, a, key):
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
        st.dataframe(pd.DataFrame([{"Date": r["date"], "What": r["what"], "Amount": r["amount"]} for r in src["rows"]]),
                     hide_index=True, width="stretch")
        if src.get("more"):
            st.caption(f"...and {src['more']} more records like these.")
    if st.toggle("Details for nerds", key=f"nerd_{key}_{item['id']}"):
        for src in sources:
            took = f"{src['duration_s']:.3f} s"
            if src.get("original_duration_s") is not None:
                took += f" (original Zetaris query {src['original_duration_s']:.1f} s)"
            st.markdown(f"`{item['id']}` · query **{src['query']}** · {src['backend']} · {took} · rows "
                        + ", ".join(src["row_ids"]))
            st.code(src["sql"], language="sql", wrap_lines=True)


def _thinking(a):
    with st.expander("How Runway thought about this", icon=":material/psychology:"):
        plan = agent.Plan(**a.plan)
        st.markdown("**What Runway checked:** " + fmt.md(agent.plan_words(plan) if plan.tool else "nothing (off-topic)")
                    + ("  \n:gray[Matched by keywords because the planner wasn't available.]"
                       if plan.source == "keywords" else ""))
        by = a.models.get("answered_by")
        if plan.tool:
            st.markdown("**Written by:** " + (f"{agent.model_name(by)} (`{by}`)" if by and by != "template" else
                                               "a template built from your numbers (no model was available)"))
        c = a.check
        if c:
            st.markdown("**Number check:** " + (
                f"all {c['amounts']} dollar amounts and {c['dates']} dates match your records."
                if c["ok"] else "these didn't match your records: " + fmt.md("; ".join(c["problems"]))))
        if a.reasoning:
            st.markdown("**Nemotron's reasoning**")
            with st.container(height=220):
                st.text(a.reasoning)


def _actions(a, key):
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
    """Footnote chip label in plain words: "2 · $1,850.00", "1 · The answer", "7 · Your checking account"."""
    it = items[cid]
    if it["kind"] == "source":
        return f"{notes[cid]} · {it['title'].split(' (')[0]}"
    return f"{notes[cid]} · " + (it["value"] if it.get("unit") not in ("text", "flag") else "The answer")


def _verdict_color(a):
    if a.verdict in ("yes", "covered") or a.verdict_label == "You can afford it.":
        return "green"
    return "orange" if a.verdict == "yes_if" else "red"


def card(a, latest=True):
    s, key = st.session_state, str(int(a.created * 1000))
    notes = _footnotes(a)
    with st.container(border=True):
        st.caption(f"You asked: {fmt.md(a.question)}")
        if a.verdict_label:
            st.badge(a.verdict_label, color=_verdict_color(a))
        st.markdown(_chipify(a.text, notes))
        for x in a.plan.get("assumptions") or []:
            st.caption(f":material/info: Assumption: {fmt.md(x)}")
        for n in a.notes:
            (st.warning if "couldn't be matched" in n else st.info)(fmt.md(n))
        if not latest:
            return
        if a.verdict == "yes_if" and a.fixes:
            fixes = [SimpleNamespace(**f) for f in a.fixes]
            done = all(s.wf_refund if f.kind == "refund" else s.get(state.cancel_key(f.name)) for f in fixes)
            if not done:
                st.button("Do these", type="primary", key=f"ans_do_{key}", on_click=state.apply_fixes, args=(fixes,))
        if notes:
            items = {it["id"]: it for it in a.pack["items"]}
            pick = st.pills("Proof", list(notes), key=f"proof_{key}", format_func=lambda cid: _chip(cid, notes, items))
            if pick:
                _proof(items[pick], a, key)
        _actions(a, key)
        _thinking(a)


def render(ds, scenario):
    s = st.session_state
    s.setdefault("history", [])
    with st.container():
        typed = st.chat_input("Ask Runway anything about your money this semester", key="ask_input")
        with st.container(horizontal=True, gap="small"):
            for i, q in enumerate(agent.SUGGESTED):
                st.button(q, key=f"ask_suggest_{i}", on_click=_queue, args=(q,), type="tertiary",
                          icon=":material/chat_bubble:")
    question = typed or s.pop("ask_pending", None)
    if question:
        _ask(question, ds, scenario)
        st.rerun()
    for i, a in enumerate(s.history):
        if i == 0:
            card(a)
        else:
            with st.expander(f"Earlier: {a.question}"):
                card(a, latest=False)
