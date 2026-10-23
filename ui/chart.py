"""Checking balance, today through the end of the semester: base vs current, $0 line, shaded overdraft zone."""
import altair as alt
import pandas as pd
import streamlit as st

import config
from ui import fmt

KEY_EVENTS = {"rent": "Rent", "paycheck": "Paycheck", "card_autopay": "Card autopay",
              "installment": "Payment-plan installment", "refund": "Refund released", "purchase": "Purchase"}
BASE, CURRENT = "If nothing changes", "With your changes"


def _ts(d):
    return f"{d.isoformat()}T00:00:00"        # local time, so Vega does not shift the day


def _series(p, name):
    pts = [(config.DEMO_TODAY, p.start_balance.value)] + p.daily
    return [{"date": _ts(d), "balance": float(b), "scenario": name, "when": fmt.day(d), "bal": fmt.money(b)}
            for d, b in pts]


def build(base, current, same):
    lines = pd.DataFrame(_series(base, BASE) + ([] if same else _series(current, CURRENT)))
    events = pd.DataFrame([{"date": _ts(e.date), "balance": float(current.balance_on(e.date)), "when": fmt.day(e.date),
                            "what": e.label if e.kind == "purchase" else KEY_EVENTS[e.kind],
                            "kind": KEY_EVENTS[e.kind], "amount": fmt.signed_money(e.amount) or fmt.money(0),
                            "bal": fmt.money(current.balance_on(e.date))}
                           for e in current.events if e.kind in KEY_EVENTS])
    low = min(base.lowest.value, current.lowest.value, 0)
    floor = float(low) * 1.1 - 50
    x = alt.X("date:T", title=None, axis=alt.Axis(format="%b %d", labelAngle=0, tickCount="week"))
    y = alt.Y("balance:Q", title="Checking balance", axis=alt.Axis(format="$,.0f"))
    colors = alt.Color("scenario:N", title=None, legend=alt.Legend(orient="top"),
                       scale=alt.Scale(domain=[BASE, CURRENT], range=["#8a94a6", "#2563eb"]))
    tip = [alt.Tooltip("when:N", title="Date"), alt.Tooltip("scenario:N", title="Scenario"),
           alt.Tooltip("bal:N", title="Balance")]

    danger = alt.Chart(pd.DataFrame({"y": [0.0], "y2": [floor]})).mark_rect(color="#ef4444", opacity=0.08).encode(
        y="y:Q", y2="y2:Q")
    zero = alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(color="#dc2626", strokeWidth=1.5).encode(y="y:Q")
    zero_label = alt.Chart(pd.DataFrame({"y": [0.0], "t": ["$0: overdraft below this line"]})).mark_text(
        align="left", dx=4, dy=-7, color="#dc2626", fontSize=11).encode(y="y:Q", text="t:N", x=alt.value(0))
    path = alt.Chart(lines).mark_line(interpolate="step-after", strokeWidth=2.5).encode(
        x, y, color=colors, strokeDash=alt.condition(alt.datum.scenario == BASE, alt.value([5, 4]), alt.value([1, 0])))
    hover = alt.Chart(lines).mark_point(size=80, opacity=0).encode(x, y, tooltip=tip)
    layers = [danger, zero, zero_label, path, hover]
    if not events.empty:
        layers.append(alt.Chart(events).mark_point(filled=True, size=90, stroke="white", strokeWidth=1).encode(
            x, y, shape=alt.Shape("kind:N", title=None, legend=alt.Legend(orient="bottom")),
            color=alt.value("#111827"),
            tooltip=[alt.Tooltip("when:N", title="Date"), alt.Tooltip("what:N", title="What"),
                     alt.Tooltip("amount:N", title="Amount"), alt.Tooltip("bal:N", title="Balance that day")]))
    return alt.layer(*layers).properties(height=380).resolve_scale(color="independent", shape="independent")


def render(base, current, same):
    st.subheader("Your checking balance through the semester")
    st.altair_chart(build(base, current, same), width="stretch")
    st.caption("End-of-day balances. Hover over the markers to see rent, paychecks, card autopays, the payment-plan "
               "installment, the refund and purchases.")
