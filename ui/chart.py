"""The balance chart. Every balance and event comes from the engine; this module only decides how to draw it.

- The line goes through end-of-day balances with straight segments, so everyday spending is a gentle slope.
  Only on days with a scheduled event (rent, paycheck, card payment, refund, purchase) does the line make a
  vertical step, at mid-day, so big events look like steps and nothing else does.
- The line is split where it crosses $0: blue (green when covered all semester) above, red below, each with a
  faint tint down to the $0 line.
- A dashed marker at the first day below $0 ("Runs out · Mon, Nov 9"), or a green "Covered all semester" note.
- 2-3 story events are labelled right at their step, in the first spot (above/below, right/left of the step)
  whose estimated box clears the lines, the other labels and the edges at phone width (_Layout). A label with no
  room on a phone is drawn only on wide charts. All events are small dots with details on hover.
- The lowest point gets one small marker with its label below it (the line never goes below its lowest point,
  so that space is always free). "Today" sits bottom-left, over the first date.
"""
from datetime import datetime, time, timedelta

import altair as alt
import pandas as pd

import config
import engine
from ui import fmt

BLUE, GREEN, RED, GREY, ZERO = "#2563eb", "#16a34a", "#dc2626", "#9ca3af", "#8b93a3"
LABEL = "#7c8aa5"
SHORT = {"rent": "Rent", "card_autopay": "Card payment", "installment": "Tuition payment", "paycheck": "Paycheck",
         "refund": "Refund"}
STEP_KINDS = {"rent", "paycheck", "card_autopay", "installment", "refund", "purchase", "subscription",
              "recurring_bill"}


def _ts(x):
    return x.isoformat(timespec="minutes") if isinstance(x, datetime) else f"{x.isoformat()}T00:00"


def _at(d, hours=0):
    return datetime.combine(d, time()) + timedelta(hours=hours)


def _name(e):
    return e.label if e.kind == "purchase" else SHORT.get(e.kind, fmt.event_name(e).capitalize())


def _flow(e):
    return f"{_name(e)}: {fmt.dollars(e.amount)} {'in' if e.amount > 0 else 'out'}"


def _story_label(e):
    sign = "+" if e.amount > 0 else ""
    name = " ".join(e.label.split()[:2]) if e.kind == "purchase" else _name(e)     # short: "Flight home"
    return f"{name} {sign}{fmt.dollars(e.amount)}"


def polyline(p):
    """[(x, balance)]: end-of-day points joined by straight lines; a vertical step at mid-day on event days."""
    step_days = {e.date for e in p.events if e.kind in STEP_KINDS}
    prev = float(p.start_balance.value)
    pts = [(_at(config.DEMO_TODAY), prev)]
    for d, b in p.daily:
        if d in step_days:
            mid = _at(d, -12)
            pts += [(mid, prev), (mid, float(b))]
        pts.append((_at(d), float(b)))
        prev = float(b)
    return pts


def split_at_zero(pts):
    """Runs of the polyline that stay on one side of $0, with crossing points inserted. [(sign, [(x, y)])]"""
    out = []
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if (y1 < 0 < y2) or (y2 < 0 < y1):                        # crosses $0: split at the crossing point
            frac = (0 - y1) / (y2 - y1)
            xc = x1 + (x2 - x1) * frac
            segs = [((x1, y1), (xc, 0.0)), ((xc, 0.0), (x2, y2))]
        else:
            segs = [((x1, y1), (x2, y2))]
        for a, b in segs:
            sign = "neg" if (a[1] + b[1]) / 2 < 0 else "pos"
            if out and out[-1][0] == sign and out[-1][1][-1] == a:
                out[-1][1].append(b)
            else:
                out.append((sign, [a, b]))
    return out


def story_events(p):
    """The 2-3 events that explain the line: what tips it below $0 and the biggest drops after; or, when covered,
    what brings it closest to $0 and the biggest money coming in."""
    r = engine.main_reason(p)
    pool = [e for e in p.events if e.kind in STEP_KINDS and e.kind != "paycheck"]
    picked = [r.event] if r.event else []
    if p.lasts_through_semester:
        ins = sorted((e for e in pool if e.amount > 0 and e not in picked), key=lambda e: -e.amount)
        picked += ins[:1]
    else:
        after = sorted((e for e in pool if e.amount < 0 and e.date > p.first_below_zero.value),
                       key=lambda e: e.amount)
        picked += after[:2]
    return sorted(picked, key=lambda e: e.date)


