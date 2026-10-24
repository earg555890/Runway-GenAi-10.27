"""The balance chart: your balance through the semester, soft blue fill above $0 and red below, a bold $0 line,
"Today", the lowest point and the ending balance labelled, the biggest events as ticks along the bottom, and
every event of a day in the hover tooltip. Every balance and event comes from the engine."""
from datetime import timedelta

import altair as alt
import pandas as pd

import config
from ui import fmt

SHORT = {"rent": "Rent", "card_autopay": "Card payment", "installment": "Tuition payment", "paycheck": "Paycheck",
         "refund": "Refund"}
TICKS = 5                    # at most this many events get a labelled tick along the bottom
BLUE, RED, GREY = "#2563eb", "#dc2626", "#9ca3af"
LABEL, LABEL_BLUE = "#7c8aa5", "#3b82f6"   # mid-tones: readable on light and dark themes
BEFORE, WITH = "Before your changes", "With your changes"


def _ts(d):
    return f"{d.isoformat()}T00:00:00"        # local time, so the chart does not shift the day


def _event_name(e):
    return e.label if e.kind == "purchase" else SHORT.get(e.kind, fmt.event_name(e).capitalize())


def _flow(e):
    """An event in plain words for tooltips: "Card payment: $360 out"."""
    return f"{_event_name(e)}: {fmt.dollars(e.amount)} {'in' if e.amount > 0 else 'out'}"


def _days(base, current, changed):
    """One row per day: the balance, the 'before' balance, and every event of that day for the tooltip."""
    by_day = {}
    for e in current.events:
        by_day.setdefault(e.date, []).append(_flow(e))
    before = dict([(config.DEMO_TODAY, base.start_balance.value)] + base.daily)
    rows = []
    for d, b in [(config.DEMO_TODAY, current.start_balance.value)] + current.daily:
        rows.append({"date": _ts(d), "balance": float(b), "when": fmt.day(d), "bal": fmt.balance(b),
                     "before": float(before[d]), "before_txt": fmt.balance(before[d]) if changed else "",
                     "events": "; ".join(by_day.get(d, [])) or "Everyday spending only"})
    return pd.DataFrame(rows)


