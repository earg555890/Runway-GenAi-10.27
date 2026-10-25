"""Tab 2, "Budget": where the money went (one sentence, a donut of the top categories, a table with the purchases
one click away), then the budget for next month (task 4). The UI does no money math: every total, share base and
budget comes from the engine; this module only formats and lays it out."""
import altair as alt
import pandas as pd
import streamlit as st

import config
import engine
import summary
from ui import background, fmt

TOP = 5
ACCOUNTS = {"both": "Both", "checking": "Checking", "card": "Card"}
SURFACE = ("#ffffff", "#0e1117")       # Streamlit's light / dark page background (the 2px gap between slices)
INK = ("#0b0b0b", "#f0efec")


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
        color=_mode(INK), fontSize=24, fontWeight="bold", dy=-8).encode(text="t:N")
    small = alt.Chart(pd.DataFrame({"t": ["spent"]})).mark_text(
        color=_mode(INK), fontSize=15, opacity=.8, dy=16).encode(text="t:N")
    return (arcs + big + small).properties(width=240, height=240).configure_view(stroke=None)


def table_html(sp, per, budget):
    """Category, % of total, Amount, Budget, Left: one row per category, biggest first, with its color."""
    monthly = per.key != "semester"
    head = "<tr><th>Category</th><th>Share</th><th>Spent</th>" + ("<th>Budget</th><th>Left</th>" if monthly else "") + \
        "</tr>"
    rows = []
    for c in sp.categories:
        sw = f'<span class="rw-sw-dot" style="background:{fmt.category_color(c.name)}"></span>'
        cells = [f"{sw}{fmt.html(c.name)}", _pct(c.spent.value, sp.total.value), fmt.html(fmt.dollars(c.spent.value))]
        if monthly:
            b = budget.get(c.name)
            if c.kind == "fixed":
                cells += ['<span class="rw-muted">fixed</span>', ""]
            elif b is None:
                cells += ['<span class="rw-muted">none</span>', ""]
            else:
                left = engine.D(b) - c.spent.value
                cells += [fmt.html(fmt.dollars(b)) if b else "$0",
                          fmt.html(f"{fmt.dollars(left)} left" if left >= 0 else f"{fmt.dollars(left)} over")]
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


def render(ds, budget=None):
    budget = budget or {}
    per, account = filters()
    sp = spending(ds, per, account)
    top_line(sp, per)
    if per.future or not sp.categories:
        return sp
    left, right = st.columns([5, 6], vertical_alignment="center", gap="medium")
    with left:
        st.altair_chart(donut(sp), width="content", theme=None)
    with right:
        st.markdown(table_html(sp, per, budget), unsafe_allow_html=True)
    purchases(sp)
    return sp
