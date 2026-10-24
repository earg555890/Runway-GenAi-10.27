"""agent: PLAN validation, tool execution and evidence packs, the checker, fallbacks, cache/replay. No network."""
from types import SimpleNamespace

import pytest

import agent
import config
import engine
import llm_client
import normalize

FLIGHT_Q = "Can I afford a $400 flight home for Thanksgiving if I book it Nov 10?"
FLIGHT_PLAN = '{"intent": "afford", "tool": "can_afford", "args": {"item": "flight home", "cost": 400, ' \
              '"date": "2026-11-10"}, "clarifying_question": null}'
GOOD_FLIGHT = ("ANSWER: Yes, if you do 2 things first [C1].\n"
               "WHY:\n"
               "- Without changes, you'd be $1,862 below zero [C2].\n"
               "- With them, your lowest point is $5.81 on Mon, Nov 2 [C4][C5].\n"
               "DO THIS:\n"
               "1. Send your verification form. Your $1,850 refund comes around Thu, Nov 5 [C6].\n"
               "2. Cancel Spotify. That saves $23.98 this semester [C8].\n"
               "NOTE: Cancelling Apple Music saves $0.00 [C7]. Its card bill is paid after the semester.")


@pytest.fixture(scope="module")
def ds():
    return normalize.load("local")


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ANSWER_CACHE_DIR", tmp_path / "answers")
    monkeypatch.setattr(config, "DEMO_ANSWERS_DIR", tmp_path / "demo_answers")


SUBS = ["Apple Music", "Spotify"]


class FakeStream:
    def __init__(self, text):
        self.text, self.result = text, None

    def __iter__(self):
        yield "reasoning", "Let me look at the facts."
        for word in self.text.split(" "):
            yield "text", word + " "
        self.result = SimpleNamespace(text=self.text, reasoning="Let me look at the facts.")


class FakeLLM:
    """Plays back PLAN replies (JSON strings, validated like llm_client.chat_json) and EXPLAIN texts."""

    def __init__(self, plans=(), answers=(), plan_error=None, explain_error=None, failing_models=()):
        self.plans, self.answers = list(plans), list(answers)
        self.plan_error, self.explain_error = plan_error, explain_error
        self.failing_models = set(failing_models)      # explain_error only for these models (all if empty)
        self.calls, self.messages = [], []

    def chat_json(self, messages, thinking=False, validate=None, **kwargs):
        self.calls.append(("plan", thinking))
        if self.plan_error:
            raise self.plan_error
        for attempt in range(2):
            raw = self.plans.pop(0)
            try:
                data = llm_client.parse_json(raw)
                validate(data)
                return SimpleNamespace(data=data, json_retries=attempt, retries=0)
            except ValueError as exc:
                if attempt == 1:
                    raise llm_client.InvalidJSONError(str(exc), raw) from exc

    def stream_chat(self, messages, thinking=True, model=None, **kwargs):
        self.calls.append(("explain", thinking))
        self.messages.append((model, messages))
        if self.explain_error and (not self.failing_models or model in self.failing_models):
            raise self.explain_error
        return FakeStream(self.answers.pop(0))


class NoLLM:
    def chat_json(self, *a, **k):
        raise AssertionError("must not call PLAN")

    def stream_chat(self, *a, **k):
        raise AssertionError("must not call EXPLAIN")


def run_all(question, llm, scenario=None, mode="live", ds=None):
    events = list(agent.run(question, scenario or engine.Scenario(), ds=ds, mode=mode, llm=llm, typing_s=0))
    assert events[-1][0] == "answer"
    return events, events[-1][1]


# --- PLAN validation -------------------------------------------------------------------------

