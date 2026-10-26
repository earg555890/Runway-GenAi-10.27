"""Tab 2, "Budget": where the money went (one sentence, a donut of the top categories, a table with the purchases
one click away), then the budget for next month (task 4). The UI does no money math: every total, share base and
budget comes from the engine; this module only formats and lays it out."""
from dataclasses import replace

import altair as alt
import pandas as pd
import streamlit as st

import config
import engine
import normalize
import summary
from ui import background, checkin, fmt, state

TOP = 5
BUDGET_MONTH = "2026-11"          # next month: the one she can still plan
ACCOUNTS = {"both": "Both", "checking": "Checking", "card": "Card"}
SURFACE = ("#ffffff", "#0e1117")       # Streamlit's light / dark page background (the 2px gap between slices)
INK = ("#0b0b0b", "#f0efec")
FONT = "Source Sans Pro, Source Sans 3, sans-serif"       # Streamlit's own font, so the total matches the page


def _mode(pair):
    return pair[1] if fmt.dark() else pair[0]


def _pct(part, whole):
    """Share of the total, for display only ("41%"); "<1%" for tiny slices."""
    if not whole:
        return "0%"
    v = part / whole * 100
    return "<1%" if 0 < v < 1 else f"{v:.0f}%"


def filters():
    s = st.session_state
    s.setdefault("bud_month", "2026-10")
    s.setdefault("bud_account", "both")
    with st.container(horizontal=True, gap="medium", key="bud_filters"):
        st.segmented_control("Month", [p.key for p in summary.PERIODS], key="bud_month",
                             format_func=lambda k: summary.period(k).label, required=True)
        st.segmented_control("Account", list(ACCOUNTS), key="bud_account", format_func=ACCOUNTS.get, required=True)
    return summary.period(s.bud_month), s.bud_account


def spending(ds, per, account):
    end = min(per.end, config.DEMO_TODAY)
    return engine.spending_by_category(per.start, end if not per.future else per.start, account, ds)


def top_line(sp, per):
    text = summary.sentence(sp, per)
    key = f"summary|{per.key}|{sp.account}|{sp.total.value}"
    if summary.enabled() and not per.future and sp.categories:
        background.start(key, lambda: summary.ai_summary(sp, per))
    background.slot(key, text, lambda t: st.markdown(f'<div class="rw-bud-line">{fmt.html(t)}</div>',
                                                       unsafe_allow_html=True))


def donut_rows(sp):
    """Top 5 categories that have their own color, then everything else as "Other" (at most 6 slices)."""
    named = [c for c in sp.categories if c.name in fmt.CATEGORY_COLORS][:TOP]
    rest = [c for c in sp.categories if c not in named]
    rows = [(c.name, c.spent.value) for c in named]
    if rest:
        rows.append((fmt.OTHER, sum((c.spent.value for c in rest), engine.ZERO)))
    return rows


def donut(sp):
    rows = donut_rows(sp)
    total = sp.total.value
    df = pd.DataFrame([{"category": name, "amount": float(v), "rank": i, "spent": fmt.money(v), "share": _pct(v, total)}
                       for i, (name, v) in enumerate(rows)])
    colors = [fmt.category_color(name) for name, _ in rows]
    base = alt.Chart(df).encode(
        theta=alt.Theta("amount:Q", stack=True), order=alt.Order("rank:Q"),
        color=alt.Color("category:N", scale=alt.Scale(domain=[n for n, _ in rows], range=colors), legend=None),
        tooltip=[alt.Tooltip("category:N", title="Category"), alt.Tooltip("spent:N", title="Spent"),
                 alt.Tooltip("share:N", title="Share")])
    arcs = base.mark_arc(innerRadius=68, outerRadius=108, stroke=_mode(SURFACE), strokeWidth=2, cornerRadius=2)
    big = alt.Chart(pd.DataFrame({"t": [fmt.dollars(total)]})).mark_text(
        color=_mode(INK), fontSize=24, fontWeight="bold", dy=-8, font=FONT).encode(text="t:N")
    small = alt.Chart(pd.DataFrame({"t": ["spent"]})).mark_text(
        color=_mode(INK), fontSize=15, opacity=.8, dy=16, font=FONT).encode(text="t:N")
    return (arcs + big + small).properties(width=240, height=240).configure_view(stroke=None)


