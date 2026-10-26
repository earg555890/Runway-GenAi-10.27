"""Sources 7 (aid opportunities) and 8 (meal plan): the engine reproduces answer-key stories 6 and 7 to the cent,
grants are only ever "if approved" what-ifs, and nothing here changes the base forecast or stories 1-5."""
import json
from datetime import date
from decimal import Decimal

import pytest

import config
import engine as e
import normalize


@pytest.fixture(scope="module")
def ds():
    return normalize.load("local")


@pytest.fixture(scope="module")
def key():
    stories = json.loads((config.DATA_DIR / "answer_key.json").read_text(encoding="utf-8"))["stories"]
    return {s["id"]: s for s in stories}


# --- story 6: the meal plan ----------------------------------------------------------------------------------

def test_story6_meal_plan_to_the_cent(ds, key):
    kn = key[6]["key_numbers"]
    m = e.meal_plan_status(e.Scenario(), ds)
    c = m.c
    assert str(c["dd_total"].value) == kn["dining_dollars"] and str(c["dd_used"].value) == kn["dining_dollars_used"]
    assert str(c["dd_left"].value) == kn["dining_dollars_left"]
    assert c["dd_runs_out"].value.isoformat() == kn["dining_dollars_run_out"] == "2026-11-22"      # a Sunday
    assert c["swipes_total"].value == kn["swipes"] and c["swipes_used"].value == kn["swipes_used"]
    assert c["swipes_left"].value == kn["swipes_left"] and str(c["swipes_end"].value) == kn["swipes_unused_dec_18"]
    assert str(c["avg_meal"].value) == kn["average_meal"] and str(c["cost"].value) == kn["cost_to_checking"] == "0.00"
    assert str(m.tip["dd_end"].value) == kn["tip_dining_dollars_left_dec_18"]
    assert str(m.tip["sw_end"].value) == kn["tip_swipes_left_dec_18"]
    assert m.tip_works and m.swipes_last
    assert c["dd_week"].value == Decimal("30.95") and c["swipes_week"].value == Decimal("2.1")
    assert set(c["dd_used"].inputs) | set(c["swipes_used"].inputs) == set(key[6]["evidence"][1]["row_ids"])


def test_meal_plan_what_ifs(ds):
    two = e.meal_plan_status(e.Scenario(meal_moves=2), ds)
    assert two.runs_out is None and two.c["cost"].value == 0                     # the tip itself: both last
    four = e.meal_plan_status(e.Scenario(meal_moves=-4), ds)                     # 4 swipe meals a week paid in dining $
    assert four.c["cost"].value == 0 and four.runs_out < date(2026, 11, 22)      # the freed swipes still cover it
    six = e.meal_plan_status(e.Scenario(meal_moves=-6), ds)                      # no swipes used at all any more
    assert six.c["cost"].value == Decimal("23.87") and six.c["swipes_end"].value == 56
    p = e.project(e.Scenario(meal_moves=-6), ds)
    ev = next(x for x in p.events if x.kind == "meal_plan")
    assert (ev.date, ev.amount) == (six.runs_out, Decimal("-23.87"))
    added = e.meal_plan_status(e.Scenario(dining_dollars_added=Decimal("150")), ds)
    assert added.c["dd_left"].value == Decimal("267.00") and added.runs_out is None
    p = e.project(e.Scenario(dining_dollars_added=Decimal("150")), ds)
    assert p.balance_on(date(2026, 10, 27)) == e.project(e.Scenario(), ds).balance_on(date(2026, 10, 27)) - 150


# --- story 7: aid opportunities --------------------------------------------------------------------------------