def test_parse_plan_good_and_missing_date_assumption():
    p = agent.parse_plan(llm_client.parse_json(FLIGHT_PLAN), SUBS)
    assert (p.tool, p.args["cost"], p.args["date"], p.args["account"], p.assumptions) == \
        ("can_afford", "400.00", "2026-11-10", "checking", [])
    p = agent.parse_plan({"intent": "afford", "tool": "can_afford", "args": {"item": "headphones", "cost": "$150"}},
                         SUBS)
    assert p.args["date"] == "2026-10-27"
    assert p.assumptions == ["You didn't say when you'd buy it, so I assumed tomorrow, Tue, Oct 27."]


@pytest.mark.parametrize("data,message", [
    ([1, 2], "one JSON object"),
    ({"intent": "afford", "tool": "buy_stuff", "args": {}}, "unknown tool"),
    ({"intent": "afford", "tool": "can_afford", "args": {"cost": 400, "date": "2026-12-25"}}, "outside"),
    ({"intent": "afford", "tool": "can_afford", "args": {"cost": 400, "date": "2026-10-20"}}, "outside"),
    ({"intent": "afford", "tool": "can_afford", "args": {"cost": -5}}, "positive"),
    ({"intent": "afford", "tool": "can_afford", "args": {"cost": 5, "colour": "red"}}, "no argument"),
    ({"intent": "what_if", "tool": "what_if", "args": {"cancel_subscriptions": ["Netflix"]}}, "unknown subscription"),
    ({"intent": "what_if", "tool": "what_if", "args": {}}, "at least one change"),
    ({"intent": "runway", "tool": "none"}, "tool"),
])
def test_parse_plan_rejects(data, message):
    with pytest.raises(ValueError, match=message):
        agent.parse_plan(data, SUBS)


def test_parse_plan_off_topic_and_canonical_subscription_names():
    assert agent.parse_plan({"intent": "off_topic", "tool": "none"}, SUBS).tool is None
    p = agent.parse_plan({"intent": "what_if", "tool": "what_if",
                          "args": {"cancel_subscriptions": ["spotify"],
                                   "extra_shifts": [{"date": "2026-11-07", "hours": 5}]}}, SUBS)
    assert p.args["cancel_subscriptions"] == ["Spotify"] and p.args["extra_shifts"][0]["hours"] == "5.00"


def test_bad_json_twice_falls_back_to_keywords(ds):
    llm = FakeLLM(plans=["not json", '{"tool": "nope"}'], answers=[GOOD_FLIGHT])
    _, a = run_all(FLIGHT_Q, llm, ds=ds)
    assert a.plan["source"] == "keywords" and a.plan["tool"] == "can_afford" and a.plan["args"]["date"] == "2026-11-10"
    assert a.mode == "fallback" and any("planner" in n for n in a.notes)


def test_plan_retry_after_validation_error_counts(ds):
    llm = FakeLLM(plans=['{"intent": "afford", "tool": "can_afford", "args": {"cost": 400, "date": "2026-12-25"}}',
                         FLIGHT_PLAN], answers=[GOOD_FLIGHT])
    _, a = run_all(FLIGHT_Q, llm, ds=ds)
    assert a.retries["plan_json"] == 1 and a.mode == "live" and a.check["ok"]


# --- EXECUTE and the evidence pack -----------------------------------------------------------

def pack_for(tool, args, ds, scenario=None):
    plan = agent.parse_plan({"intent": "x", "tool": tool, "args": args}, SUBS)
    scenario = scenario or engine.Scenario()
    result = agent.execute(plan, scenario, ds)
    return result, agent.build_pack(result, ds, plan, scenario)


def values(pack):
    return {it["value"] for it in pack.items if it["kind"] == "calc"}


