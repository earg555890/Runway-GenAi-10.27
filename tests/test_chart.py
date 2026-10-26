"""The balance chart: two engine lines (solid "What's happening", dotted "If you follow the steps"), one point per day
with monotone interpolation (soft corners, no overshoot), red only below $0, the run-out marker, the dotted line's
lowest point, and a hover layer with both balances and the day's events. Plus the card's legend in the app."""
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import engine  # noqa: E402
import normalize  # noqa: E402
from ui import chart  # noqa: E402


@pytest.fixture(scope="module")
def ds():
    return normalize.load("local")


def _layers(spec):
    return spec["layer"]


def _mark(layer):
    m = layer["mark"]
    return m if isinstance(m, dict) else {"type": m}


def _texts(spec):
    return [r["t"] for d in spec["datasets"].values() for r in d if "t" in r]


def _build(ds, scenario):
    cur = engine.project(scenario, ds)
    steps_sc = chart.steps_scenario(scenario, ds)
    steps = engine.project(steps_sc, ds) if steps_sc else None
    return cur, steps, chart.build(cur, steps).to_dict(validate=True)


def test_steps_are_the_fixes_that_still_help_never_if_approved_aid(ds):
    sc = chart.steps_scenario(engine.Scenario(), ds)
    assert sc.refund_released and sc.cancel_subscriptions == ("Spotify",)        # Apple Music saves $0.00: not a step
    assert not sc.approved
    done = engine.Scenario(refund_released=True, cancel_subscriptions=("Spotify",))
    assert chart.steps_scenario(done, ds) is None                                   # nothing left to do


def test_base_has_a_solid_line_a_dotted_steps_line_and_both_markers(ds):
    cur, steps, spec = _build(ds, engine.Scenario())
    lines = [_mark(l) for l in _layers(spec) if _mark(l)["type"] == "line"]
    dotted = [m for m in lines if m.get("strokeDash")]
    solid = [m for m in lines if not m.get("strokeDash")]
    assert len(dotted) == 1 and dotted[0]["color"] == chart.STEPS and dotted[0]["interpolate"] == "monotone"
    assert len(solid) == 1 and solid[0]["interpolate"] == "monotone" and solid[0]["strokeWidth"] > dotted[0]["strokeWidth"]
    assert "RUNS OUT · MON, NOV 9" in _texts(spec)
    assert "With the steps: lowest $5.81" in _texts(spec)                           # the answer key's $5.81
    assert all(_mark(l)["type"] != "line" or _mark(l).get("color") != "#9ca3af" for l in _layers(spec))  # no old grey line


def test_one_point_per_day_and_red_only_below_zero(ds):
    cur, steps, spec = _build(ds, engine.Scenario())
    pts = chart.day_points(cur)
    assert len(pts) == len(cur.daily) + 1 and pts[0] == (config.DEMO_TODAY, float(cur.start_balance.value))
    runs = chart.split_at_zero([(chart._at(d), b) for d, b in pts])
    assert all((sign == "neg") == all(y <= 0 for _, y in seg) for sign, seg in runs)
    assert all(y >= 0 for sign, seg in runs if sign == "pos" for _, y in seg)
    color = next(l["encoding"]["color"] for l in _layers(spec) if _mark(l)["type"] == "line" and "color" in l.get("encoding", {}))
    assert color["scale"]["range"] == [chart.LINE, chart.RED]


def test_line_values_are_the_engine_balances_on_event_days(ds):
    cur, steps, spec = _build(ds, engine.Scenario())
    line_rows = next(rows for rows in spec["datasets"].values() if rows and "sign" in rows[0])
    by_day = {r["x"][:10]: r["y"] for r in line_rows}
    for e in cur.events:
        if e.kind in ("rent", "card_autopay", "paycheck"):
            assert by_day[e.date.isoformat()] == pytest.approx(float(cur.balance_on(e.date)))


def test_when_every_step_is_taken_only_the_solid_line_shows(ds):
    cur, steps, spec = _build(ds, engine.Scenario(refund_released=True, cancel_subscriptions=("Spotify",)))
    assert steps is None
    assert not [l for l in _layers(spec) if _mark(l)["type"] == "line" and _mark(l).get("strokeDash")]
    assert "COVERED ALL SEMESTER" in _texts(spec) and not any(t.startswith("With the steps") for t in _texts(spec))


def test_hover_shows_both_balances_and_the_days_events(ds):
    cur, steps, spec = _build(ds, engine.Scenario())
    hover = [l for l in _layers(spec) if _mark(l)["type"] == "rule" and _mark(l).get("strokeWidth") == 14]
    assert len(hover) == 1 and spec["params"][0]["select"]["on"] == "pointerover"   # a full-height strip per day
    titles = [t["title"] for t in hover[0]["encoding"]["tooltip"]]
    assert titles == ["Day", "What's happening", "If you follow the steps", "That day"]
    rows = next(rows for rows in spec["datasets"].values() if rows and "events" in rows[0])
    nov9 = next(r for r in rows if r["x"].startswith("2026-11-09"))
    assert "Card payment $360" in nov9["events"] and nov9["when"] == "Mon, Nov 9"
    assert len([l for l in _layers(spec) if l.get("transform")]) == 3                # guide + a dot on each line


def test_a_purchase_still_runs_out_and_keeps_the_steps_line(ds):
    sc = engine.Scenario(purchases=(engine.Purchase(Decimal("400"), date(2026, 11, 10), "checking", "Flight home"),))
    cur, steps, spec = _build(ds, sc)
    assert steps is not None and cur.first_below_zero.value
    assert any(t.startswith("RUNS OUT") for t in _texts(spec))


def test_the_card_legend_names_both_lines_then_says_following_the_plan(monkeypatch):
    monkeypatch.setattr(config, "DATA_BACKEND", "local")
    at = AppTest.from_file("../ui/app.py", default_timeout=60)
    at.run()
    legend = next(m.value for m in at.markdown if m.value.startswith('<div class="rw-legend"'))
    assert "What&#39;s happening" in legend and "If you follow the steps" in legend
    assert any("Your money through Dec 18" in m.value for m in at.markdown)
    at.toggle(key="wf_refund").set_value(True)
    at.toggle(key="wf_cancel_Spotify").set_value(True)
    at.run()
    legend = next(m.value for m in at.markdown if m.value.startswith('<div class="rw-legend"'))
    assert "If you follow the steps" not in legend and "You&#39;re following the plan" in legend