PHONE_W, WIDE_W, PLOT_H = 285, 700, 250     # plot px: width at a 400 px page, a laptop minimum, height
# a label that only fits on a wide plot is hidden when the plot is narrower than WIDE_W (it stays on hover)


class _Layout:
    """Rough label boxes in px, so story labels can avoid the lines, each other and the edges. Estimates only:
    the real chart width isn't known here, so each spot is checked at phone width and at laptop width."""

    def __init__(self, lo, hi, lines, width):
        self.lo, self.hi, self.w = lo, hi, width
        self.boxes, self.segs = [], []
        for pts in lines:
            self.segs += [(self.px(a), self.py(ya), self.px(b), self.py(yb)) for (a, ya), (b, yb) in zip(pts, pts[1:])]

    def px(self, x):
        span = (_at(config.SEMESTER_END + timedelta(days=3)) - _at(config.DEMO_TODAY)).total_seconds()
        return (x - _at(config.DEMO_TODAY)).total_seconds() / span * self.w

    def py(self, v):
        return (self.hi - v) / (self.hi - self.lo) * PLOT_H

    def box(self, x, y, text, align, dx, dy):
        w, cx, cy = 5.6 * len(text), self.px(x) + dx, self.py(y) + dy
        x0 = {"left": cx, "right": cx - w, "center": cx - w / 2}[align]
        return x0, cy - 6, x0 + w, cy + 6

    def free(self, b):
        x0, y0, x1, y1 = b
        if x0 < 0 or x1 > self.w or y0 < 0 or y1 > PLOT_H:
            return False
        if any(x0 < c1 and c0 < x1 and y0 < d1 and d0 < y1 for c0, d0, c1, d1 in self.boxes):
            return False
        for ax, ay, bx, by in self.segs:
            if max(ax, bx) < x0 or min(ax, bx) > x1:
                continue
            if ax == bx:
                ys = (ay, by)
            else:                                    # the segment's y range inside the box's x range
                t0, t1 = sorted(((x0 - ax) / (bx - ax), (x1 - ax) / (bx - ax)))
                t0, t1 = max(t0, 0.0), min(t1, 1.0)
                ys = (ay + (by - ay) * t0, ay + (by - ay) * t1)
            if min(ys) < y1 and max(ys) > y0:
                return False
        return True


def _spots(e, prev, after):
    """Places to try for a story label at its step, best first: (y, align, dx, dy)."""
    if e.amount < 0:      # a drop: above the higher line before it, below the lower line after it, then the left
        return [(prev, "left", 7, -11), (after, "left", 7, 15), (prev, "right", -7, -11), (after, "right", -7, -11),
                (after, "right", -7, 15)]
    return [(after, "left", 7, -11), (prev, "left", 7, 15), (after, "right", -7, -11), (prev, "right", -7, 15)]


def _placement(e, prev, after, phone, wide):
    """(x, y, align, dx, dy, wide_only): the first spot free at phone width; else one free on a laptop, shown
    only on wide charts."""
    x = _at(e.date, -12)
    text = _story_label(e)
    for layouts, wide_only in (((phone, wide), False), ((wide,), True)):
        for y, align, dx, dy in _spots(e, prev, after):
            boxes = [lay.box(x, y, text, align, dx, dy) for lay in layouts]
            if all(lay.free(b) for lay, b in zip(layouts, boxes)):
                for lay, b in zip(layouts, boxes):
                    lay.boxes.append(b)
                return (x, y, align, dx, dy, wide_only)
    y, align, dx, dy = _spots(e, prev, after)[0]
    return (x, y, align, dx, dy, True)


