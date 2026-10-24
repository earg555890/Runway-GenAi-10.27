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
GOOD_FLIGHT = ("Yes, if you do 2 things [C1]. Send your verification form so your $1,850.00 refund arrives around "
               "Thu Nov 5 [C6], and cancel Spotify to save $23.98 [C8]. Cancelling Apple Music saves $0.00 [C7] "
               "because the card bill is paid after the semester. Your lowest point would be $5.81 on Mon Nov 2 "
               "[C4][C5]. Next step: send the form today.")


@pytest.fixture(scope="module")
def ds():
    return normalize.load("local")


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ANSWER_CACHE_DIR", tmp_path / "answers")


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

    def __init__(self, plans=(), answers=(), plan_error=None, explain_error=None):
        self.plans, self.answers = list(plans), list(answers)
        self.plan_error, self.explain_error = plan_error, explain_error
        self.calls = []

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

    def stream_chat(self, messages, thinking=True, **kwargs):
        self.calls.append(("explain", thinking))
        if self.explain_error:
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
    assert p.assumptions == ["You didn't say when you'd buy it, so I assumed tomorrow, Tue Oct 27."]


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
    assert r.verdict == "runs_out" and agent.verdict_label(r) == "Money runs out Mon Nov 9"
    assert {"$359.53", "Mon Nov 9", "2.0 weeks", "-$1,462.37"} <= values(pack)


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
    assert {"$1,850.00", "$3,697.00", "Thu Nov 5"} <= values(pack)
    assert any(it["kind"] == "source" and "REQ-01" in it["row_ids"] for it in pack.items)
    _, pack = pack_for("cash_crunches", {}, ds)
    assert {"$200.00", "$114.70", "Fri Nov 20"} <= values(pack)


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
    ("Your refund arrives Wed Nov 5 [C6].", "wrong weekday"),
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
    assert llm.calls[0] == ("plan", False) and llm.calls[1] == ("explain", True)


def test_explain_retry_then_warn(ds):
    llm = FakeLLM(plans=[FLIGHT_PLAN], answers=["You'd have $412.50 left [C4].", "Still $412.50 [C4]."])
    _, a = run_all(FLIGHT_Q, llm, ds=ds)
    assert not a.check["ok"] and any("$412.50" in n for n in a.notes)
    assert not list(config.ANSWER_CACHE_DIR.glob("*.json"))          # failed answers are not cached


# --- fallbacks, off-topic, actions -----------------------------------------------------------

def test_explain_failure_uses_template(ds):
    llm = FakeLLM(plans=[FLIGHT_PLAN], explain_error=llm_client.LLMError("timeout"))
    _, a = run_all(FLIGHT_Q, llm, ds=ds)
    assert a.explain_source == "template" and a.mode == "fallback" and a.check["ok"]
    assert a.text.startswith("Yes, if you do 2 things") and "$5.81" in a.text and "Apple Music" in a.text
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
    assert "Cancel Spotify before Sat Nov 14." in checklist["items"]
    assert a.fixes == [{"kind": "refund", "name": "refund released"}, {"kind": "cancel", "name": "Spotify"}]


# --- cache and replay ------------------------------------------------------------------------

def test_cached_and_replay_modes(ds):
    _, live = run_all(FLIGHT_Q, FakeLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT]), ds=ds)
    assert live.mode == "live"
    _, cached = run_all("  can I afford a $400 flight home for thanksgiving if I book it Nov 10 ", NoLLM(),
                        mode="cached", ds=ds)
    assert cached.mode == "cached" and cached.text == GOOD_FLIGHT and cached.timings == live.timings
    events, replayed = run_all(FLIGHT_Q, NoLLM(), mode="replay", ds=ds)
    assert replayed.mode == "replay"
    assert "".join(p for k, p in events if k == "text") == GOOD_FLIGHT
    assert [p for k, p in events if k == "stage"] == list(agent.STAGES.values())
    # a different what-if is a different answer
    _, other = run_all(FLIGHT_Q, NoLLM(), mode="replay", ds=ds, scenario=engine.Scenario(refund_released=True))
    assert other.explain_source == "template" and any("no recorded answer" in n for n in other.notes)


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
    assert a.explain_source == "template" and a.text.startswith("Yes, if you do 2 things") and a.check["ok"]
