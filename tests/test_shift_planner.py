"""The shift planner: several planned extra shifts, each with its pay (after withholding), payday and timing, a
total that ties out to the forecast, days longer, limits, reset, and the chat's multi-shift what-if. Expected
dollar amounts come from the engine's pay rules (Maya: $16.50/hour less withholding, 1st-15th paid on the 18th,
16th-end paid on the 3rd)."""
from datetime import date
from decimal import Decimal

import pytest
from streamlit.testing.v1 import AppTest

import agent
import config
import engine
import llm_client
import normalize
from test_agent import FakeLLM
from test_ui import plain, run, status, texts

D = Decimal
SAT, NEXT_SAT = date(2026, 10, 31), date(2026, 11, 7)


@pytest.fixture(scope="module")
def ds():
    return normalize.load("local")


def shifts(*days, hours=4):
    return tuple(engine.ExtraShift(d, D(hours)) for d in days)


def paycheck_change(ds, extra):
    net = lambda sc: sum(pc.net.value for pc in engine.paychecks(ds, sc, engine.Ledger()))   # noqa: E731
    return net(engine.Scenario(extra_shifts=engine.merge_shifts(extra))) - net(engine.Scenario())


# --- engine ---------------------------------------------------------------------------------------------------

def test_paydays_and_timing(ds):
    plan = engine.shift_plan(shifts(SAT, NEXT_SAT, date(2026, 12, 17)), engine.Scenario(), ds)
    got = [(p.shift.date, p.pay_date, p.added.value, p.timing) for p in plan.shifts]
    assert got == [(SAT, date(2026, 11, 3), D("57.35"), "in_time"),               # before Mon, Nov 9
                   (NEXT_SAT, date(2026, 11, 18), D("57.35"), "late"),             # after she runs out
                   (date(2026, 12, 17), date(2027, 1, 1), D("0.00"), "after_semester")]
    assert plan.before.first_below_zero.value == date(2026, 11, 9)


def test_totals_tie_out_to_the_forecast(ds):
    week = shifts(date(2026, 10, 27), date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30), hours=8)
    for extra in (shifts(SAT, NEXT_SAT), week, shifts(SAT, NEXT_SAT, date(2026, 11, 14), date(2026, 12, 5))):
        plan = engine.shift_plan(extra, engine.Scenario(), ds)
        assert plan.total.value == sum(p.added.value for p in plan.shifts) == paycheck_change(ds, extra)
        assert plan.after.end_balance.value - plan.before.end_balance.value == plan.total.value


def test_days_longer_and_covered(ds):
    longer = engine.shift_plan(shifts(SAT, NEXT_SAT, hours=8), engine.Scenario(), ds)
    assert longer.after.first_below_zero.value == date(2026, 11, 15)
    assert longer.days_longer.value == (date(2026, 11, 15) - date(2026, 11, 9)).days == 6
    same = engine.shift_plan(shifts(NEXT_SAT), engine.Scenario(), ds)          # paid after the run-out
    assert same.days_longer.value == 0
    covered = engine.shift_plan(shifts(SAT), engine.Scenario(refund_released=True), ds)
    assert covered.after.lasts_through_semester and covered.days_longer is None


def test_same_day_merges_capped_and_week_warning(ds):
    assert engine.merge_shifts(shifts(SAT, SAT, hours=8)) == (engine.ExtraShift(SAT, D("12")),)
    week = shifts(date(2026, 10, 27), date(2026, 10, 28), date(2026, 10, 29), hours=8)       # 24 h, Mon Oct 26 week
    assert engine.shift_plan(week, engine.Scenario(), ds).week_hours == {date(2026, 10, 26): D("24.0")}
    assert engine.shift_plan(shifts(SAT, NEXT_SAT), engine.Scenario(), ds).week_hours == {}


# --- the Semester tab -----------------------------------------------------------------------------------------

@pytest.fixture
def at(monkeypatch):
    monkeypatch.setattr(config, "DATA_BACKEND", "local")
    app = AppTest.from_file("../ui/app.py", default_timeout=60)
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def body(at):
    return "\n".join(texts(at))


def test_planner_adds_lists_updates_and_resets(at, ds):
    assert "Try shifts you're thinking of taking." in body(at)
    assert "A shift worked by Sat, Oct 31 is paid Tue, Nov 3, in time." in body(at)            # the hint stays
    at.button(key="shift_add_this").click()
    run(at)
    at.button(key="shift_add_next").click()
    run(at)
    assert [(x["date"], x["hours"]) for x in at.session_state["wf_shifts"]] == [(SAT, 4.0), (NEXT_SAT, 4.0)]
    plan = engine.shift_plan(shifts(SAT, NEXT_SAT), engine.Scenario(), ds)
    b = body(at)
    assert f"These 2 shifts add $115, but your money still runs out on Mon, Nov 9." in b    # $114.70
    assert plan.total.value == D("114.70")
    assert "Sat, Oct 31 · 4 hours · adds $57.35. Paid Tue, Nov 3, in time." in b
    assert "Sat, Nov 7 · 4 hours · adds $57.35. Paid Wed, Nov 18, after you run out." in b
    assert 'class="rw-fig' in "".join(texts(at)) and any("rw-delta" in t for t in texts(at))   # the figures moved
    # reset clears only the shifts
    at.toggle(key="wf_refund").set_value(True)
    run(at)
    at.button(key="shift_reset").click()
    run(at)
    assert at.session_state["wf_shifts"] == [] and at.session_state["wf_refund"]
    assert ">You're covered all semester.<" in status(at)