def test_story7_eligibility_and_timing(ds, key):
    kn = key[7]["key_numbers"]
    by = {x.opp.row_id: x for x in e.eligible_opportunities("2026-10-27", e.Scenario(), ds)}
    assert sorted(k for k, x in by.items() if x.status == "eligible") == kn["eligible"]
    assert [k for k, x in by.items() if x.status == "almost"] == list(kn["almost"])
    assert by["OPP-03"].missing == ["a 3.50 GPA (yours is 3.40)"]
    assert [k for k, x in by.items() if x.status == "not_eligible"] == kn["not_eligible"]
    grant = by["OPP-01"]
    assert grant.decided.isoformat() == kn["grant_decided"] and grant.arrives.value.isoformat() == kn["grant_arrives"]
    assert grant.before_run_out is kn["grant_before_run_out"] is True and grant.amount.value == Decimal("500.00")
    assert by["OPP-02"].arrives.value.isoformat() == kn["books_arrive"] and not by["OPP-02"].before_run_out
    spring = by["OPP-04"]
    assert spring.arrives.value.isoformat() == kn["spring_arrives"]
    assert str(spring.this_semester.value) == kn["spring_this_semester"] == "0.00"       # pays after the semester
    assert by["OPP-05"].arrives.value.isoformat() == kn["work_study_first_pay"] and not by["OPP-05"].before_run_out
    total = sum(x.amount.value for x in by.values() if x.status == "eligible" and x.amount)
    assert str(total) == kn["up_to_total"] == "1750.00"


def test_grants_are_never_certain_money(ds):
    base = e.project(e.Scenario(), ds)
    assert not [ev for ev in base.events if ev.kind == "aid_if_approved"]
    flight = e.can_afford("400.00", "2026-11-10", "checking", e.Scenario(), ds, "flight home")
    assert {f.kind for f in flight.considered} == {"refund", "cancel"}           # fixes never include a grant
    assert [f.name for f in flight.fixes] == ["refund released", "Spotify"]
    approved = e.project(e.Scenario(approved=("OPP-01",)), ds)
    ev = next(x for x in approved.events if x.kind == "aid_if_approved")
    assert (ev.date, ev.amount, ev.label) == (date(2026, 11, 2), Decimal("500.00"), "Student Emergency Grant (if approved)")
    assert approved.first_below_zero.value == date(2026, 12, 1)                  # from Mon, Nov 9
    spring = e.project(e.Scenario(approved=("OPP-04",)), ds)                     # pays in January: no change
    assert spring.end_balance.value == base.end_balance.value


def test_base_forecast_unchanged_by_the_new_sources(ds, key):
    p = e.project(e.Scenario(), ds)
    assert (p.first_below_zero.value, p.lowest.value, p.end_balance.value) == \
        (date(2026, 11, 9), Decimal("-1462.37"), Decimal("-1412.53"))
    assert not [ev for ev in p.events if ev.kind in ("aid_if_approved", "meal_plan")]


def test_attention_items_from_the_new_sources(ds):
    by = {a.kind: a for a in e.attention_items(e.Scenario(), ds)}
    g = by["grant"]
    assert g.due.value == date(2026, 11, 2) and g.stake.value == Decimal("500.00")          # last day to arrive in time
    assert e.opportunity_arrival(g.facts["amount"] and next(o for o in ds.opportunities if o.row_id == "OPP-01"),
                                 date(2026, 11, 2))[1] == date(2026, 11, 6)
    m = by["meal_plan"]
    assert m.due.value == date(2026, 11, 22) and m.urgency.value == 0              # $0 at stake for checking
    assert "grant" not in {a.kind for a in e.attention_items(e.Scenario(approved=("OPP-01",)), ds)}


# --- chat: find_aid and meal_plan --------------------------------------------------------------------------------

import agent  # noqa: E402

SUBS = ["Apple Music", "Spotify"]


def _quick(calls, ds):
    plan = agent.parse_plan({"calls": calls}, SUBS)
    results = agent.execute_all(plan, e.Scenario(), ds)
    pack = agent.build_pack(results, ds, plan, e.Scenario())
    required = agent.required_facts(plan, results, pack, ds, e.Scenario())
    quick = agent.quick_answer(plan, results, pack, ds, e.Scenario(), required)
    check = agent.check_answer(quick, pack, require_format=True, names=agent.merchant_accounts(ds), required=required,
                               events=agent.event_dates(ds, e.Scenario()), aid=calls[0]["tool"] == "find_aid")
    assert check.ok, check.problems
    assert not agent.missing_facts(quick, required)
    return quick, pack, required