def _ticks(lo, hi):
    for step in (100, 250, 500, 1000, 2000, 5000):
        first = (int(lo // step) + (0 if lo % step == 0 else 1)) * step
        values = list(range(first, int(hi) + 1, step))
        if len(values) <= 5:
            return values
    return [0]


def build(base, current, changed):
    covered = current.lasts_through_semester
    up = GREEN if covered else BLUE
    balances = [(config.DEMO_TODAY, float(current.start_balance.value))] + [(d, float(b)) for d, b in current.daily]
    all_values = [b for _, b in balances] + ([float(b) for _, b in base.daily] if changed else [])
    lo_v, hi_v = min(min(all_values), 0.0), max(max(all_values), 0.0)
    span = hi_v - lo_v or 1.0
    lo, hi = lo_v - 0.16 * span, hi_v + 0.16 * span
    ticks = _ticks(lo, hi)
    end_pad = _at(config.SEMESTER_END + timedelta(days=3))
    mondays = [d for d, _ in balances if d.weekday() == 0]
    x = alt.X("x:T", title=None, scale=alt.Scale(domain=[_ts(_at(config.DEMO_TODAY)), _ts(end_pad)]),
              axis=alt.Axis(format="%b %-d", values=[_ts(_at(d)) for d in mondays], labelAngle=0, grid=False,
                            labelFontSize=12, labelOverlap="parity", tickSize=4))
    y = alt.Y("y:Q", title=None, scale=alt.Scale(domain=[lo, hi], nice=False),
              axis=alt.Axis(values=ticks, format="$,.0f", labelFontSize=12, gridOpacity=0.18, domain=False,
                            tickSize=0))

    # the line, split at $0, with faint tints down to $0
    runs = split_at_zero(polyline(current))
    rows = [{"x": _ts(px), "y": py, "run": i, "sign": sign, "o": j}
            for i, (sign, pts) in enumerate(runs) for j, (px, py) in enumerate(pts)]
    line_df = pd.DataFrame(rows)
    color = alt.Color("sign:N", scale=alt.Scale(domain=["pos", "neg"], range=[up, RED]), legend=None)
    layers = [
        alt.Chart(line_df).mark_area(opacity=0.08, interpolate="linear").encode(
            x, y, alt.Y2(datum=0), color=color, detail="run:N", order="o:Q"),
        alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(color=ZERO, strokeWidth=1, opacity=0.7).encode(y="y:Q"),
    ]
    if changed:                                         # the original: thin, dashed, grey, no fill
        before = pd.DataFrame([{"x": _ts(px), "y": py, "o": j} for j, (px, py) in enumerate(polyline(base))])
        layers.append(alt.Chart(before).mark_line(color=GREY, strokeWidth=1.5, strokeDash=[5, 4], opacity=0.9)
                      .encode(x, y, order="o:Q"))
    layers.append(alt.Chart(line_df).mark_line(strokeWidth=3, interpolate="linear", strokeCap="round",
                                               strokeJoin="round").encode(x, y, color=color, detail="run:N",
                                                                          order="o:Q"))

    # the headline marker
    if not covered:
        run_out = current.first_below_zero.value
        mx = _at(run_out, -12)
        late = run_out > config.DEMO_TODAY + timedelta(days=(config.SEMESTER_END - config.DEMO_TODAY).days * 0.6)
        layers += [
            alt.Chart(pd.DataFrame({"x": [_ts(mx)]})).mark_rule(color=RED, strokeDash=[4, 4], strokeWidth=1.5)
            .encode(x="x:T"),
            alt.Chart(pd.DataFrame({"x": [_ts(mx)], "y": [hi], "t": [f"Runs out · {fmt.day(run_out)}"]}))
            .mark_text(align="right" if late else "left", dx=-6 if late else 6, dy=12, fontSize=13,
                       fontWeight="bold", color=RED).encode(x, y, text="t:N"),
        ]
    else:
        layers.append(alt.Chart(pd.DataFrame({"x": [_ts(_at(config.SEMESTER_END))], "y": [hi],
                                              "t": ["Covered all semester"]}))
                      .mark_text(align="right", dy=12, fontSize=13, fontWeight="bold", color=GREEN)
                      .encode(x, y, text="t:N"))

    # every event: a small dot with details on hover
    ev_rows = [{"x": _ts(_at(e.date)), "y": float(current.balance_on(e.date)), "when": fmt.day(e.date),
                "what": _flow(e), "bal": fmt.balance(current.balance_on(e.date))}
               for e in current.events if e.kind in STEP_KINDS
               and abs((e.date - current.lowest_date.value).days) > 1]       # keep the lowest marker uncluttered
    tip_ev = [alt.Tooltip("when:N", title="Date"), alt.Tooltip("what:N", title="What"),
              alt.Tooltip("bal:N", title="Balance that day")]
    if ev_rows:
        layers.append(alt.Chart(pd.DataFrame(ev_rows)).mark_circle(size=34, opacity=0.9, color=LABEL)
                      .encode(x, y, tooltip=tip_ev))

    # today and the lowest point
    low_d, low_v = current.lowest_date.value, float(current.lowest.value)
    near_end = low_d > config.SEMESTER_END - timedelta(days=7)
    low_text = "Lowest" if low_d == config.SEMESTER_END else "Lowest point"

    # 2-3 story labels, at the step, in the first free spot (the fixed labels above are reserved first)
    lines = [polyline(current)] + ([polyline(base)] if changed else [])
    phone, wide = _Layout(lo, hi, lines, PHONE_W), _Layout(lo, hi, lines, WIDE_W)
    for lay in (phone, wide):
        lay.boxes.append(lay.box(_at(config.DEMO_TODAY), lo, "Today", "left", 3, -7))
        lay.boxes.append(lay.box(_at(low_d), low_v, low_text, "right" if near_end else "center",
                                 4 if near_end else 0, 17))
        lay.boxes.append(lay.box(_at(low_d), low_v, "", "center", 0, 0))
        if covered:
            lay.boxes.append(lay.box(_at(config.SEMESTER_END), hi, "Covered all semester", "right", 0, 12))
        else:
            rx = lay.px(mx)
            lay.segs.append((rx, 0, rx, PLOT_H))
            lay.boxes.append(lay.box(mx, hi, f"Runs out · {fmt.day(run_out)}", "right" if late else "left",
                                     -6 if late else 6, 12))
    prev_of = dict(zip([d for d, _ in balances[1:]], [b for _, b in balances[:-1]]))
    for e in story_events(current):
        sx, sy, align, dx, dy, wide_only = _placement(e, prev_of[e.date], dict(balances)[e.date], phone, wide)
        layers.append(alt.Chart(pd.DataFrame({"x": [_ts(sx)], "y": [sy], "t": [_story_label(e)]}))
                      .mark_text(align=align, dx=dx, dy=dy, fontSize=12, fontWeight=600, color=LABEL,
                                 opacity=alt.expr(f"width < {WIDE_W} ? 0 : 1") if wide_only else 1)
                      .encode(x, y, text="t:N"))

    layers += [
        # bottom-left, over the first date: an early story label can't collide with it at phone width
        alt.Chart(pd.DataFrame({"x": [_ts(_at(config.DEMO_TODAY))], "y": [lo], "t": ["Today"]}))
        .mark_text(align="left", dx=3, dy=-7, fontSize=12, fontWeight=600, color=LABEL).encode(x, y, text="t:N"),
        alt.Chart(pd.DataFrame({"x": [_ts(_at(low_d))], "y": [low_v]}))
        .mark_point(shape="circle", size=60, filled=True, color=RED if low_v < 0 else up, stroke="white",
                    strokeWidth=1.5).encode(x, y),
        alt.Chart(pd.DataFrame({"x": [_ts(_at(low_d))], "y": [low_v], "t": [low_text]}))
        .mark_text(align="right" if near_end else "center", dx=4 if near_end else 0, dy=17, fontSize=12,
                   fontWeight=600, color=RED if low_v < 0 else up).encode(x, y, text="t:N"),
    ]

    # hover anywhere: a guide line and that day's balance and events
    by_day = {}
    for e in current.events:
        by_day.setdefault(e.date, []).append(_flow(e))
    before_bal = dict([(config.DEMO_TODAY, base.start_balance.value)] + base.daily)
    days = pd.DataFrame([{"x": _ts(_at(d)), "y": b, "when": fmt.day(d), "bal": fmt.balance(b),
                          "before": fmt.balance(before_bal[d]) if changed else "",
                          "events": "; ".join(by_day.get(d, [])) or "Everyday spending only"} for d, b in balances])
    tip = [alt.Tooltip("when:N", title="Date"), alt.Tooltip("bal:N", title="Your balance")]
    if changed:
        tip.append(alt.Tooltip("before:N", title="Before your changes"))
    tip.append(alt.Tooltip("events:N", title="That day"))
    hover = alt.selection_point(fields=["x"], nearest=True, on="pointerover", empty=False, clear="pointerout")
    layers += [
        alt.Chart(days).mark_point(opacity=0, size=250).encode(x, y, tooltip=tip).add_params(hover),
        alt.Chart(days).mark_rule(color=GREY, strokeWidth=1).encode(x, tooltip=tip).transform_filter(hover),
    ]
    return alt.layer(*layers).properties(height=300).configure_view(strokeWidth=0)