def test_can_afford_pack(ds):
    r, pack = pack_for("can_afford", {"item": "flight home", "cost": 400, "date": "2026-11-10"}, ds)
    assert r.verdict == "yes_if" and [f.name for f in r.fixes] == ["refund released", "Spotify"]
    assert {"$5.81", "-$1,862.37", "$1,850.00", "$23.98", "$0.00"} <= values(pack)
    assert pack.items[0]["value"] == "yes_if" and pack.cite(r.key[0]) == "[C1]"
    sources = [it for it in pack.items if it["kind"] == "source"]
    assert any(it["title"].startswith("Your checking account") and it["query"] == "checking_account" for it in sources)
    assert any(it["source"] == "bursar" and "RFD-01" in it["row_ids"] for it in sources)
    assert len([it for it in pack.items if it["kind"] == "calc"]) <= agent.MAX_PACK_CALCS
    assert all(len(it["rows"]) <= agent.MAX_ROWS_PER_SOURCE for it in sources)


def test_runway_pack(ds):
    r, pack = pack_for("runway", {}, ds)
    assert r.verdict == "runs_out" and agent.verdict_label(r) == "Money runs out Mon, Nov 9"
    assert {"$359.53", "Mon, Nov 9", "2.0 weeks", "-$1,462.37"} <= values(pack)


def test_what_if_shift_pack(ds):
    r, pack = pack_for("what_if", {"extra_shifts": [{"date": "2026-11-07", "hours": 5}]}, ds)
    assert "$71.69" in values(pack)                     # 8 -> 13 hours: $114.70 -> $186.39 on Nov 18
    assert r.verdict == "runs_out"


def test_what_if_refund_and_spotify_pack(ds):
    r, pack = pack_for("what_if", {"cancel_subscriptions": ["Spotify"], "send_verification_form": True}, ds)
    assert r.verdict == "covered" and {"$1,850.00", "$23.98"} <= values(pack)


def test_leaks_refund_crunch_packs(ds):
    _, pack = pack_for("find_leaks", {}, ds)
    assert {"$22.98", "$23.98", "$0.00", "$35.00", "Spotify"} <= values(pack)
    _, pack = pack_for("refund_status", {}, ds)
    assert {"$1,850.00", "$3,697.00", "Thu, Nov 5"} <= values(pack)
    assert any(it["kind"] == "source" and "REQ-01" in it["row_ids"] for it in pack.items)
    _, pack = pack_for("cash_crunches", {}, ds)
    assert {"$200.00", "$114.70", "Fri, Nov 20"} <= values(pack)


# --- CHECK -----------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def flight_pack(ds):
    return pack_for("can_afford", {"item": "flight home", "cost": 400, "date": "2026-11-10"}, ds)[1]


def test_check_passes_with_format_variants(flight_pack):
    c = agent.check_answer("Your $1,850 refund [C6] comes Nov 5 (Thursday, November 5th) [C6]. Without changes you'd "
                           "be $1,862.37 below zero [C2], or -$1,862.37 on 2026-12-17 [C3]. Thanksgiving is Nov 26.",
                           flight_pack)
    assert c.ok, c.problems
    assert agent.check_answer(GOOD_FLIGHT, flight_pack).ok


@pytest.mark.parametrize("text,problem", [
    ("You'd have $412.50 left [C4].", "$412.50"),
    ("Your refund arrives Fri Nov 6 [C6].", "Fri Nov 6"),
    ("Your refund arrives Wed, Nov 5 [C6].", "wrong weekday"),
    ("Your lowest point is $5.81 [C99].", "[C99]"),
    ("See [E42].", "[E42]"),
])
def test_check_catches(flight_pack, text, problem):
    c = agent.check_answer(text, flight_pack)
    assert not c.ok and any(problem in p for p in c.problems), c.problems


def test_explain_retry_then_pass(ds):
    llm = FakeLLM(plans=[FLIGHT_PLAN], answers=["You'd have $412.50 left [C4].", GOOD_FLIGHT])
    events, a = run_all(FLIGHT_Q, llm, ds=ds)
    assert a.check["ok"] and a.retries["explain_rewrite"] == 1 and a.text == GOOD_FLIGHT
    assert ("restart", "Double-checking the numbers...") in events
    assert [c[0] for c in llm.calls] == ["plan", "explain", "explain"]
    assert llm.calls[0] == ("plan", False) and llm.calls[1] == ("explain", False)      # fast mode: thinking off