def build(base, current, changed):
    days = _days(base, current, changed)
    low_v = min(base.lowest.value, current.lowest.value, 0)
    high_v = max(max(b for _, b in current.daily), max(b for _, b in base.daily), current.start_balance.value)
    floor, ceil = float(low_v) - 0.18 * float(high_v - low_v) - 50, float(high_v) * 1.12 + 50
    end_pad = config.SEMESTER_END + timedelta(days=9)          # room for the end-of-semester label
    x = alt.X("date:T", title=None, scale=alt.Scale(domain=[_ts(config.DEMO_TODAY), _ts(end_pad)]),
              axis=alt.Axis(format="%b %-d", labelAngle=0, grid=False, labelFontSize=13,
                            values=[_ts(d) for d, _ in current.daily if d.day in (1, 15)]))
    y = alt.Y("balance:Q", title=None, scale=alt.Scale(domain=[floor, ceil], nice=False),
              axis=alt.Axis(format="$,.0f", tickCount=5, labelFontSize=13, gridOpacity=0.35, domain=False))
    daily = alt.Chart(days)
    layers = [
        daily.transform_calculate(pos="max(datum.balance, 0)").mark_area(
            interpolate="step-after", color=BLUE, opacity=0.12).encode(x, alt.Y("pos:Q"), alt.Y2(datum=0)),
        daily.transform_calculate(neg="min(datum.balance, 0)").mark_area(
            interpolate="step-after", color=RED, opacity=0.22).encode(x, alt.Y("neg:Q"), alt.Y2(datum=0)),
        alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(color=RED, strokeWidth=2.5).encode(y=alt.Y("y:Q")),
        alt.Chart(pd.DataFrame({"y": [0.0], "date": [_ts(end_pad)], "t": ["$0"]})).mark_text(
            align="right", dy=-9, color=RED, fontSize=13, fontWeight="bold").encode(x, alt.Y("y:Q"), text="t:N"),
    ]
    if changed:
        layers.append(daily.mark_line(interpolate="step-after", strokeDash=[5, 4], strokeWidth=1.6).encode(
            x, alt.Y("before:Q"),
            color=alt.Color("line:N", scale=alt.Scale(domain=[BEFORE, WITH], range=[GREY, BLUE]),
                            legend=alt.Legend(orient="top", direction="horizontal", title=None, labelFontSize=13)))
                      .transform_calculate(line=f"'{BEFORE}'"))
    line_color = (alt.Color("line:N", scale=alt.Scale(domain=[BEFORE, WITH], range=[GREY, BLUE]), legend=None)
                  if changed else alt.value(BLUE))
    layers.append(daily.transform_calculate(line=f"'{WITH}'").mark_line(
        interpolate="step-after", strokeWidth=3).encode(x, y, color=line_color))

    # Today, the lowest point, and the end of the semester. The amounts are in the figures right above the chart,
    # so the chart only names the points (no repeated numbers); the exact values are in the hover tooltip.
    start, low, end = current.start_balance.value, current.lowest, current.end_balance
    marks = pd.DataFrame([
        {"date": _ts(config.DEMO_TODAY), "balance": float(start), "t": "Today", "kind": "today"},
        {"date": _ts(current.lowest_date.value), "balance": float(low.value), "t": "Lowest point", "kind": "low"},
        {"date": _ts(config.SEMESTER_END), "balance": float(end.value), "t": "", "kind": "end"},
    ])
    low_color = RED if low.value < 0 else "#16a34a"
    early = current.lowest_date.value < config.DEMO_TODAY + timedelta(days=21)
    layers += [
        alt.Chart(marks[marks.kind != "low"]).mark_circle(size=110, opacity=1, stroke="white", strokeWidth=1.5,
                                                          color=BLUE).encode(x, y),
        alt.Chart(marks[marks.kind == "low"]).mark_circle(size=130, opacity=1, stroke="white", strokeWidth=1.5,
                                                          color=low_color).encode(x, y),
        alt.Chart(marks[marks.kind == "today"]).mark_text(align="left", dx=8, dy=-12, fontSize=13, fontWeight="bold",
                                                         color=LABEL_BLUE).encode(x, y, text="t:N"),
        alt.Chart(marks[marks.kind == "low"]).mark_text(align="left" if early else "right", dx=12 if early else -12,
                                                       dy=-12 if early else 0, fontSize=13, fontWeight="bold",
                                                       color=low_color).encode(x, y, text="t:N"),
    ]

    # The biggest events as labelled ticks along the bottom (staggered so neighbours don't collide)
    keyed = [e for e in current.events if e.kind in SHORT or e.kind == "purchase"]
    big = sorted(sorted(keyed, key=lambda e: abs(e.amount), reverse=True)[:TICKS], key=lambda e: e.date)
    if big:
        ticks = pd.DataFrame([{"date": _ts(e.date), "y": floor, "t": _event_name(e), "row": i % 3,
                               "tip": _flow(e), "when": fmt.day(e.date)}
                              for i, e in enumerate(big)])
        tick_tip = [alt.Tooltip("when:N", title="Date"), alt.Tooltip("tip:N", title="What")]
        layers.append(alt.Chart(ticks).mark_tick(thickness=2, size=14, color=LABEL)
                      .encode(x, alt.Y("y:Q"), tooltip=tick_tip))
        for row in range(3):                    # three rows: neighbours stay readable on a phone too
            layers.append(alt.Chart(ticks[ticks.row == row]).mark_text(dy=-14 - 14 * row, fontSize=12, color=LABEL)
                          .encode(x, alt.Y("y:Q"), text="t:N", tooltip=tick_tip))

    # Hover anywhere: a guide line and that day's balance and events
    hover = alt.selection_point(fields=["date"], nearest=True, on="pointerover", empty=False, clear="pointerout")
    tip = [alt.Tooltip("when:N", title="Date"), alt.Tooltip("bal:N", title="Your balance"),
           alt.Tooltip("events:N", title="That day")]
    if changed:
        tip.insert(2, alt.Tooltip("before_txt:N", title=BEFORE))
    layers += [
        daily.mark_point(opacity=0, size=300).encode(x, y, tooltip=tip).add_params(hover),
        daily.mark_rule(color=GREY, strokeWidth=1).encode(x, tooltip=tip).transform_filter(hover),
    ]
    return alt.layer(*layers).properties(height=360).configure_view(strokeWidth=0)
