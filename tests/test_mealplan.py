"""The meal plan settings and log (mealplan.py) and the engine's meal math for them (engine.meal_plan_status):
day, week and semester allowances, resets and roll-over, logging and undo, validation, pace and run-out, the
estimated cost into the forecast, and Maya's default state staying exactly the same."""
import dataclasses
from datetime import date
from decimal import Decimal

import pytest

import config
import engine as e
import mealplan
import normalize
import runway_memory

OCT26, START, END = date(2026, 10, 26), date(2026, 8, 24), date(2026, 12, 18)


@pytest.fixture(scope="module")
def ds():
    return normalize.load("local")


@pytest.fixture(scope="module")
def bare(ds):
    """A student with no school meal plan and no history (My data mode): everything comes from her log."""
    return dataclasses.replace(ds, meal_plan=None, meals=[])


def plan(meals=14, meals_per="week", points="150", points_per="semester", **kw):
    return e.MealSettings(meals, meals_per, Decimal(points), points_per, kw.pop("start", START), kw.pop("end", END),
                          **kw)


def log(*items):
    return tuple(e.MealEntry(d, m, Decimal(p), "", f"LOG-{i}") for i, (d, m, p) in enumerate(items, start=1))


def status(ds, s, entries, **kw):
    return e.meal_plan_status(e.Scenario(meal_settings=s, meal_log=entries, **kw), ds)


# --- Maya's default state ----------------------------------------------------------------------------------------
def test_default_is_her_school_plan(ds):
    s = e.default_meal_settings(ds)
    assert (s.meals, s.meals_per, s.points, s.points_per, s.start, s.end) == (75, "semester", Decimal("400.00"),
                                                                             "semester", START, END)
    assert mealplan.settings(mealplan.empty(), ds) == s and not mealplan.is_custom(mealplan.empty(), ds)
    assert mealplan.scenario_part(mealplan.empty(), ds) == {}                       # nothing reaches the engine


def test_default_unchanged(ds):
    base, ledger = e.meal_plan_status(e.Scenario(), ds), e.Ledger()
    same = e.meal_plan_status(e.Scenario(meal_settings=e.default_meal_settings(ds)), ds)
    assert {k: (c.value, c.how, c.inputs) for k, c in base.c.items()} == \
           {k: (c.value, c.how, c.inputs) for k, c in same.c.items()}
    detail = e.meal_plan_status(e.Scenario(), ds, ledger, detail=True)
    assert [c.label for c in ledger.items[:len(base.c) + 3]] == [c.label for c in [*base.c.values(), *base.tip.values()]]
    assert detail.meals.left.value == 56 and detail.points.left.value == Decimal("117.00")
    assert detail.points.runs_out.value == date(2026, 11, 22) and detail.meals.runs_out.value is None
    assert detail.meals.unused_end.value == Decimal("40.27") and not detail.events
    assert e.project(e.Scenario(meal_settings=e.default_meal_settings(ds)), ds).daily == e.project(e.Scenario(), ds).daily


def test_maya_log_counts_with_her_history(ds):
    m = status(ds, None, log((OCT26, 2, "9.50")))
    assert m.pooled and m.c["swipes_used"].value == 21 and m.c["swipes_left"].value == 54
    assert m.c["dd_used"].value == Decimal("292.50") and "and 1 you logged" in m.c["dd_used"].how
    assert "LOG-1" in m.c["dd_used"].inputs and "LOG-1" in m.c["swipes_used"].inputs


# --- week plans: left this week, reset, pace, run short ---------------------------------------------------------
def test_week_plan_left_and_reset(bare):
    m = status(bare, plan(), log((OCT26, 2, "0")))
    a = m.meals
    assert (a.used.value, a.left.value, a.resets.value) == (2, 12, date(2026, 11, 2))       # Mon Oct 26 + 1 week
    assert a.pace.value == Decimal("14.0")                                                 # 2 a day since Oct 26
    assert a.runs_out.value is None and a.short.value == 0
    assert (a.short_periods.value, a.periods_left.value) == (0, 8)
    assert a.unused_period.value == 0 and a.unused_end.value == 4         # Dec 14-18: 5 days x 2 of 14
    assert m.c["cost"].value == 0 and not m.events