def test_explain_retry_then_warn(ds):
    llm = FakeLLM(plans=[FLIGHT_PLAN], answers=["You'd have $412.50 left [C4].", "Still $412.50 [C4]."])
    events, a = run_all(FLIGHT_Q, llm, ds=ds)
    # the AI answer failed twice: the quick answer (built from the engine) stays, with a note saying why
    assert a.explain_source == "template" and a.text == a.quick and a.check["ok"]
    assert any("didn't pass Runway's checks" in n and "$412.50" in n for n in a.notes)
    assert ("quick", a.quick) in events
    assert not list(config.ANSWER_CACHE_DIR.glob("*.json"))          # failed answers are not cached


# --- fallbacks, off-topic, actions -----------------------------------------------------------

def test_explain_failure_uses_template(ds):
    llm = FakeLLM(plans=[FLIGHT_PLAN], explain_error=llm_client.LLMError("timeout"))
    _, a = run_all(FLIGHT_Q, llm, ds=ds)
    assert a.explain_source == "template" and a.mode == "fallback" and a.check["ok"]
    assert a.text.startswith("ANSWER: Yes, if you do 2 things") and "$5.81" in a.text and "Apple Music" in a.text
    assert a.sections["do"][0].startswith("Send your verification form") and len(a.sections["why"]) == 2
    assert any("The AI explanation isn't available right now" in n for n in a.notes)


def test_both_models_down_still_answers_suggested_questions(ds):
    down = FakeLLM(plan_error=TimeoutError(), explain_error=TimeoutError())
    for q, tool in [(FLIGHT_Q, "can_afford"), ("How long will my money last?", "runway"),
                    ("Where is my money leaking?", "find_leaks")]:
        _, a = run_all(q, down, ds=ds)
        assert a.plan["tool"] == tool and a.check["ok"] and a.text


def test_off_topic_makes_no_explain_call(ds):
    llm = FakeLLM(plans=['{"intent": "off_topic", "tool": "none", "args": {}}'])
    _, a = run_all("What's the capital of France?", llm, ds=ds)
    assert a.text == agent.OFF_TOPIC and a.mode == "off_topic" and llm.calls == [("plan", False)]


def test_actions_email_and_checklist(ds):
    _, a = run_all(FLIGHT_Q, FakeLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT]), ds=ds)
    email = next(x for x in a.actions if x["kind"] == "email")
    assert email["to"] == "Office of Student Financial Aid"
    assert "2026-27 Verification Worksheet (Dependent)" in email["subject"] and "Fall 2026" in email["body"]
    assert "$1,850.00" in email["body"]
    checklist = next(x for x in a.actions if x["kind"] == "checklist")
    assert "Cancel Spotify before Sat, Nov 14." in checklist["items"]
    assert a.fixes == [{"kind": "refund", "name": "refund released"}, {"kind": "cancel", "name": "Spotify"}]


# --- cache and replay ------------------------------------------------------------------------

def test_cached_and_replay_modes(ds):
    _, live = run_all(FLIGHT_Q, FakeLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT]), ds=ds)
    assert live.mode == "live"
    _, cached = run_all("  can I afford a $400 flight home for thanksgiving if I book it Nov 10 ", NoLLM(),
                        mode="cached", ds=ds)
    assert cached.mode == "cached" and cached.text == GOOD_FLIGHT and cached.timings == live.timings
    _, missing = run_all(FLIGHT_Q, NoLLM(), mode="replay", ds=ds)        # replay reads only demo_answers/
    assert missing.mode == "no_key"
    agent.save_cached(live, engine.Scenario(), config.DEMO_ANSWERS_DIR)
    events, replayed = run_all(FLIGHT_Q, NoLLM(), mode="replay", ds=ds)
    assert replayed.mode == "replay"
    assert "".join(p for k, p in events if k == "text") == GOOD_FLIGHT
    assert [p for k, p in events if k == "stage"] == list(agent.STAGES.values())
    agent.cache_path(FLIGHT_Q, engine.Scenario()).unlink()                 # cached falls back to demo_answers/
    _, from_demo = run_all(FLIGHT_Q, NoLLM(), mode="cached", ds=ds)
    assert from_demo.mode == "cached" and from_demo.text == GOOD_FLIGHT
    # a different what-if is a different answer: no recording, so a friendly message and no model calls
    llm = NoLLM()
    _, other = run_all(FLIGHT_Q, llm, mode="replay", ds=ds, scenario=engine.Scenario(refund_released=True))
    assert other.mode == "no_key" and "Recorded answers cover the four suggested questions" in other.text