def test_planner_lasts_longer_and_start_over(at):
    for _ in range(2):                                     # 8 hours on each Saturday
        at.button(key="shift_add_this").click()
        run(at)
        at.button(key="shift_add_next").click()
        run(at)
    assert "These 2 shifts add $229 and your money lasts until Sun, Nov 15 (6 days longer)." in body(at)
    assert ">Your money runs out in 2.8 weeks, on Sun, Nov 15.<" in status(at)
    at.button(key="start_over").click()
    run(at)
    assert at.session_state["wf_shifts"] == []
    assert ">Your money runs out in 2 weeks, on Mon, Nov 9.<" in status(at)


@pytest.mark.parametrize("day,hours,message", [
    (date(2026, 10, 26), 4, "Pick a day after today."),
    (date(2026, 12, 19), 4, "Pick a day by Fri, Dec 18, when the semester ends."),
    (SAT, 13, "That's more than 12 hours on Sat, Oct 31. Pick fewer hours."),
])
def test_limits_have_friendly_messages(at, day, hours, message):
    at.session_state["wf_shift_date"] = day
    at.session_state["wf_shift_hours"] = float(hours) if hours <= 12 else 12.0
    if hours > 12:                                         # 8 planned + 5 more on the same day
        at.session_state["wf_shifts"] = [{"date": SAT, "hours": 8.0}]
        at.session_state["wf_shift_hours"] = 5.0
    run(at)
    at.button(key="shift_add").click()
    run(at)
    assert any(message in plain(c.value) for c in at.caption), [c.value for c in at.caption]
    assert len(at.session_state["wf_shifts"]) == (1 if hours > 12 else 0)


def test_soft_warning_over_20_hours_a_week(at):
    at.session_state["wf_shifts"] = [{"date": date(2026, 10, d), "hours": 8.0} for d in (27, 28, 29)]
    run(at)
    assert any("That's 24 extra hours in the week of Mon, Oct 26." in plain(c.value) for c in at.caption)


# --- the chat -------------------------------------------------------------------------------------------------

PLAN = ('{"calls": [{"tool": "what_if", "args": {"extra_shifts": [{"date": "2026-10-31", "hours": 4}, '
        '{"date": "2026-11-07", "hours": 4}]}}]}')


def test_chat_answer_has_total_paydays_and_run_out(ds, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ANSWER_CACHE_DIR", tmp_path)
    llm = FakeLLM(plans=[PLAN], explain_error=llm_client.LLMError("down"))
    a = agent.ask("What if I work 4 hours this Saturday and next Saturday?", engine.Scenario(), ds=ds, mode="live",
                  llm=llm)
    assert a.check["ok"], a.check
    assert {f["key"] for f in a.facts} == {"shifts_total", "payday_2026-11-03", "payday_2026-11-18", "runs_out"}
    assert a.text.startswith("ANSWER: These 2 shifts add $115 [")
    assert "Pay for Sat, Oct 31 arrives Tue, Nov 3, before you run out" in a.text
    assert "Pay for Sat, Nov 7 arrives Wed, Nov 18, after you run out" in a.text
    assert "Your money runs out on Mon, Nov 9" in a.text


def test_chat_button_adds_the_shifts_to_the_planner(at, tmp_path, monkeypatch):
    fake = FakeLLM(plans=[PLAN], explain_error=llm_client.LLMError("down"))
    monkeypatch.setattr(llm_client, "chat_json", fake.chat_json)
    monkeypatch.setattr(llm_client, "stream_chat", fake.stream_chat)
    monkeypatch.setattr(config, "ANSWER_MODE", "live")
    monkeypatch.setattr(config, "ANSWER_CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "NVIDIA_API_KEY", "test-key")
    at.chat_input(key="ask_input").set_value("What if I work 4 hours this Saturday and next Saturday?")
    run(at)
    button = next(b for b in at.button if str(b.key).startswith("ans_shifts_"))
    assert button.label == "Add these to my shift planner"
    button.click()
    run(at)
    assert [(x["date"], x["hours"]) for x in at.session_state["wf_shifts"]] == [(SAT, 4.0), (NEXT_SAT, 4.0)]
    assert any("These shifts are in your shift planner." in plain(c.value) for c in at.caption)
