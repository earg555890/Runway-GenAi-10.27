"""The meal plan card (ui/meal.py), the chat's meal_plan tool on her own settings and log (agent.py), and the
"Log 2 meals" button: one-tap logging and undo, settings, reset, the check-in item, required facts, and that
nothing is ever logged without her tap. Maya's default state stays exactly the same."""
import dataclasses
from datetime import date
from decimal import Decimal

import pytest
from streamlit.testing.v1 import AppTest

import actions
import agent
import config
import engine as e
import llm_client
import mealplan
import normalize
from test_agent import FakeLLM
from test_ui import plain, run, status, texts

OCT25, OCT26, START, END = date(2026, 10, 25), date(2026, 10, 26), date(2026, 8, 24), date(2026, 12, 18)
WEEK = e.MealSettings(14, "week", Decimal("150"), "semester", START, END, 0, False)
c = lambda x: "[C]"                                                       # noqa: E731


@pytest.fixture(scope="module")
def ds():
    return normalize.load("local")


@pytest.fixture(scope="module")
def bare(ds):
    return dataclasses.replace(ds, meal_plan=None, meals=[])


def log(*items):
    return tuple(e.MealEntry(d, m, Decimal(p), "", f"LOG-{i}") for i, (d, m, p) in enumerate(items, start=1))


def tool(question, scenario, ds):
    args = agent.validate_call("meal_plan", agent.meal_words(question.lower()), [])[0]
    r = agent.execute_call("meal_plan", args, scenario, ds)
    r.tool, r.args = "meal_plan", args
    return args, r


# --- the chat tool -------------------------------------------------------------------------------------------------
def test_question_words():
    assert agent.meal_words("i just used 2 meals") == {"log_meals": 2}
    assert agent.meal_words("i had a meal") == {"log_meals": 1}
    assert agent.meal_words("i spent $8.50 in points") == {"log_points": "8.50"}
    assert agent.meal_words("how many meals do i have left this week?") == {"about": "meals"}
    assert agent.meal_words("will my points last?") == {"about": "points"}
    assert agent.meal_words("will my dining dollars last?") == {}               # the recorded demo question: as before


def test_validation():
    assert agent.validate_call("meal_plan", {}, [])[0] == {}
    assert agent.validate_call("meal_plan", {"log_meals": 2, "about": "Meals"}, [])[0] == {"about": "meals",
                                                                                          "log_meals": 2}
    for bad in ({"log_meals": 2.5}, {"log_meals": 12}, {"log_meals": -1}, {"about": "snacks"}, {"log_points": "x"}):
        with pytest.raises(ValueError):
            agent.validate_call("meal_plan", bad, [])


def test_maya_default_answer_unchanged(ds):
    _, r = tool("Will my dining dollars last?", e.Scenario(), ds)
    head, why, do, note, facts = agent.meal_parts(r.facts, c)
    assert head == "Your dining dollars run out around Sun, Nov 22 [C]."
    assert [f.key for f in facts] == ["runs_out", "swipes_end", "cost"] and note == ""
    assert len(r.key) == 15                                         # C1-C15, as in the recorded demo answer


def test_week_plan_meals_left(bare):
    sc = e.Scenario(meal_settings=WEEK, meal_log=log((OCT26, 2, "0"), (OCT26, 0, "8.50"), (OCT25, 3, "0")))
    _, r = tool("How many meals do I have left this week?", sc, bare)
    head, why, do, note, facts = agent.meal_parts(r.facts, c)
    assert head == "You have 12 meals left this week [C]."                      # 14 - 2 (Oct 25 was last week)
    assert "Your meals reset Mon, Nov 2 [C]." in why
    assert why[0] == "You have $142 in points left this semester [C]."
    assert [f.key for f in facts] == ["left", "points_left", "when", "cost"]
    assert "At your pace, you run short 7 of 8 weeks [C]." in why and do == []
    slow = e.Scenario(meal_settings=WEEK, meal_log=log((date(2026, 10, 20), 1, "8.50")))      # last week: 1 meal
    head, why, do, *_ = agent.meal_parts(tool("How many meals do I have left this week?", slow, bare)[1].facts, c)
    assert head == "You have 14 meals left this week [C]."
    assert do == ["Use about 13 meals before Mon, Nov 2: unused ones don't roll over [C]."]