def table_html(sp, per, budget):
    """Category, % of total, Amount, Budget, Left: one row per category, biggest first, with its color."""
    monthly = per.key != "semester" and bool(budget)          # Budget / Left only once she has a budget
    head = "<tr><th>Category</th><th>Share</th><th>Spent</th>" + ("<th>Budget</th><th>Left</th>" if monthly else "") + \
        "</tr>"
    rows = []
    progress_by = ({r.category: r for r in engine.budget_progress({k: v for k, v in budget.items() if v}, per.start)}
                   if monthly and budget else {})
    slices = {name for name, _ in donut_rows(sp)}          # the table is the donut's legend: folded rows are "Other"
    for c in sp.categories:
        color = fmt.category_color(c.name if c.name in slices else fmt.OTHER)
        sw = f'<span class="rw-sw-dot" style="background:{color}"></span>'
        cells = [f"{sw}{fmt.html(c.name)}", _pct(c.spent.value, sp.total.value), fmt.html(fmt.dollars(c.spent.value))]
        if monthly:
            b = budget.get(c.name)
            if c.kind == "fixed":
                cells += ['<span class="rw-muted">fixed</span>', ""]
            elif b is None:
                cells += ['<span class="rw-muted">none</span>', ""]
            else:
                left = progress_by.get(c.name)
                cells += [fmt.html(fmt.dollars(b)) if b else "$0",
                          fmt.html(f"{fmt.dollars(left.left.value)} left" if left.left.value >= 0 else
                                   f"{fmt.dollars(left.left.value)} over") if left else ""]
        rows.append("<tr>" + "".join(f"<td>{x}</td>" for x in cells) + "</tr>")
    return f'<table class="rw-bud-table">{head}{"".join(rows)}</table>'


def purchases(sp):
    """Click a category to see the purchases behind it (the proof)."""
    pick = st.pills("See the purchases in", [c.name for c in sp.categories], key="bud_pick")
    c = sp.get(pick) if pick else None
    if c:
        st.dataframe(pd.DataFrame([{"Date": fmt.day(t.date), "What": t.merchant,
                                    "Account": "Checking" if t.account == "checking" else "Card",
                                    "Amount": fmt.money(-t.amount)} for t in c.txns]),
                     hide_index=True, width="stretch",
                     column_config={"What": st.column_config.TextColumn(width="medium")})
        st.caption(f"{len(c.txns)} purchase{'s' if len(c.txns) != 1 else ''}, {fmt.money(c.spent.value)} in all. "
                   "Card payments aren't counted: they just move money between your accounts.")


def _suggest(amounts):
    state.set_budget(amounts)
    state.log("Filled in the suggested budget", "approved")


def _clear():
    state.set_budget({})
    st.session_state.wf_budget = False


def _what(label):
    """"rent 2026-11" -> "Rent", "paycheck 2026-11-03 (PAY-05)" -> "Paycheck", "Venmo 2026-11-05" -> "Venmo"."""
    words = [x for x in fmt.strip_ids(label).split() if not x[:1].isdigit() and not x.startswith("(")]
    return " ".join(words).capitalize() if words and words[0].islower() else " ".join(words)


def _how(m):
    with st.expander("How we worked this out"):
        st.dataframe(pd.DataFrame([{"Date": fmt.day(d), "What": _what(label), "Amount": fmt.money(v)}
                                   for label, d, v, _ in m.lines]),
                     hide_index=True, width="stretch", column_config=fmt.PROOF_COLUMNS)
        st.markdown(fmt.md(f"- Checking going into the month: {fmt.money(m.start_balance.value)}.\n"
                           f"- Money in: {fmt.money(m.money_in.value)}.\n"
                           f"- Rent, bills and the card bill already owed: {fmt.money(m.fixed.value)}.\n"
                           "- Card spending still to come isn't counted: that's what the budget is for."))


