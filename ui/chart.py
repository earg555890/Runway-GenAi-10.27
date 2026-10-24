"""One line: your balance through the end of the semester, a $0 line, red below $0, the biggest events labelled."""
import altair as alt
import pandas as pd

import config
from ui import fmt

SHORT = {"rent": "Rent", "card_autopay": "Card payment", "installment": "Tuition payment", "paycheck": "Paycheck",
         "refund": "Refund"}
LABELLED = 5           # at most this many events get a label on the chart; the rest only on hover


def _ts(d):
    return f"{d.isoformat()}T00:00:00"        # local time, so the chart does not shift the day


def _series(p, name):
    pts = [(config.DEMO_TODAY, p.start_balance.value)] + p.daily
    return [{"date": _ts(d), "balance": float(b), "line": name, "when": fmt.day(d), "bal": fmt.money(b)} for d, b in pts]


def build(base, current, changed):
    yours = pd.DataFrame(_series(current, "Your balance"))
    events = [e for e in current.events if e.kind in SHORT or e.kind == "purchase"]
    big = sorted(events, key=lambda e: abs(e.amount), reverse=True)[:LABELLED]
    marks = pd.DataFrame([{"date": _ts(e.date), "balance": float(current.balance_on(e.date)), "when": fmt.day(e.date),
                           "what": e.label if e.kind == "purchase" else SHORT[e.kind],
                           "amount": fmt.money(e.amount), "bal": fmt.money(current.balance_on(e.date)),
                           "show": e in big} for e in events])
    floor = float(min(base.lowest.value, current.lowest.value, 0)) * 1.15 - 100

    x = alt.X("date:T", title=None, axis=alt.Axis(format="%b %-d", labelAngle=0, tickCount="week", grid=False))
    y = alt.Y("balance:Q", title=None, axis=alt.Axis(format="$,.0f", tickCount=6))
    layers = [
        alt.Chart(pd.DataFrame({"y": [0.0], "y2": [floor]})).mark_rect(color="#ef4444", opacity=0.10)
        .encode(y="y:Q", y2="y2:Q"),
        alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(color="#dc2626", strokeWidth=1.5).encode(y="y:Q"),
        alt.Chart(pd.DataFrame({"y": [0.0], "t": ["$0"]})).mark_text(align="left", dx=4, dy=-8, color="#dc2626")
        .encode(y="y:Q", text="t:N", x=alt.value(0)),
    ]
    if changed:
        before = pd.DataFrame(_series(base, "Before your what-ifs"))
        layers.append(alt.Chart(before).mark_line(interpolate="step-after", strokeDash=[5, 4], color="#9ca3af",
                                                  strokeWidth=2).encode(x, y, tooltip=[
                                                      alt.Tooltip("when:N", title="Date"),
                                                      alt.Tooltip("bal:N", title="Before your what-ifs")]))
    layers += [
        alt.Chart(yours).mark_line(interpolate="step-after", color="#2563eb", strokeWidth=3).encode(x, y),
        alt.Chart(yours).mark_point(size=90, opacity=0).encode(
            x, y, tooltip=[alt.Tooltip("when:N", title="Date"), alt.Tooltip("bal:N", title="Your balance")]),
    ]
    if not marks.empty:
        tip = [alt.Tooltip("when:N", title="Date"), alt.Tooltip("what:N", title="What"),
               alt.Tooltip("amount:N", title="Amount"), alt.Tooltip("bal:N", title="Balance that day")]
        layers.append(alt.Chart(marks).mark_circle(size=70, color="#1f2937").encode(x, y, tooltip=tip))
        layers.append(alt.Chart(marks).transform_filter("datum.show").mark_text(dy=-14, fontSize=12, fontWeight=600)
                      .encode(x, y, text="what:N", tooltip=tip))
    return alt.layer(*layers).properties(height=340)