def test_no_key_typed_question_gets_friendly_message(ds, monkeypatch):
    monkeypatch.setattr(config, "NVIDIA_API_KEY", None)
    for mode in ("cached", "live", "replay"):
        events, a = run_all("Can I afford a $90 jacket?", None, mode=mode, ds=ds)   # the real client
        assert a.mode == "no_key" and a.text.startswith("Live answers need an NVIDIA key.")
        assert "add NVIDIA_API_KEY to .env" in a.text and not a.check


def test_cached_mode_misses_go_live(ds):
    llm = FakeLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT])
    _, a = run_all(FLIGHT_Q, llm, mode="cached", ds=ds)
    assert a.mode == "live" and len(llm.calls) == 2


def test_keyword_plan():
    assert agent.keyword_plan("Can I afford a $400 flight home for Thanksgiving?", SUBS).args["date"] == "2026-10-27"
    assert agent.keyword_plan("am I ok?", SUBS).tool == "runway"
    assert agent.keyword_plan("tell me a joke", SUBS) is None
    assert agent.keyword_plan("Can I afford a $90 dinner on Nov 7 on my credit card?", SUBS).args == \
        {"cost": "90.00", "item": "this purchase", "account": "card", "date": "2026-11-07"}


def test_empty_answer_is_rewritten_then_falls_back(ds):
    llm = FakeLLM(plans=[FLIGHT_PLAN], answers=["", GOOD_FLIGHT])
    _, a = run_all(FLIGHT_Q, llm, ds=ds)
    assert a.text == GOOD_FLIGHT and a.retries["explain_rewrite"] == 1
    llm = FakeLLM(plans=[FLIGHT_PLAN], answers=["", " "])
    _, a = run_all(FLIGHT_Q, llm, ds=ds)
    assert a.explain_source == "template" and a.text.startswith("ANSWER: Yes, if you do 2 things") and a.check["ok"]