def test_points_last(bare):
    sc = e.Scenario(meal_settings=WEEK, meal_log=log((OCT26, 1, "8.50")))
    _, r = tool("Will my points last?", sc, bare)
    head, why, *_ = agent.meal_parts(r.facts, c)
    assert head == "You have $142 in points left this semester [C]."
    assert any(x.startswith("At this pace, your points") for x in why)


def test_just_used_2_meals_is_a_preview(bare):
    entries = log((OCT26, 1, "0"))
    sc = e.Scenario(meal_settings=WEEK, meal_log=entries)
    args, r = tool("I just used 2 meals", sc, bare)
    head, why, do, note, facts = agent.meal_parts(r.facts, c)
    assert args == {"log_meals": 2}
    assert head == "After you log 2 meals: you have 11 meals left this week [C]."
    assert "PocketMoney logs nothing until you tap" in note and "after" in [f.key for f in facts]
    assert sc.meal_log == entries                                              # nothing logged
    too_many = tool("I just used 2 meals", e.Scenario(meal_settings=dataclasses.replace(WEEK, start=OCT26 + e.timedelta(days=1))), bare)[1]
    assert too_many.facts["problem"] and not too_many.facts["after"]           # can't log: no preview, no button


def test_chat_answer_passes_the_checks(bare, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ANSWER_CACHE_DIR", tmp_path)
    sc = e.Scenario(meal_settings=WEEK, meal_log=log((OCT26, 1, "0")))
    for q, plan in (("How many meals do I have left this week?", '{"calls": [{"tool": "meal_plan", "args": {"about": "meals"}}]}'),
                    ("I just used 2 meals", '{"calls": [{"tool": "meal_plan", "args": {"log_meals": 2}}]}')):
        llm = FakeLLM(plans=[plan], explain_error=llm_client.LLMError("down"))
        a = agent.ask(q, sc, ds=bare, mode="live", llm=llm)
        assert a.check["ok"], (q, a.check)
        assert not any(f["appended"] for f in a.facts)
    assert "After you log 2 meals" in a.text


def test_week_plan_check_in_item_only_when_it_costs(bare):
    short = e.Scenario(meal_settings=WEEK, meal_log=log((OCT26, 3, "0"), (OCT26, 0, "10")))
    item = next(i for i in e.attention_items(short, bare) if i.kind == "meal_plan")
    title, sentence = actions.text(item)
    assert title.startswith("Your meals run short around ") and "(estimated)" in sentence
    assert actions.step(item).startswith("Plan for about ") and actions.reminder(item).title == "Meals run short"
    spare = e.Scenario(meal_settings=dataclasses.replace(WEEK, points=Decimal("2000")),
                       meal_log=log((OCT26, 3, "0"), (OCT26, 0, "10")))
    assert e.meal_plan_status(spare, bare).meals.runs_out.value                 # meals run short, points cover it...
    assert "meal_plan" not in [i.kind for i in e.attention_items(spare, bare)]  # ...so it doesn't matter: no item


# --- the card --------------------------------------------------------------------------------------------------
@pytest.fixture
def at(monkeypatch):
    monkeypatch.setattr(config, "DATA_BACKEND", "local")
    app = AppTest.from_file("../ui/app.py", default_timeout=60)
    app.run()
    assert not app.exception, [x.value for x in app.exception]
    return app


def counters(at):
    return next(t for t in texts(at) if 'class="rw-meal-row"' in t and "<style" not in t)


def test_card_default_counters(at):
    t = counters(at)
    assert '>Meals left<' in t and '>56<' in t and '>$117<' in t and t.count(">this semester<") == 2
    assert ">At this pace, they run out around Sun, Nov 22.<" in t
    assert ">Use them or lose them: about 40 meals left on Fri, Dec 18.<" in t
    assert any("Tip: use 2 swipes a week instead of dining dollars, and both last." in plain(x.value) for x in at.caption)
    at.slider(key="wf_meal_moves").set_value(2)                                  # the what-if still works
    run(at)
    assert ">At this pace, they last the semester.<" in counters(at)
    assert ">Your money runs out in 2 weeks, on Mon, Nov 9.<" in status(at)


def test_card_plus_minus_and_remove(at):
    before = status(at)
    at.button(key="meal_plus").click()
    run(at)
    at.button(key="meal_plus").click()
    run(at)
    assert '>55<' not in counters(at) and '>54<' in counters(at)
    assert any("Mon, Oct 26 · 2 meals" == plain(m.value) for m in at.markdown)
    assert [x["meals"] for x in mealplan.load("maya")["log"]] == [2]           # saved on this computer right away
    at.button(key="meal_minus").click()
    run(at)
    assert '>55<' in counters(at)
    rm = next(b for b in at.button if str(b.key).startswith("meal_rm_"))
    rm.click()
    run(at)
    assert '>56<' in counters(at) and mealplan.load("maya")["log"] == []
    assert status(at) == before                                                 # swipes: $0 to checking


def test_card_points_and_settings_and_reset(at):
    at.number_input(key="meal_points_in").set_value(250.0)                      # over $200: friendly message
    at.button(key="FormSubmitter:meal_points_form-Log").click()
    run(at)
    at.number_input(key="meal_set_meals").set_value(14)
    at.selectbox(key="meal_set_meals_per").set_value("week")
    at.number_input(key="meal_set_points").set_value(150.0)
    at.button(key="FormSubmitter:meal_settings_form-Save").click()
    run(at)
    t = counters(at)
    assert ">this week<" in t and ">12<" not in t and ">14<" in t and ">Resets Mon, Nov 2.<" in t
    assert mealplan.load("maya")["settings"]["meals_per"] == "week"
    at.button(key="meal_reset").click()
    run(at)
    assert '>56<' in counters(at) and mealplan.load("maya") == mealplan.empty()


def test_chat_log_button(at, tmp_path, monkeypatch):
    fake = FakeLLM(plans=['{"calls": [{"tool": "meal_plan", "args": {"log_meals": 2}}]}'],
                   explain_error=llm_client.LLMError("down"))
    monkeypatch.setattr(llm_client, "chat_json", fake.chat_json)
    monkeypatch.setattr(llm_client, "stream_chat", fake.stream_chat)
    monkeypatch.setattr(config, "ANSWER_MODE", "live")
    monkeypatch.setattr(config, "ANSWER_CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "NVIDIA_API_KEY", "test-key")
    at.button(key="chat_fab_btn").click()
    run(at)
    at.chat_input(key="ask_input").set_value("I just used 2 meals")
    run(at)
    assert mealplan.load("maya")["log"] == []                                   # the answer alone logs nothing
    button = next(b for b in at.button if str(b.key).startswith("ans_meal_"))
    assert button.label == "Log 2 meals"
    button.click()
    run(at)
    assert [(x["date"], x["meals"]) for x in mealplan.load("maya")["log"]] == [("2026-10-26", 2)]
    assert any("Logged in your meal plan." in plain(x.value) for x in at.caption)
    assert '>54<' in counters(at)


# --- a new plan of her own counts from its start (today by default) ------------------------------------------------
def test_new_plan_counts_from_today(ds):
    mine = dataclasses.replace(WEEK, start=OCT26)                       # 14 a week + $150 a semester, from today
    m = e.meal_plan_status(e.Scenario(meal_settings=mine), ds)
    assert m.meals.left.value == 14                                       # not "$133 more than your plan":
    assert m.points.left.value == Decimal("143.01")                       # $150 - today's $6.99 lunch (MEAL-051)
    assert m.points.used.inputs == ["MEAL-051"]
    assert e.meal_plan_status(e.Scenario(meal_settings=WEEK), ds).points.left.value == Decimal("-133.00")  # from Aug 24


def test_saving_a_plan_starts_today(at):
    assert at.date_input(key="meal_set_start").value == OCT26
    at.number_input(key="meal_set_meals").set_value(14)
    at.selectbox(key="meal_set_meals_per").set_value("week")
    at.number_input(key="meal_set_points").set_value(150.0)
    at.button(key="FormSubmitter:meal_settings_form-Save").click()
    run(at)
    t = counters(at)
    assert ">14<" in t and ">$143<" in t and "more than your plan" not in t
    assert mealplan.load("maya")["settings"]["start"] == "2026-10-26"
    assert ">Your money runs out in 2 weeks, on Mon, Nov 9.<" in status(at)