def progress(ds):
    """This month so far: spent vs budget per category, with the pace."""
    rows = engine.budget_progress({c: v for c, v in state.budget().items() if v}, None, ds)
    if not rows:
        return
    _, end = engine.month_span(config.DEMO_TODAY)
    st.markdown(f"**{config.DEMO_TODAY:%B} so far** (day {config.DEMO_TODAY.day} of {end.day})")
    out = []
    for r in rows:
        fill = 100 if r.pace == "over" else int(r.spent.value / r.budget * 100) if r.budget else 0
        left = (f"{fmt.dollars(r.left.value)} left" if r.left.value >= 0 else f"{fmt.dollars(r.left.value)} over")
        note = {"on pace": "on pace", "spending fast": "spending fast", "over": "over budget"}[r.pace]
        out.append(f'<div class="rw-prog"><div class="rw-prog-top"><span>{fmt.html(r.category)}</span>'
                   f'<span>{fmt.html(left)} · <span class="rw-pace-{r.pace.replace(" ", "-")}">{note}</span></span>'
                   f'</div><div class="rw-prog-track"><div class="rw-prog-fill" style="width:{fill}%;'
                   f'background:{fmt.category_color(r.category)}"></div></div>'
                   f'<div class="rw-prog-sub">{fmt.html(fmt.dollars(r.spent.value))} of '
                   f'{fmt.html(fmt.dollars(r.budget))}' + "".join(
                       f'<br>Plus a {fmt.html(fmt.dollars(-t.amount))} one-off: {fmt.html(t.merchant)}'
                       for t in r.one_offs) + '</div></div>')
    st.markdown("".join(out), unsafe_allow_html=True)


def allocate(ds, scenario):
    """Your budget for November: what's left after rent and bills, amounts per flexible category, a suggestion,
    "Left to assign", this month's progress, and the switch that puts the budget in the forecast."""
    sg = engine.suggest_budget(BUDGET_MONTH, replace(scenario, budget=()), ds)
    m = sg.available
    month = f"{m.start:%B}"
    st.markdown(f"### Your budget for {month}")
    if m.amount.value > 0:
        head = f"You have {fmt.dollars(m.amount.value)} to spend after rent and bills in {month}."
    elif not scenario.refund_released:
        head = (f"Without your refund, {month}'s bills are {fmt.dollars(m.amount.value)} more than your money. "
                "Send the verification form first.")
    else:
        head = f"{month}'s bills are {fmt.dollars(m.amount.value)} more than your money."
    st.markdown(f'<div class="rw-bud-head">{fmt.html(head)}</div>', unsafe_allow_html=True)
    if m.amount.value <= 0 and not scenario.refund_released:
        refund = next((it for it in engine.attention_items(state.done_scenario(), ds) if it.kind == "refund"), None)
        if refund:                                   # the action itself, right here: email, reminder, "Form sent"
            checkin.actions_row(refund, ds, "bud_refund")
    _how(m)
    usual = {x.category: x.average.value for x in sg.lines}
    cols = st.columns(3)
    for i, c in enumerate(normalize.FLEXIBLE):
        hint = f"usual {fmt.dollars(usual[c])}" if c in usual else "none so far"
        cols[i % 3].number_input(f"{c} ({hint})", min_value=0, max_value=5000, step=5, key=state.budget_key(c))
    left = engine.budget_left(m.amount, state.budget(), engine.Ledger())
    with st.container(horizontal=True, gap="small", vertical_alignment="center", key="bud_actions"):
        st.button("Suggest a budget", icon=":material/auto_awesome:", key="bud_suggest", disabled=not sg.fits,
                  on_click=_suggest, args=({c: int(v) for c, v in sg.amounts().items()},),
                  help="Your usual spending, scaled down to fit if needed." if sg.fits else
                  "Nothing is left after rent and bills, so no budget fits yet.")
        st.button("Clear", key="bud_clear", type="tertiary", on_click=_clear)
        if m.amount.value > 0:                       # otherwise the sentence above already says how short it is
            tone = " rw-red" if left.value < 0 else ""
            st.markdown(f'<span class="rw-bud-left{tone}">Left to assign: '
                        f'{fmt.html(fmt.dollars(left.value) + (" over" if left.value < 0 else ""))}</span>',
                        unsafe_allow_html=True)
    progress(ds)
    st.toggle("Use my budget in my forecast", key="wf_budget", disabled=not state.has_budget(),
              help="The forecast uses your budget instead of your past spending.")
    if scenario.budget:
        effect = engine.budget_effect(scenario, ds)
        st.markdown(f'<div class="rw-bud-effect">{fmt.html(summary.budget_effect_line(effect))}</div>',
                    unsafe_allow_html=True)


def render(ds, scenario):
    per, account = filters()
    sp = spending(ds, per, account)
    top_line(sp, per)
    if not (per.future or not sp.categories):
        left, right = st.columns([5, 6], vertical_alignment="center", gap="medium")
        with left:
            st.altair_chart(donut(sp), width="content", theme=None)
        with right:
            st.markdown(table_html(sp, per, state.budget() if state.has_budget() else {}), unsafe_allow_html=True)
        purchases(sp)
    st.divider()
    allocate(ds, scenario)
    return sp
