"""Ask Runway as a conversation: the new tools, multi-step plans, follow-ups, the quick answer, fast vs Think harder,
general info, and the smarter checks. Mocked models, no network."""
import json
from datetime import date
from types import SimpleNamespace

import pytest

import agent
import config
import engine
import normalize
from test_agent import FLIGHT_PLAN, FLIGHT_Q, GOOD_FLIGHT, FakeLLM

SUBS = ["Apple Music", "Spotify"]


@pytest.fixture(scope="module")
def ds():
    return normalize.load("local")


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ANSWER_CACHE_DIR", tmp_path / "answers")
    monkeypatch.setattr(config, "DEMO_ANSWERS_DIR", tmp_path / "demo_answers")


class RecordingLLM(FakeLLM):
    """FakeLLM that also keeps the PLAN messages."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.plan_messages = []

    def chat_json(self, messages, thinking=False, validate=None, **kwargs):
        self.plan_messages.append(messages)
        return super().chat_json(messages, thinking, validate, **kwargs)


def plan_json(calls, resolved=None):
    return json.dumps({"resolved_question": resolved, "calls": calls, "clarifying_question": None})


def run_all(question, llm, ds, scenario=None, history=(), think=False):
    events = list(agent.run(question, scenario or engine.Scenario(), ds=ds, mode="live", llm=llm, typing_s=0,
                            history=history, think=think))
    assert events[-1][0] == "answer"
    return events, events[-1][1]


def _pieces(calls, ds, scenario=None):
    scenario = scenario or engine.Scenario()
    plan = agent.parse_plan({"calls": calls}, SUBS)
    results = agent.execute_all(plan, scenario, ds)
    pack = agent.build_pack(results, ds, plan, scenario)
    return plan, results, pack, agent.required_facts(plan, results, pack, ds, scenario)


# --- every new tool: executes, has required facts, and a quick answer that passes every check --------------

@pytest.mark.parametrize("calls,keys", [
    ([{"tool": "spending_summary", "args": {"start": "2026-10-01", "end": "2026-10-31"}}],
     {"total", "group_Rent", "group_Shopping", "group_School"}),
    ([{"tool": "find_transactions", "args": {"query": "Kroger"}}], {"spent", "count"}),
    ([{"tool": "find_transactions", "args": {"query": "Starbucks"}}], {"none"}),
    ([{"tool": "upcoming_bills", "args": {"start": "2026-10-27", "end": "2026-11-09"}}],
     {"bill0", "bill1", "bill2", "total"}),
    ([{"tool": "work_summary", "args": {"start": "2026-10-01", "end": "2026-10-31"}}], {"worked", "scheduled", "pay"}),
    ([{"tool": "balance_on", "args": {"date": "2026-11-26"}}], {"balance"}),
    ([{"tool": "accounts_today", "args": {}}], {"checking", "card", "refund", "paycheck"}),
    ([{"tool": "money_ideas", "args": {}}], {"deadline", "idea_shift", "idea_refund"}),
])
def test_new_tools_quick_answer_passes_every_check(ds, calls, keys):
    plan, results, pack, required = _pieces(calls, ds)
    assert {f.key for f in required} == keys
    quick = agent.quick_answer(plan, results, pack, ds, engine.Scenario(), required)
    check = agent.check_answer(quick, pack, require_format=True, names=agent.merchant_accounts(ds))
    assert check.ok, (quick, check.problems)
    assert not agent.missing_facts(quick, required)


def test_money_ideas_answer_has_amounts_and_dates(ds):
    plan, results, pack, required = _pieces([{"tool": "money_ideas", "args": {}}], ds)
    quick = agent.quick_answer(plan, results, pack, ds, engine.Scenario(), required)
    assert "Here are 2 ways to get money before you run out on Mon, Nov 9" in quick
    assert "Work an extra shift by Sat, Oct 31: it adds $57.35 on Tue, Nov 3" in quick
    assert "your $1,850 refund arrives around Thu, Nov 5" in quick
    assert quick.index("Sat, Oct 31") < quick.index("Thu, Nov 5")               # ranked by when the money arrives


def test_spending_and_bills_validate_dates():
    with pytest.raises(ValueError, match="past transactions"):
        agent.validate_call("spending_summary", {"start": "2026-11-01"}, SUBS)
    assert agent.validate_call("upcoming_bills", {"start": "2026-10-26", "end": "2026-11-02"}, SUBS)[0]["start"] == \
        "2026-10-27"                                                              # "from today": bills start tomorrow
    with pytest.raises(ValueError, match="outside"):
        agent.validate_call("upcoming_bills", {"start": "2027-01-10"}, SUBS)
    with pytest.raises(ValueError, match="needs a query"):
        agent.validate_call("find_transactions", {}, SUBS)
    assert agent.validate_call("upcoming_bills", {}, SUBS)[0] == {"start": "2026-10-27", "end": "2026-11-02"}


# --- multi-step plans ---------------------------------------------------------------------------------------

def test_multi_step_plan_one_plan_call_one_merged_pack(ds):
    calls = [{"tool": "runway"}, {"tool": "money_ideas"}, {"tool": "find_leaks"}]
    wrong = "ANSWER: You'd have $412.50 left [C4].\nWHY:\n- It works out [C1].\nDO THIS:\n1. Relax."
    llm = FakeLLM(plans=[plan_json(calls, "Help me get through the semester")], answers=[wrong, wrong])
    events, a = run_all("Help me get through the semester", llm, ds)
    assert [c[0] for c in llm.calls].count("plan") == 1                           # still ONE plan call
    assert [c["tool"] for c in a.plan["calls"]] == ["runway", "money_ideas", "find_leaks"]
    ids = [it["id"] for it in a.pack["items"]]
    assert len(ids) == len(set(ids))                                              # one numbering across calls
    keys = {f["key"] for f in a.facts}
    assert {"runs_out", "cause", "deadline", "idea_shift", "idea_refund", "monthly_total", "fee"} <= keys
    assert a.text == a.quick and a.check["ok"]                                    # the AI failed: quick stays
    assert "Your money runs out on Mon, Nov 9" in a.text and "$57.35" in a.text and "$22.98" in a.text


def test_broad_request_is_widened_when_plan_picks_one_tool(ds):
    """Seen live: Lightning answered "Help me get through the semester" with runway alone."""
    llm = FakeLLM(plans=[plan_json([{"tool": "runway"}])], answers=["x", "x"])
    _, a = run_all("Help me get through the semester", llm, ds)
    assert [c["tool"] for c in a.plan["calls"]] == ["runway", "money_ideas", "find_leaks"]
    p = agent.parse_plan({"calls": [{"tool": "runway"}]}, SUBS)
    assert len(agent.widen_broad_plan(p, "How long will my money last?").calls) == 1      # specific: unchanged
    off = agent.parse_plan({"intent": "off_topic", "calls": []}, SUBS)     # seen live: Lightning called it off-topic
    off = agent.widen_broad_plan(off, "Help me get through the semester")
    assert [c["tool"] for c in off.calls] == list(agent.BROAD_CALLS) and off.tool == "runway"
    off = agent.parse_plan({"intent": "off_topic", "calls": []}, SUBS)
    assert agent.widen_broad_plan(off, "What's the capital of France?").tool is None     # off-topic stays off-topic


def test_parse_plan_limits_calls():
    with pytest.raises(ValueError, match="at most 3"):
        agent.parse_plan({"calls": [{"tool": "runway"}] * 2 + [{"tool": "find_leaks"}, {"tool": "money_ideas"}]},
                         SUBS)
    p = agent.parse_plan({"calls": [{"tool": "runway"}, {"tool": "runway"}]}, SUBS)
    assert len(p.calls) == 1                                                       # duplicates dropped


# --- follow-ups -------------------------------------------------------------------------------------------

def test_follow_up_gets_history_and_resolves(ds):
    first = RecordingLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT])
    _, a1 = run_all(FLIGHT_Q, first, ds)
    resolved = "Can I afford the $400 flight home if I book it Nov 17?"
    follow = RecordingLLM(plans=[plan_json([{"tool": "can_afford", "args": {"item": "flight home", "cost": 400,
                                                                            "date": "2026-11-17"}}], resolved)],
                          answers=["bad", "bad"])
    _, a2 = run_all("what about Nov 17 instead?", follow, ds, history=[a1])
    system = follow.plan_messages[0][0]["content"]
    assert "Recent conversation" in system and FLIGHT_Q in system                 # the earlier turn reached PLAN
    assert "Runway answered: Yes, if you do 2 things first" in system
    assert a2.plan["resolved_question"] == resolved and a2.plan["args"]["date"] == "2026-11-17"
    assert agent.cache_path("what about Nov 17 instead?", engine.Scenario(), history=[a1]) != \
        agent.cache_path("what about Nov 17 instead?", engine.Scenario())        # follow-ups cache separately


def test_follow_up_date_isnt_reset_to_tomorrow(ds):
    """"what about Nov 17 instead?" has a date in the question; "and if I buy it later?" relies on the resolved one."""
    plan = agent.parse_plan(json.loads(plan_json([{"tool": "can_afford", "args": {"item": "flight", "cost": 400,
                                                                                  "date": "2026-11-17"}}],
                                                 "Can I afford the flight on Nov 17?")), SUBS)
    grounded = agent.ground_purchase_date(plan, "and that one? Can I afford the flight on Nov 17?")
    assert grounded.args["date"] == "2026-11-17" and not grounded.assumptions


# --- quick answer, then the AI answer -----------------------------------------------------------------------

def test_quick_answer_comes_first_then_the_ai_answer_replaces_it(ds):
    events, a = run_all(FLIGHT_Q, FakeLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT]), ds)
    kinds = [k for k, _ in events]
    assert kinds.index("quick") < kinds.index("text")                            # instant answer before the AI streams
    assert a.quick.startswith("ANSWER: Yes, if you do 2 things first")
    assert a.text == GOOD_FLIGHT and a.explain_source == "llm"
    assert a.timings["quick_s"] <= a.timings["total_s"]


# --- fast vs Think harder ------------------------------------------------------------------------------------

def test_fast_mode_uses_lightning_without_thinking(ds, monkeypatch):
    monkeypatch.setattr(config, "NVIDIA_EXPLAIN_MODEL", "super")
    monkeypatch.setattr(config, "NVIDIA_PLAN_MODEL", "lightning")
    llm = FakeLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT])
    _, a = run_all(FLIGHT_Q, llm, ds)
    assert llm.calls == [("plan", False), ("explain", False)] and llm.messages[0][0] == "lightning"
    assert a.models["answered_by"] == "lightning" and not a.think


def test_think_harder_uses_super_with_thinking(ds, monkeypatch):
    monkeypatch.setattr(config, "NVIDIA_EXPLAIN_MODEL", "super")
    monkeypatch.setattr(config, "NVIDIA_PLAN_MODEL", "lightning")
    llm = FakeLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT])
    _, a = run_all(FLIGHT_Q, llm, ds, think=True)
    assert llm.calls == [("plan", False), ("explain", True)] and llm.messages[0][0] == "super"
    assert a.models["answered_by"] == "super" and a.think and a.reasoning


def test_fast_mode_falls_back_to_super_without_thinking(ds, monkeypatch):
    monkeypatch.setattr(config, "NVIDIA_EXPLAIN_MODEL", "super")
    monkeypatch.setattr(config, "NVIDIA_PLAN_MODEL", "lightning")
    llm = FakeLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT], explain_error=TimeoutError(),
                  failing_models={"lightning"})
    _, a = run_all(FLIGHT_Q, llm, ds)
    assert [m for m, _ in llm.messages] == ["lightning", "super"] and llm.calls[-1] == ("explain", False)
    assert a.models["answered_by"] == "super" and "Nemotron Lightning wasn't available" in a.notes[0]


# --- general info ---------------------------------------------------------------------------------------------

GENERAL_PLAN = plan_json([{"tool": "general_info", "args": {"topic": "FAFSA verification"}}],
                         "What is FAFSA verification?")
GENERAL_GOOD = ("ANSWER: FAFSA verification is when your school checks the facts on your aid form.\nWHY:\n"
                "- Some students are picked to confirm their income and household.\n"
                "- Your aid can wait until it is done.\nDO THIS:\n1. Send what your financial aid office asks for.")


def test_general_info_answers_without_her_numbers(ds):
    leaky = GENERAL_GOOD.replace("Your aid can wait until it is done.", "Your $1,850 refund waits until it is done.")
    llm = FakeLLM(plans=[GENERAL_PLAN], answers=[leaky, GENERAL_GOOD])
    events, a = run_all("What is FAFSA verification?", llm, ds)
    assert "quick" not in [k for k, _ in events]                                  # no numbers of hers to show
    assert a.text == GENERAL_GOOD and a.check["ok"] and a.retries["explain_rewrite"] == 1
    system = llm.messages[0][1][0]["content"]
    assert "GENERAL money question" in system and "[C" not in llm.messages[0][1][1]["content"]   # no facts sent


def test_general_info_rules():
    pack = agent.Pack([], [], {})
    private = {agent.Decimal("1850.00"), agent.Decimal("783.38")}
    bad = agent.check_answer("ANSWER: You have $783 today.\nWHY:\n- It is yours.", pack, True, general=True,
                             private=private)
    assert any("student's own numbers" in p for p in bad.problems)
    ok = agent.check_answer(GENERAL_GOOD, pack, True, general=True, private=private)
    assert ok.ok, ok.problems                                                     # no citations needed
    rep = agent.check_answer(GENERAL_GOOD + "\n2. Send what your financial aid office asks for.", pack, True,
                             general=True, private=private)
    assert any("repeats" in p for p in rep.problems)                              # repetition still applies
    cut = agent.check_answer("ANSWER: FAFSA verification is when your school\nWHY:\n- Some students are", pack,
                             True, general=True, private=private)
    assert any("mid-sentence" in p for p in cut.problems)                         # cut-off still applies


# --- smarter checks: the real failures seen in the regenerated answers and the live app ------------------------

def _leaks(ds, scenario):
    plan = agent.parse_plan({"intent": "leaks", "tool": "find_leaks", "args": {}}, SUBS)
    r = agent.execute(plan, scenario, ds)
    return agent.build_pack(r, ds, plan, scenario)


def test_check_catches_the_invented_spotify_on_credit_card_reason(ds):
    pack = _leaks(ds, engine.Scenario(refund_released=True, cancel_subscriptions=("Spotify",)))
    real = ("ANSWER: Rent caused a $35.00 overdraft fee on Thu, Oct 1 [C1].\nWHY:\n- Rent was $725.00 on Thu, Oct 1 "
            "[C3].\nDO THIS:\n1. Keep rent money in checking before the 1st [C5].\nNOTE: Cancelling Spotify saves "
            "$0.00 because its charges go on the credit card, and that bill is paid after the semester ends.")
    check = agent.check_answer(real, pack, True, names=agent.merchant_accounts(ds))
    assert "Spotify is not charged to the credit card (it charges checking)" in check.problems
    assert any("saves $0.00" in p and "Spotify" in p for p in check.problems)    # no such saving in the facts


def test_check_accepts_true_account_claims_and_catches_wrong_savings(ds):
    pack = _leaks(ds, engine.Scenario())
    names = agent.merchant_accounts(ds)
    good = ("ANSWER: Two music apps and a fee are leaking money.\nWHY:\n- You pay for Apple Music and Spotify: "
            "$22.98 a month together [C3].\nDO THIS:\n1. Cancel Spotify to save $23.98 by Fri, Dec 18 [C7].\nNOTE: "
            "Apple Music is billed to your credit card, and that card bill is paid after the semester ends [C6].")
    assert agent.check_answer(good, pack, True, names=names).ok
    wrong = good.replace("save $23.98", "save $11.99")
    assert any("doesn't match its computed saving" in p for p in agent.check_answer(wrong, pack, True,
                                                                                    names=names).problems)
    invented = good.replace("NOTE: Apple Music", "NOTE: Netflix and Apple Music").replace("Apple Music and Spotify",
                                                                                          "Uber and Spotify")
    assert "Uber is not in the facts" in agent.check_answer(invented, pack, True, names=names).problems


def test_check_catches_the_cut_off_answer(ds):
    pack = _leaks(ds, engine.Scenario())
    cut = ("ANSWER: Your money leaks from music subscriptions and a rent overdraft fee.\nWHY:\n- You pay for Apple "
           "Music [C3].\n- You pay for Spotify [C3].\n- Together they cost $22.98 a month [C3].\n- Rent caused a $35 "
           "overdraft fee on Thu, Oct 1 [C9].\nDO THIS:\n1. Cancel Spotify to save")
    assert "the answer stops mid-sentence" in agent.check_answer(cut, pack, True).problems
    full = cut.replace("1. Cancel Spotify to save", "1. Cancel Spotify.")
    assert agent.check_answer(full, pack, True).ok
    assert any("cut off" in p for p in agent.check_answer(full, pack, True, finish_reason="length").problems)


def test_check_catches_the_five_times_repeated_shift_bullet():
    text = ("ANSWER: Work a shift by Sat, Oct 31 to get paid Tue, Nov 3.\nWHY:\n"
            + "- The extra shift adds $143 to your Wed, Nov 18 paycheck.\n" * 5
            + "- A shift worked by Sat, Oct 31 is paid Tue, Nov 3.\n- Your money runs out on Mon, Nov 9.\n"
              "DO THIS:\n1. Work a shift by Sat, Oct 31.")
    assert agent.repetition_problems(text) == [
        'the answer repeats itself ("The extra shift adds $143 to your Wed, Nov 18 paycheck.")']
    near = ("ANSWER: You can afford it.\nWHY:\n- Your lowest point is $5.81 on Mon, Nov 2.\n"
            "- Your lowest point is $5.81 on Mon, Nov 2!")
    assert agent.repetition_problems(near)                                        # near-identical counts too


def test_check_catches_the_wrong_date_for_an_event(ds):
    """Seen in a regenerated answer: "Watch your balance before rent on Mon, Nov 9" (rent is due on the 1st;
    Nov 9 is the card payment)."""
    pack = _leaks(ds, engine.Scenario())
    events = agent.event_dates(ds, engine.Scenario())
    bad = ("ANSWER: Your money leaks from two music apps and a fee.\nWHY:\n- Rent caused a $35 overdraft fee [C9].\n"
           "DO THIS:\n1. Watch your balance before rent on Mon, Nov 9 [C15].")
    assert "Mon, Nov 9 is not a rent date" in agent.check_answer(bad, pack, True, events=events).problems
    ok = ("ANSWER: Two dates matter.\nWHY:\n- Rent of $725 is due Sun, Nov 1 and the card payment on Mon, Nov 9.\n"
          "- Your refund arrives around Thu, Nov 5. Send the refund form by Tue, Oct 27.")
    assert agent.event_date_problems(ok, events) == []
    # seen live: "Wait for your next paycheck after Nov 20" - the date belongs to the tuition payment
    assert agent.event_date_problems("Wait for your next paycheck after Fri, Nov 20 [E3].", events) == []
    assert agent.event_date_problems("Your next paycheck is on Fri, Nov 20.", events) == [
        "Fri, Nov 20 is not a paycheck date"]


def test_card_subscription_reaching_checking_via_the_card_bill_is_not_a_false_claim(ds):
    names = agent.merchant_accounts(ds)
    pack = _leaks(ds, engine.Scenario())
    true_claim = ("ANSWER: Apple Music won't help this semester.\nWHY:\n- Apple Music hits checking only when the card "
                  "bill is paid, after the semester [C6].")
    assert not any("does not charge checking" in p for p in agent.reason_problems(true_claim, pack, names))
    false_claim = "ANSWER: x.\nWHY:\n- Apple Music charges your checking every month [C6]."
    assert "Apple Music does not charge checking (it is billed to the credit card)" in \
        agent.reason_problems(false_claim, pack, names)


def test_check_catches_a_copied_fact_label(ds):
    """Seen in a regenerated answer: "the duplicate subscription Apple Music: You pay for Apple Music [C3]."."""
    plan, results, pack, required = _pieces([{"tool": "find_leaks", "args": {}}], ds)
    text = ("ANSWER: Your money leaks from music subscriptions.\nWHY:\n- the duplicate subscription Apple Music: You "
            "pay for Apple Music [C3].\nDO THIS:\n1. Cancel Spotify.")
    assert agent.copied_label_problems(text, required) == [
        'the answer copied an instruction: "the duplicate subscription Apple Music:"']
    assert required[0].prompt().endswith(': "You pay for Apple Music [C3]."')       # the sentence is quoted


def test_check_catches_a_copied_placement_hint():
    """Seen live: the model copied the required-fact line with its hint, "...on Mon, Nov 2. (as a WHY bullet)"."""
    text = ("ANSWER: Yes, if you do 2 things.\nWHY:\n- Your lowest point would be $5.81 on Mon, Nov 2. "
            "(as a WHY bullet)\nDO THIS:\n1. Send the form.")
    assert agent.copied_hint_problems(text) == ["the answer copied an instruction: (as a WHY bullet)"]
    fact = agent.Fact("lowest", "the lowest point", "Your lowest point would be $5.81 on Mon, Nov 2.", where="why")
    assert fact.prompt() == '- the lowest point (as a WHY bullet): "Your lowest point would be $5.81 on Mon, Nov 2."'


def test_check_catches_invented_budgets():
    assert agent.invented_budget_problems("ANSWER: x.\nWHY:\n- y.\nDO THIS:\n1. Set a $200 School budget for October.")
    assert not agent.invented_budget_problems("ANSWER: x.\nWHY:\n- y.\nDO THIS:\n1. Keep $360 for the card payment.")


def test_failed_checks_trigger_the_one_rewrite(ds):
    plan = plan_json([{"tool": "money_ideas"}])
    repeated = ("ANSWER: Work an extra shift by Sat, Oct 31 [C2].\nWHY:\n"
                + "- Work an extra shift by Sat, Oct 31: it adds $57.35 on Tue, Nov 3 [C2].\n" * 3)
    llm = FakeLLM(plans=[plan], answers=[repeated, repeated])
    _, a = run_all("What can I do to make money before this?", llm, ds)
    assert a.retries["explain_rewrite"] == 1 and len(llm.messages) == 2
    assert "repeats itself" in llm.messages[1][1][-1]["content"]                  # the rewrite request names it
    assert a.text == a.quick                                                      # still failing: quick answer


# --- proof evidence comes from the dataset loaded now -----------------------------------------------------------

def test_proof_details_use_the_current_backend():
    from ui import ask
    src = {"query": "checking_transactions", "backend": "local", "duration_s": 0.001, "sql": "SELECT local"}
    now = SimpleNamespace(evidence=[SimpleNamespace(query="checking_transactions", backend="zetaris-cached",
                                                    duration_s=0.01, original_duration_s=3.2, sql="SELECT zetaris")])
    ev = ask._current_evidence(src, now)
    assert ev.backend == "zetaris-cached" and ev.sql == "SELECT zetaris"
    assert ask._current_evidence(src, SimpleNamespace(evidence=[])) is None      # falls back to the recorded one