def test_super_down_lightning_answers(ds, monkeypatch):
    monkeypatch.setattr(config, "NVIDIA_EXPLAIN_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b")
    monkeypatch.setattr(config, "NVIDIA_PLAN_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
    llm = FakeLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT], explain_error=llm_client.LLMError("503"),
                  failing_models={"nvidia/nemotron-3.5-super-vl-120b-a12b"})
    events = list(agent.run(FLIGHT_Q, engine.Scenario(), ds=ds, mode="live", llm=llm, typing_s=0, think=True))
    a = events[-1][1]
    assert a.explain_source == "llm" and a.mode == "live" and a.text == GOOD_FLIGHT
    assert a.models["answered_by"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert [m for m, _ in llm.messages] == ["nvidia/nemotron-3.5-super-vl-120b-a12b",
                                           "nvidia/nemotron-3.5-lightning-30b-a3b"]
    assert llm.calls[-1] == ("explain", True)                       # Lightning explains with thinking on
    assert any("Nemotron Lightning wrote this answer" in n for n in a.notes)


def test_all_models_down_template_records_errors(ds):
    _, a = run_all(FLIGHT_Q, FakeLLM(plans=[FLIGHT_PLAN], explain_error=llm_client.LLMError("503")), ds=ds)
    assert a.models["answered_by"] == "template" and len(a.models["explain_errors"]) == len(agent.explain_chain())


def test_leaks_prompt_requires_monthly_total(ds):
    llm = FakeLLM(plans=['{"intent": "leaks", "tool": "find_leaks", "args": {}}'],
                  answers=["ANSWER: Two leaks.\nWHY:\n- You pay $22.98 a month [C3] for Spotify and Apple Music.\n"
                           "- Rent caused a $35 fee [C9]."])
    run_all("Where is my money leaking?", llm, ds=ds)
    prompt = llm.messages[0][1][1]["content"]
    assert "Your answer must include all of these:" in prompt
    assert "- their monthly total: Together they cost $22.98 a month [C3]." in prompt


def test_fourth_suggested_question_is_the_undated_flight(ds):
    assert agent.SUGGESTED[3] == "Can I afford a $400 flight home for Thanksgiving?"
    down = FakeLLM(plan_error=TimeoutError(), explain_error=TimeoutError())
    _, a = run_all(agent.SUGGESTED[3], down, ds=ds)
    assert a.verdict == "no" and a.verdict_label == "Not right now" and a.plan["args"]["date"] == "2026-10-27"


@pytest.mark.parametrize("question,grounded", [
    ("Can I afford a $400 flight home for Thanksgiving?", False),
    ("Can I afford a $400 flight home for Thanksgiving if I book it Nov 10?", True),
    ("Can I buy a $30 pie on Thanksgiving?", True),
    ("Can I afford $60 concert tickets this Friday?", True),
    ("Can I afford headphones for $150 tomorrow?", True),
])
def test_purchase_date_must_come_from_the_question(question, grounded):
    plan = agent.parse_plan({"intent": "afford", "tool": "can_afford",
                             "args": {"item": "x", "cost": 400, "date": "2026-11-26"}}, SUBS)
    plan = agent.ground_purchase_date(plan, question)
    assert (plan.args["date"] == "2026-11-26") == grounded
    assert bool(plan.assumptions) != grounded


def test_thanksgiving_trip_date_from_planner_is_replaced(ds):
    llm = FakeLLM(plans=['{"intent": "afford", "tool": "can_afford", "args": {"item": "flight home", "cost": 400, '
                         '"date": "2026-11-26"}}'], answers=["ANSWER: Not right now [C1].\nWHY:\n- Even with fixes you'd be short."])
    _, a = run_all("Can I afford a $400 flight home for Thanksgiving?", llm, ds=ds)
    assert a.plan["args"]["date"] == "2026-10-27" and a.verdict == "no" and a.plan["assumptions"]


def test_check_accepts_rounded_dollars_and_below_zero(flight_pack):
    ok = agent.check_answer("You'd be $1,862 below zero [C2]. Your $1,850 refund helps [C6]. Lowest $5.81 [C4].",
                            flight_pack)
    assert ok.ok, ok.problems
    bad = agent.check_answer("You'd be $1,870 below zero [C2].", flight_pack)
    assert not bad.ok and "$1,870 is not in the facts" in bad.problems
    assert not agent.check_answer("You'd have $5.80 [C4].", flight_pack).ok     # cents must be exact


def test_format_required_for_model_answers(ds):
    llm = FakeLLM(plans=[FLIGHT_PLAN], answers=["Yes, if you send the form [C1].", GOOD_FLIGHT])
    _, a = run_all(FLIGHT_Q, llm, ds=ds)
    assert a.retries["explain_rewrite"] == 1 and a.text == GOOD_FLIGHT
    assert a.sections["answer"] == "Yes, if you do 2 things first [C1]."
    assert a.sections["note"].startswith("Cancelling Apple Music saves $0.00")


def test_parse_sections_tolerates_markdown():
    s = agent.parse_sections("**ANSWER:** Yes.\n**WHY:**\n* one\n* two\n**DO THIS:**\n1) go\nNOTE: n")
    assert s == {"answer": "Yes.", "why": ["one", "two"], "do": ["go"], "note": "n"}
    assert agent.parse_sections("Just a paragraph.") is None


# --- required facts: built from the engine, enforced by CHECK -------------------------------------

def _facts(tool, args, ds):
    plan = agent.parse_plan({"intent": "x", "tool": tool, "args": args}, SUBS)
    result = agent.execute(plan, engine.Scenario(), ds)
    pack = agent.build_pack(result, ds, plan, engine.Scenario())
    return {f.key: f for f in agent.required_facts(plan, result, pack, ds, engine.Scenario())}


def test_required_facts_per_tool_use_engine_values(ds):
    from datetime import date
    from decimal import Decimal as Dec
    f = _facts("can_afford", {"item": "flight home", "cost": 400, "date": "2026-11-10"}, ds)
    assert set(f) == {"verdict", "fix_refund", "fix_Spotify", "lowest"}
    assert f["fix_refund"].money == (Dec("1850.00"),) and f["fix_refund"].date == date(2026, 11, 5)
    assert f["fix_Spotify"].money == (Dec("23.98"),) and f["lowest"].money == (Dec("5.81"),)
    f = _facts("can_afford", {"item": "headphones", "cost": 150}, ds)
    assert f["assumption"].where == "note" and f["assumption"].date == date(2026, 10, 27)
    f = _facts("runway", {}, ds)
    assert f["runs_out"].date == date(2026, 11, 9) and f["cause"].money == (Dec("-359.53"), Dec("307.20"))
    f = _facts("what_if", {"extra_shifts": [{"date": "2026-11-07", "hours": 5}]}, ds)
    assert f["shift_pay"].money == (Dec("71.69"),) and f["shift_pay"].date == date(2026, 11, 18)
    assert f["shift_pay"].where == "lead"
    f = _facts("find_leaks", {}, ds)
    assert f["monthly_total"].money == (Dec("22.98"),) and f["fee"].money == (Dec("35.00"),)
    assert {"sub_Spotify", "sub_Apple Music"} <= set(f)
    f = _facts("refund_status", {}, ds)
    assert f["refund_amount"].money == (Dec("1850.00"),) and f["arrives"].date == date(2026, 11, 5)
    assert "Verification Worksheet" in f["waiting_on"].line
    f = _facts("cash_crunches", {}, ds)
    assert f["payment0"].money == (Dec("200.00"),) and f["paycheck0"].money == (Dec("114.70"),)
    assert f["paycheck0"].date == date(2026, 11, 18)


REFUND_Q = "Why is my refund on hold?"
REFUND_PLAN = '{"intent": "refund", "tool": "refund_status", "args": {}}'
REFUND_GOOD = ("ANSWER: Your $1,850 refund [C4] is on hold.\nWHY:\n- Financial aid is waiting for your "
               "verification worksheet.\nDO THIS:\n1. Send it. The refund arrives around Thu, Nov 5 [C7].")
REFUND_NO_AMOUNT = ("ANSWER: Your refund is on hold.\nWHY:\n- Financial aid is waiting for your verification "
                    "worksheet.\nDO THIS:\n1. Send it. The refund arrives around Thu, Nov 5 [C7].")


def test_missing_required_fact_triggers_the_rewrite(ds):
    llm = FakeLLM(plans=[REFUND_PLAN], answers=[REFUND_NO_AMOUNT, REFUND_GOOD])
    _, a = run_all(REFUND_Q, llm, ds=ds)
    assert a.text == REFUND_GOOD and a.retries["explain_rewrite"] == 1 and a.retries["facts_appended"] == 0
    rewrite_request = llm.messages[1][1][-1]["content"]
    assert "missing the refund amount: Your $1,850 refund [C4] is on hold." in rewrite_request
    assert all(not f["appended"] for f in a.facts)


def test_rewrite_still_missing_gets_the_deterministic_line(ds):
    llm = FakeLLM(plans=[REFUND_PLAN], answers=[REFUND_NO_AMOUNT, REFUND_NO_AMOUNT])
    _, a = run_all(REFUND_Q, llm, ds=ds)
    assert a.retries["facts_appended"] == 1 and a.check["ok"] and a.mode == "live"
    assert "Your $1,850 refund [C4] is on hold." in a.sections["why"]
    assert [f["key"] for f in a.facts if f["appended"]] == ["refund_amount"]
    assert agent.missing_facts(a.text, _facts("refund_status", {}, ds).values()) == []


def test_record_id_triggers_rewrite_and_never_reaches_the_screen(ds):
    with_id = REFUND_GOOD.replace("Financial aid", "Hold HLD-01 means financial aid")
    llm = FakeLLM(plans=[REFUND_PLAN], answers=[with_id, REFUND_GOOD])
    _, a = run_all(REFUND_Q, llm, ds=ds)
    assert a.retries["explain_rewrite"] == 1 and "HLD-01" not in a.text
    assert "HLD-01 is a record ID" in llm.messages[1][1][-1]["content"]
    pack = agent.build_pack(*(lambda p: (agent.execute(p, engine.Scenario(), ds), ds, p, engine.Scenario()))(
        agent.parse_plan({"intent": "x", "tool": "refund_status", "args": {}}, SUBS)))
    assert not agent.check_answer(with_id, pack).ok
    from ui import fmt
    assert "HLD" not in fmt.strip_ids("Hold HLD-01 blocks refunds.")


def test_what_if_answer_leads_with_the_change(ds):
    plan = '{"intent": "what_if", "tool": "what_if", "args": {"extra_shifts": [{"date": "2026-11-07", "hours": 5}]}}'
    buried = ("ANSWER: Your money still runs out on Mon, Nov 9 [C7].\nWHY:\n- A big card bill is due.\n"
              "- The extra shift adds $71.69 to your Wed, Nov 18 paycheck [C14].\nDO THIS:\n1. Take the shift.")
    lead = ("ANSWER: The extra shift adds $71.69 to your Wed, Nov 18 paycheck [C14].\nWHY:\n- Your money still runs "
            "out on Mon, Nov 9 [C7].\n- A shift worked by Sat, Oct 31 is paid Tue, Nov 3, before you run out [C15].\n"
            "DO THIS:\n1. Take the shift.")
    _, a = run_all("What if I pick up a 5 hour shift on Nov 7?", FakeLLM(plans=[plan], answers=[buried, lead]), ds=ds)
    assert a.text == lead and a.retries["explain_rewrite"] == 1
    _, a = run_all("What if I pick up a 5 hour shift on Nov 7?", FakeLLM(plans=[plan], answers=[buried, buried]),
                   ds=ds)
    assert a.sections["why"][0] == "The extra shift adds $71.69 to your Wed, Nov 18 paycheck [C14]."
    assert a.retries["facts_appended"] == 2                 # the extra pay (as the lead) and the in-time shift
    assert "A shift worked by Sat, Oct 31 is paid Tue, Nov 3, before you run out [C15]." in a.sections["why"]


def test_template_answers_contain_every_required_fact(ds):
    down = FakeLLM(plan_error=TimeoutError(), explain_error=TimeoutError())
    for q in agent.SUGGESTED + [REFUND_Q]:
        _, a = run_all(q, down, ds=ds)
        assert a.check["ok"], (q, a.check)
        assert a.facts and all(f["key"] for f in a.facts)


def test_late_shift_answer_must_say_which_shift_is_paid_in_time(ds):
    f = _facts("what_if", {"extra_shifts": [{"date": "2026-11-07", "hours": 5}]}, ds)
    from datetime import date
    assert f["latest_shift"].date == (date(2026, 10, 31), date(2026, 11, 3))
    assert f["latest_shift"].line.startswith("A shift worked by Sat, Oct 31 is paid Tue, Nov 3, before you run out")
    assert "latest_shift" not in _facts("what_if", {"extra_shifts": [{"date": "2026-10-30", "hours": 4}]}, ds)