def test_week_reset_day(bare):
    a = status(bare, plan(week_starts=2), log((OCT26, 2, "0"))).meals              # weeks start on Wednesday
    assert a.resets.value == date(2026, 10, 28)


def test_week_plan_runs_short_and_costs_checking(bare):
    m = status(bare, plan(), log((OCT26, 3, "0"), (OCT26, 0, "10")))
    a, p = m.meals, m.points
    assert a.left.value == 11 and a.runs_out.value == date(2026, 10, 30)             # 11 - 3 a day: short on Fri
    assert (a.short_periods.value, a.periods_left.value) == (8, 8)                  # 21 a week vs 14: every week
    assert a.short.value == 50                                                      # 7 + 6 weeks x 7 + 1
    assert p.left.value == Decimal("140.00") and p.runs_out.value == date(2026, 11, 10)
    assert p.short.value == Decimal("390.00")                                       # $530 needed, $140 left
    assert m.c["avg_meal"].value == Decimal("10.00")
    assert m.c["cost"].value == Decimal("890.00")                                   # $390 + 50 meals x $10
    assert m.runs_out == date(2026, 10, 30)
    assert sum(x for _, x, _ in m.events) == Decimal("890.00") and m.events[0][0] == date(2026, 10, 30)
    pr, base = e.project(e.Scenario(meal_settings=plan(), meal_log=log((OCT26, 3, "0"), (OCT26, 0, "10"))), bare), \
        e.project(e.Scenario(), bare)
    assert sum(-x.amount for x in pr.events if x.kind == "meal_plan") == Decimal("890.00")
    assert pr.end_balance.value == base.end_balance.value - Decimal("890.00")


def test_rolls_over(bare):
    a = status(bare, plan(rolls_over=True), log((OCT26, 2, "0"))).meals
    assert a.left.value == 138                                       # 10 weeks from Mon Aug 24 x 14, minus 2
    assert a.unused_period is None and a.runs_out.value is None


def test_day_plan_use_them_or_lose_them(bare):
    a = status(bare, plan(3, "day"), log((OCT26, 2, "0"))).meals
    assert (a.left.value, a.resets.value) == (1, date(2026, 10, 27))
    assert a.unused_period.value == 1 and a.unused_end.value == 1            # 3 a day, 2 used: 1 lost each day


def test_semester_pool_from_log_only(bare):
    m = status(bare, plan(50, "semester", "100"), log((OCT26, 1, "0")))
    assert m.pooled and m.c["swipes_left"].value == 49 and m.c["swipes_end"].value == Decimal("-4.00")
    assert m.cost_unknown and m.c["cost"].value == 0                     # no points purchase to price a meal from


def test_attention_item_for_a_week_plan(bare):
    sc = e.Scenario(meal_settings=plan(), meal_log=log((OCT26, 3, "0"), (OCT26, 0, "10")))
    item = next(i for i in e.attention_items(sc, bare) if i.kind == "meal_plan")
    assert item.due.value == date(2026, 10, 30) and item.stake.value == Decimal("890.00")
    assert item.facts["kind"] == "meals" and item.facts["short_periods"].value == 8
    ok = e.Scenario(meal_settings=plan(), meal_log=log((OCT26, 2, "0")))
    assert "meal_plan" not in [i.kind for i in e.attention_items(ok, bare)]


# --- validation ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("day,meals,points,msg", [
    (OCT26, -1, 0, "can't be negative"), (OCT26, 0, -5, "can't be negative"), (OCT26, 11, 0, "from 0 to 10"),
    (OCT26, 1.5, 0, "whole number"), (OCT26, 0, 201, "up to $200"), (OCT26, 0, 0, "at least one"),
    (date(2026, 8, 1), 1, 0, "inside your meal plan"), (date(2026, 10, 27), 1, 0, "today or an earlier day")])
