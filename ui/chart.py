"""The balance chart ("Your money through Dec 18"). Every balance and event comes from the engine; this module only
decides how to draw it.

- Two lines, one point per day (each day's end-of-day balance), drawn with MONOTONE interpolation: corners are softly
  rounded, a big drop like rent still happens within its one day, and the line never overshoots the real values.
  - SOLID, bold: "What's happening", the forecast with the student's current choices. Split where it crosses $0:
    red below $0 (alert red only for below zero).
  - DOTTED, fainter, green: "If you follow the steps", the forecast with the recommended steps applied (the fixes
    that still help: send the verification form, cancel Spotify; never "if approved" aid). Drawn only when it
    differs from the solid line.
- A solid, clear $0 line; a dashed "Runs out · Mon, Nov 9" marker for the solid line, or "Covered all semester"; the dotted
  line's lowest point labelled ("With the steps: lowest $5.81").
- Hover anywhere: a vertical dashed guide, dots on both lines, and a tooltip pill with each line's balance that day and
  that day's events ("Card payment $360").
"""
from datetime import datetime, time, timedelta

import altair as alt
import pandas as pd

import config
import engine
from ui import fmt

# One palette, shared with style.py's CSS variables (readable on the paper and the night-navy backgrounds).
LINE, STEPS, RED, ZERO, GRID, LABEL = "#3F78C0", "#2E8F62", "#C8402F", "#8A94A6", "#8A94A6", "#7A8599"
FONT, MONO = "Runway Body, sans-serif", "Runway Mono, monospace"     # config.toml fontFaces (plain-zero digits)
SHORT = {"rent": "Rent", "card_autopay": "Card payment", "installment": "Tuition payment", "paycheck": "Paycheck",
         "refund": "Refund"}


def _ts(x):
    return x.isoformat(timespec="minutes") if isinstance(x, datetime) else f"{x.isoformat()}T00:00"


def _at(d, hours=0):
    return datetime.combine(d, time()) + timedelta(hours=hours)


def _name(e):
    return e.label if e.kind == "purchase" else SHORT.get(e.kind, fmt.event_name(e).capitalize())


def day_points(p):
    """[(date, end-of-day balance)]: today, then one point per day to the end of the semester."""
    return [(config.DEMO_TODAY, float(p.start_balance.value))] + [(d, float(b)) for d, b in p.daily]


def split_at_zero(pts):
    """Runs of the daily points that stay on one side of $0, with the crossing point inserted. [(sign, [(x, y)])]
    x is a datetime; the crossing sits at the interpolated time between the two days."""
    out = []
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        segs = [((x1, y1), (x2, y2))]
        if (y1 < 0 < y2) or (y2 < 0 < y1):
            xc = x1 + (x2 - x1) * ((0 - y1) / (y2 - y1))
            segs = [((x1, y1), (xc, 0.0)), ((xc, 0.0), (x2, y2))]
        for a, b in segs:
            sign = "neg" if (a[1] + b[1]) / 2 < 0 else "pos"
            if out and out[-1][0] == sign and out[-1][1][-1] == a:
                out[-1][1].append(b)
            else:
                out.append((sign, [a, b]))
    return out