def test_find_aid_answer_says_if_approved(ds):
    quick, pack, required = _quick([{"tool": "find_aid", "args": {}}], ds)
    assert quick.startswith("ANSWER: You may qualify for 3 awards worth up to $1,750")
    assert "Student Emergency Grant: up to $500" in quick and "if approved, it arrives around Mon, Nov 2" in quick
    assert "after the semester, so it adds $0.00 this semester" in quick                  # the spring scholarship
    assert "it's the only one that could arrive before Mon, Nov 9" in quick
    assert "You'd need a 3.50 GPA (yours is 3.40) for the Dean's Merit Scholarship." in quick
    assert "if_approved" in {f.key for f in required}
    assert not [it for it in pack.items if "Dean's Merit" in it.get("title", "")]     # not eligible: no amount to offer
    certain = quick.replace("up to $500 [C3]; if approved, it arrives around Mon, Nov 2", "$500 [C3]; it arrives Mon, Nov 2")
    assert certain != quick
    assert agent.check_answer(certain, pack, aid=True).problems[0].endswith('treats aid as certain; say "if approved"')
    quick, _, _ = _quick([{"tool": "find_aid", "args": {"type": "emergency_grant"}}], ds)
    assert quick.startswith("ANSWER: You may qualify for 1 award worth up to $500")


def test_meal_plan_answer(ds):
    quick, _, required = _quick([{"tool": "meal_plan", "args": {}}], ds)
    assert quick.startswith("ANSWER: Your dining dollars run out around Sun, Nov 22")
    assert "You'll have about 40 swipes left on Fri, Dec 18" in quick and "checking pays $0.00" in quick
    assert "you'd still have $16.56 in dining dollars on Fri, Dec 18" in quick
    assert {f.key for f in required} == {"runs_out", "swipes_end", "cost"}


def test_new_tools_validation_and_keywords():
    assert agent.validate_call("find_aid", {"type": "Scholarship"}, SUBS)[0] == {"type": "scholarship"}
    assert agent.validate_call("find_aid", {"type": "all"}, SUBS)[0] == {"type": None}         # seen live
    with pytest.raises(ValueError):
        agent.validate_call("find_aid", {"type": "loan"}, SUBS)
    assert agent.keyword_plan("Are there any grants or scholarships I qualify for?", SUBS).tool == "find_aid"
    assert agent.keyword_plan("Is there emergency money?", SUBS).args == {"type": "emergency_grant"}
    assert agent.keyword_plan("Will my dining dollars last?", SUBS).tool == "meal_plan"
    assert agent.keyword_plan("How many swipes do I have left?", SUBS).tool == "meal_plan"


def test_grants_never_become_afford_fixes_in_chat(ds):
    plan = agent.parse_plan({"calls": [{"tool": "can_afford", "args": {"item": "flight", "cost": 400,
                                                                         "date": "2026-11-10"}}]}, SUBS)
    approved = e.Scenario(approved=("OPP-01",))
    r = agent.execute_all(plan, approved, ds)[0]
    assert [f.name for f in r.fixes] == ["refund released", "Spotify"]          # the grant what-if is dropped


def test_deadlines_must_be_the_opportunitys_own(ds):
    """Seen live (fast): "Apply for the Student Emergency Grant before the Nov 15 deadline" (it's rolling)."""
    assert agent.deadline_problems("1. Apply for the Student Emergency Grant before the Nov 15 deadline.",
                                   ds.opportunities) == ["the Student Emergency Grant has no deadline (apply anytime), "
                                                         "not Sun, Nov 15"]
    assert agent.deadline_problems("Apply for the book scholarship by Nov 15.", ds.opportunities) == []
    assert agent.deadline_problems("Apply for the Textbook & Supplies Scholarship by Sun, Nov 15.", ds.opportunities) == []
    assert agent.deadline_problems("The Spring Opportunity Scholarship deadline is Sun, Nov 15.", ds.opportunities) ==         ["the Spring Opportunity Scholarship's deadline is Tue, Dec 1, not Sun, Nov 15"]