def test_entry_validation(day, meals, points, msg):
    assert msg in e.meal_entry_problem(day, meals, points, plan(), OCT26)


def test_entry_validation_ok():
    assert e.meal_entry_problem(OCT26, 10, 200, plan(), OCT26) is None


def test_settings_validation():
    assert "negative" in e.meal_settings_problem(-1, "week", 0, "semester", START, END)
    assert "per day, per week" in e.meal_settings_problem(1, "month", 0, "semester", START, END)
    assert "end after it starts" in e.meal_settings_problem(1, "week", 0, "semester", END, START)
    assert "Add some meals" in e.meal_settings_problem(0, "week", 0, "semester", START, END)
    with pytest.raises(ValueError):
        plan(meals=-1)


# --- storage, logging and undo ------------------------------------------------------------------------------------
def test_storage_log_and_undo(ds):
    data = mealplan.load("maya")
    assert data == mealplan.empty()
    assert mealplan.add(data, OCT26, meals=1, ds=ds, today=OCT26) is None
    assert mealplan.add(data, OCT26, meals=1, ds=ds, today=OCT26) is None
    assert mealplan.add(data, OCT26, points="8.50", note="lunch", ds=ds, today=OCT26) is None
    assert "from 0 to 10" in mealplan.add(data, OCT26, meals=12, ds=ds, today=OCT26)          # nothing logged
    assert mealplan.meals_on(data, OCT26) == 2 and len(data["log"]) == 3
    assert mealplan.undo_meal(data, OCT26) and mealplan.meals_on(data, OCT26) == 1
    mealplan.remove(data, "LOG-3")
    mealplan.save("maya", data)
    back = mealplan.load("maya")
    assert [x.id for x in mealplan.entries(back)] == ["LOG-1"] and back["next"] == 4
    assert mealplan.load("mine") == mealplan.empty()                      # My data keeps its own, separately
    assert mealplan.path("maya") != mealplan.path("mine")
    part = mealplan.scenario_part(back, ds)
    assert part["meal_settings"] is None and len(part["meal_log"]) == 1


def test_files_are_gitignored():
    ignored = (config.PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".cache/" in ignored and "user_data/" in ignored
    mealplan.FOLDER, saved = None, mealplan.FOLDER
    try:
        assert mealplan.path("maya") == config.PROJECT_ROOT / ".cache" / "mealplan.json"
        assert mealplan.path("mine") == config.USER_DATA_DIR / "mealplan.json"
    finally:
        mealplan.FOLDER = saved


def test_my_data_settings(bare):
    data = mealplan.empty()
    assert mealplan.settings(data, bare) is None and "Set up your meal plan" in mealplan.add(data, OCT26, 1, ds=bare)
    mealplan.set_settings(data, plan())
    assert mealplan.add(data, OCT26, 2, ds=bare, today=OCT26) is None
    part = mealplan.scenario_part(data, bare, OCT26)
    assert part["meal_settings"] == plan() and status(bare, **{"s": part["meal_settings"],
                                                                "entries": part["meal_log"]}).meals.left.value == 12


def test_memory_text_and_hmem(tmp_path):
    text = mealplan.memory_text(plan(), lambda x: f"${x:,.0f}")
    assert text == "Your meal plan: 14 meals a week, $150 points a semester."
    mem = runway_memory.RunwayMemory(persist_dir=tmp_path / "m")
    mem.remember_meal_plan(text)
    mem.remember_meal_plan("Your meal plan: 10 meals a week, $150 points a semester.")
    live = [m for m in mem.items() if "meal_plan" in m.tags]
    assert len(live) == 1 and live[0].content.startswith("Your meal plan: 10 meals")
    assert live[0].provenance["label"] == "You set this in the meal plan card"