def _ticks(lo, hi):
    span = hi - lo
    step = next(s for s in (100, 250, 500, 1000, 2000, 5000) if span / s <= 6)
    first = int(lo // step) * step
    return [v for v in range(first, int(hi) + step, step) if lo <= v <= hi]


def steps_scenario(scenario, ds, ledger=None):
    """The current choices plus every recommended step not taken yet (fixes that still add money this semester).
    None when no step is left. Engine fixes only: never "if approved" aid."""
    fixes = [f for f in engine.available_fixes(scenario, ds, ledger or engine.Ledger()) if f.savings.value > 0]
    if not fixes:
        return None
    for f in fixes:
        scenario = f.apply(scenario)
    return scenario


def build(current, steps=None, mode="light"):
    """The chart for the current forecast, with the "If you follow the steps" forecast as a dotted line (or None).
    mode ("light"/"dark") picks the text colors from style.PALETTE (4.5:1 on the page); lines keep the brand colors."""
    from ui import style
    pal = style.PALETTE[mode]
    red_text, green_text, label = pal["red_text"], pal["green_text"], pal["axis"]
    now = day_points(current)
    alt_pts = day_points(steps) if steps is not None else None
    dates = [d for d, _ in now]
    end_pad = _at(config.SEMESTER_END, 24)
    values = [b for _, b in now] + ([b for _, b in alt_pts] if alt_pts else []) + [0.0]
    lo, hi = min(values), max(values)
    pad = max(60.0, (hi - lo) * 0.12)
    lo, hi = lo - pad, hi + pad * 1.6                                  # room on top for the markers' labels
    mondays = [d for d in dates if d.weekday() == 0]

    x = alt.X("x:T", title=None, scale=alt.Scale(domain=[_ts(_at(config.DEMO_TODAY)), _ts(end_pad)]),
              axis=alt.Axis(format="%b %-d", values=[_ts(_at(d)) for d in mondays], labelAngle=0, grid=False,
                            domain=False, ticks=False, labelFont=FONT, labelFontSize=12, labelColor=label,
                            labelPadding=8, labelOverlap="greedy"))
    y = alt.Y("y:Q", title=None, scale=alt.Scale(domain=[lo, hi], nice=False),
              axis=alt.Axis(values=_ticks(lo, hi), format="$,.0f", labelFont=MONO, labelFontSize=11.5,
                            labelColor=label, gridColor=GRID, gridOpacity=0.16, gridDash=[2, 4], domain=False,
                            ticks=False, labelPadding=6))

    layers = [alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(color=label, strokeWidth=1.6, opacity=0.85)
              .encode(y="y:Q")]                                                  # the $0 line: solid and clear
    if alt_pts:
        steps_df = pd.DataFrame([{"x": _ts(_at(d)), "y": b, "o": i} for i, (d, b) in enumerate(alt_pts)])
        layers.append(alt.Chart(steps_df).mark_line(color=STEPS, strokeWidth=3, strokeDash=[0.1, 7], strokeCap="round",
                                                    opacity=0.85, interpolate="monotone")
                      .encode(x, y, order="o:Q"))
    rows = []
    for run, (sign, seg) in enumerate(split_at_zero([(_at(d), b) for d, b in now])):
        rows += [{"x": _ts(px), "y": py, "sign": sign, "run": run, "o": i} for i, (px, py) in enumerate(seg)]
    color = alt.Color("sign:N", scale=alt.Scale(domain=["pos", "neg"], range=[LINE, RED]), legend=None)
    line_df = pd.DataFrame(rows)
    layers += [
        alt.Chart(line_df).mark_area(opacity=0.07, interpolate="monotone").encode(
            x, y, alt.Y2(datum=0), color=color, detail="run:N", order="o:Q"),
        alt.Chart(line_df).mark_line(strokeWidth=3.5, interpolate="monotone", strokeCap="round", strokeJoin="round")
        .encode(x, y, color=color, detail="run:N", order="o:Q"),
    ]

    run_out = current.first_below_zero.value
    if run_out:
        mx = _at(run_out)
        late = run_out > config.SEMESTER_END - timedelta(days=21)
        layers += [
            alt.Chart(pd.DataFrame({"x": [_ts(mx)]})).mark_rule(color=RED, strokeDash=[4, 4], strokeWidth=1.5)
            .encode(x="x:T"),
            alt.Chart(pd.DataFrame({"x": [_ts(mx)], "y": [hi], "t": [f"RUNS OUT · {fmt.day(run_out).upper()}"]}))
            .mark_text(align="right" if late else "left", dx=-8 if late else 8, dy=14, fontSize=12.5,
                       fontWeight=600, font=MONO, color=red_text).encode(x, y, text="t:N"),
        ]
    else:
        layers.append(alt.Chart(pd.DataFrame({"x": [_ts(_at(config.SEMESTER_END))], "y": [hi],
                                              "t": ["COVERED ALL SEMESTER"]}))
                      .mark_text(align="right", dy=14, fontSize=12.5, fontWeight=600, font=MONO, color=green_text)
                      .encode(x, y, text="t:N"))
    if alt_pts:
        low_d, low_v = min(alt_pts, key=lambda t: (t[1], t[0]))
        near_end = low_d > config.SEMESTER_END - timedelta(days=14)
        layers += [
            alt.Chart(pd.DataFrame({"x": [_ts(_at(low_d))], "y": [low_v]}))
            .mark_point(shape="circle", size=55, filled=True, color=STEPS, stroke="white", strokeWidth=1.5)
            .encode(x, y),
            alt.Chart(pd.DataFrame({"x": [_ts(_at(low_d))], "y": [low_v],
                                    "t": [f"With the steps: lowest {fmt.balance(low_v)}"]}))
            .mark_text(align="right" if near_end else "center", dx=-8 if near_end else 0, dy=20, fontSize=12,
                       fontWeight=600, font=FONT, color=green_text).encode(x, y, text="t:N"),
        ]

    # Hover: one invisible point per day carrying both balances and that day's events; a dashed guide and dots.
    events = {}
    for e in current.events:
        events.setdefault(e.date, []).append(f"{_name(e)} {fmt.dollars(abs(e.amount))}")
    alt_by_day = dict(alt_pts) if alt_pts else {}
    days = pd.DataFrame([{"x": _ts(_at(d)), "y": b, "when": fmt.day(d), "now": fmt.balance(b),
                          "steps": fmt.balance(alt_by_day[d]) if d in alt_by_day else "",
                          "ys": alt_by_day.get(d, b), "events": "; ".join(events.get(d, [])) or "No scheduled payments"}
                         for d, b in now])
    tip = [alt.Tooltip("when:N", title="Day"), alt.Tooltip("now:N", title="What's happening")]
    if alt_pts:
        tip.append(alt.Tooltip("steps:N", title="If you follow the steps"))
    tip.append(alt.Tooltip("events:N", title="That day"))
    hover = alt.selection_point(fields=["x"], nearest=True, on="pointerover", empty=False, clear="pointerout")
    layers += [
        # a full-height, invisible strip per day: the pill shows wherever the pointer is on that day
        alt.Chart(days).mark_rule(strokeWidth=14, opacity=0.001).encode(x, alt.Y(datum=lo), alt.Y2(datum=hi),
                                                                         tooltip=tip).add_params(hover),
        alt.Chart(days).mark_rule(color=ZERO, strokeWidth=1, strokeDash=[3, 3]).encode(x, tooltip=tip)
        .transform_filter(hover),
        alt.Chart(days).mark_point(filled=True, size=70, color=LINE, stroke="white", strokeWidth=2)
        .encode(x, y, tooltip=tip).transform_filter(hover),
    ]
    if alt_pts:                         # the dotted line's dot: same y encoding (a separate axis=None would hide it)
        steps_days = days.assign(y=days["ys"])
        layers.append(alt.Chart(steps_days).mark_point(filled=True, size=60, color=STEPS, stroke="white", strokeWidth=2)
                      .encode(x, y, tooltip=tip).transform_filter(hover))
    return alt.layer(*layers).properties(height=320).configure(font=FONT, background="transparent",
                                                               view={"strokeWidth": 0})
