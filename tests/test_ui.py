"""ui/app.py through Streamlit's AppTest, local backend, no network, no LLM.

Screens show rounded headline money ("$1,850"), "below zero" instead of minus signs, and dates like
"Mon, Nov 9"; the tests check that wording and the exact engine values behind it."""
import html
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import config


@pytest.fixture
def at(monkeypatch):
    monkeypatch.setattr(config, "DATA_BACKEND", "local")
    app = AppTest.from_file("../ui/app.py", default_timeout=60)
    app.run()
    app.button(key="chat_fab_btn").click()            # the chat lives in the panel behind the floating button
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def plain(s):
    return html.unescape(s).replace("\\$", "$")


def texts(at):
    return [plain(m.value) for m in at.markdown] + [plain(c.value) for c in at.caption]


def status(at):
    return next(t for t in texts(at) if 'class="rw-status' in t)


def verdict(at):
    return next((t for t in texts(at) if 'class="rw-answer' in t), "")


def figures(at):
    return [t for t in texts(at) if 'class="rw-fig"' in t]


def run(at):
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def visible(at):
    """Everything outside "Behind the scenes" and the CSS."""
    behind = next(e for e in at.expander if e.label == "Behind the scenes")
    hidden = {plain(m.value) for m in behind.markdown} | {plain(c.value) for c in behind.caption}
    return [t for t in texts(at) if t not in hidden and not t.startswith("<style>")]


# --- status card, big number, fix cards ---------------------------------------------------------

def test_base_status_and_fix_cards(at):
    s = status(at)
    assert ">Your money runs out in 2 weeks, on Mon, Nov 9.<" in s                  # first_below_zero Nov 9
    assert ">A $360 card payment is due that day. You'll only have $307.<" in s    # $359.53, $307.20
    assert not at.chat_input[0].disabled
    assert [b.label for b in at.button if str(b.key).startswith("ask_suggest_")][3:] == \
        ["Can I afford a $400 flight home for Thanksgiving?", "What should I do this week?"]
    assert [t.label for t in at.toggle if t.key != "ask_think"][:2] == [
        "**Send the verification form**", "**Cancel Spotify**"]
    assert "wf_shift_on" not in at.session_state                     # the single shift card became the planner
    body = "\n".join(texts(at))
    assert "Releases your $1,850 refund around Thu, Nov 5." in body
    assert "Saves $23.98 this semester." in body
    why = next(e for e in at.expander if e.label == "Cancelling Apple Music won't help this semester. Why?")
    text = plain(why.markdown[0].value)
    assert "Thu, Jan 7, 2027" in text and "saves $0.00 this semester" in text


def test_big_number_and_figures(at):
    t = texts(at)
    assert any('class="rw-today">$783<' in x and "in your checking account today" in x for x in t)   # $783.38
    low, end = figures(at)
    assert "Lowest point" in low and 'rw-red">$1,462 below zero<' in low and "Thu, Dec 17" in low   # -$1,462.37
    assert "End of semester" in end and "$1,413 below zero" in end and "Fri, Dec 18" in end      # -$1,412.53
    assert "rw-delta" not in low
    at.toggle(key="wf_refund").set_value(True)
    run(at)
    low, end = figures(at)
    assert 'rw-green">$5.81 <span class="rw-delta rw-up">+$1,468<' in low and "Mon, Nov 2" in low   # +$1,468.18
    assert ">$437 <" in end and "+$1,850" in end                                                  # $437.47


def test_no_bare_negative_balances_or_jargon_on_screen(at):
    shown = visible(at)
    for t in shown:
        assert "-$" not in t, t
    for word in ("scenario", "Computed", "evidence", "row ID", "backend", "ledger", "projection", "delta"):
        assert not any(word in t.replace("rw-delta", "") for t in shown), word


def test_start_over_resets(at):
    at.toggle(key="wf_refund").set_value(True)
    at.toggle(key="wf_cancel_Spotify").set_value(True)
    at.button(key="buy_check").click()
    run(at)
    assert ">You're covered all semester.<" in status(at)
    at.button(key="start_over").click()
    run(at)
    assert "Your money runs out in 2 weeks, on Mon, Nov 9." in status(at)
    assert not at.toggle(key="wf_refund").value and not at.session_state["buy_active"]


# --- Can I afford it? ---------------------------------------------------------------------------

def test_flight_yes_if_two_things_then_do_these(at):
    at.button(key="buy_check").click()
    run(at)
    assert ">Yes, if you do 2 things first<" in verdict(at)
    body = "\n".join(texts(at))
    assert "1. Send your verification form. Your $1,850 refund comes around Thu, Nov 5." in body
    assert "2. Cancel Spotify. That saves $23.98 this semester." in body
    assert "With both, your lowest point would be $5.81 on Mon, Nov 2." in body
    at.button(key="buy_do").click()
    run(at)
    assert at.toggle(key="wf_refund").value and at.toggle(key="wf_cancel_Spotify").value
    assert not at.session_state["wf_cancel_Apple Music"]
    assert ">You can afford it.<" in verdict(at)
    assert "Your lowest point would be $5.81 on Mon, Nov 2. That's cutting it close." in "\n".join(texts(at))
    assert 'rw-green">$5.81' in figures(at)[0]                                         # exact $5.81 kept


# --- What we found ------------------------------------------------------------------------------

def test_found_cards_and_proof(at):
    body = "\n".join(texts(at))
    for title, sentence in [("Your $1,850 refund is on hold", "Financial aid needs your verification form first."),
                            ("You pay for 2 music apps", "That's $22.98 a month for Spotify and Apple Music."),
                            ("Rent caused a $35 overdraft fee", "Rent is due the 1st. Your paycheck came Fri, Oct 2."),
                            ("Money is tight the week of Nov 16",
                             "A $200 tuition payment is due right after a small paycheck.")]:
        assert f'rw-card-title">{title}<' in body and sentence in body, title      # the shared card style
    assert "(estimated)" in body
    proof = [e for e in at.expander if e.label == "Show proof"]
    assert len(proof) == 4
    fee_proof = proof[2]                         # cards: refund, music apps, fee, tight week
    assert "Your checking account" in fee_proof.dataframe[0].value["Where"].tolist()
    how = plain(fee_proof.markdown[1].value)
    assert "- You had $718.08 the night before rent." in how and "- Rent took you to $6.92 below zero." in how


# --- Ask Runway (mocked models) -----------------------------------------------------------------

@pytest.fixture
def asked(at, monkeypatch, tmp_path):
    import llm_client
    from test_agent import FLIGHT_PLAN, GOOD_FLIGHT, FakeLLM

    fake = FakeLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT])
    monkeypatch.setattr(llm_client, "chat_json", fake.chat_json)
    monkeypatch.setattr(llm_client, "stream_chat", fake.stream_chat)
    monkeypatch.setattr(config, "ANSWER_MODE", "live")
    monkeypatch.setattr(config, "ANSWER_CACHE_DIR", tmp_path / "answers")
    monkeypatch.setattr(config, "NVIDIA_API_KEY", "test-key")        # the fake client stands in; no .env needed
    at.button(key="ask_suggest_0").click()
    run(at)
    return at


def _fake_models(monkeypatch, tmp_path, plans, answers):
    import llm_client
    from test_chat import RecordingLLM

    fake = RecordingLLM(plans=plans, answers=answers)
    monkeypatch.setattr(llm_client, "chat_json", fake.chat_json)
    monkeypatch.setattr(llm_client, "stream_chat", fake.stream_chat)
    monkeypatch.setattr(config, "ANSWER_MODE", "live")
    monkeypatch.setattr(config, "ANSWER_CACHE_DIR", tmp_path / "answers")
    monkeypatch.setattr(config, "NVIDIA_API_KEY", "test-key")
    return fake


def test_chat_thread_follow_up_and_new_chat(at, monkeypatch, tmp_path):
    import json

    from test_agent import FLIGHT_PLAN, GOOD_FLIGHT
    resolved = "Can I afford the $400 flight home if I book it Nov 17?"
    follow = json.dumps({"resolved_question": resolved, "calls": [{"tool": "can_afford", "args": {
        "item": "flight home", "cost": 400, "date": "2026-11-17"}}]})
    fake = _fake_models(monkeypatch, tmp_path, [FLIGHT_PLAN, follow], [GOOD_FLIGHT, GOOD_FLIGHT])
    at.button(key="ask_suggest_0").click()
    run(at)
    assert [m.name for m in at.chat_message] == ["user", "assistant"]
    assert not [b for b in at.button if str(b.key).startswith("ask_suggest_")]   # chips only in an empty thread
    at.chat_input(key="ask_input").set_value("what about Nov 17 instead?")
    run(at)
    assert [m.name for m in at.chat_message] == ["user", "assistant", "user", "assistant"]   # newest at the bottom
    assert f"Answering: {resolved}" in [plain(c.value) for c in at.chat_message[2].caption]
    assert "Recent conversation" in fake.plan_messages[1][0]["content"]              # the earlier turn reached PLAN
    history = at.session_state["history"]
    assert [a.question for a in history] == ["what about Nov 17 instead?", agent_suggested(0)]
    assert history[0].plan["args"]["date"] == "2026-11-17"
    at.button(key="ask_new").click()
    run(at)
    assert not at.chat_message and at.session_state["history"] == []
    assert len([b for b in at.button if str(b.key).startswith("ask_suggest_")]) == 5


def test_think_harder_toggle_routes_to_super_with_thinking(at, monkeypatch, tmp_path):
    from test_agent import FLIGHT_PLAN, GOOD_FLIGHT
    fake = _fake_models(monkeypatch, tmp_path, [FLIGHT_PLAN], [GOOD_FLIGHT])
    monkeypatch.setattr(config, "NVIDIA_EXPLAIN_MODEL", "super")
    monkeypatch.setattr(config, "THINK_MODEL", "super")
    at.toggle(key="ask_think").set_value(True)
    run(at)
    at.button(key="ask_suggest_0").click()
    run(at)
    assert fake.calls[-1] == ("explain", True) and fake.messages[-1][0] == "super"
    a = at.session_state["history"][0]
    assert a.think and any("Think harder: Nemotron Super, thinking on" in plain(m.value) for m in at.markdown)


def agent_suggested(i):
    import agent
    return agent.SUGGESTED[i]


def test_ask_flight_question_shows_structured_answer(asked):
    at = asked
    t = texts(at)
    ans = next(x for x in t if 'class="rw-ans"' in x)
    assert ans.startswith('<div class="rw-ans">Yes, if you do 2 things first<sup class="rw-fn">1</sup>.</div>')
    assert "<li>Without changes, you'd be $1,862 below zero<sup" in ans          # WHY bullets
    assert "[C" not in ans                                                       # citations became footnotes
    steps = next(x for x in t if 'class="rw-do-list"' in x)
    assert "<li>Send your verification form. Your $1,850 refund comes around Thu, Nov 5" in steps
    assert any('class="rw-note"' in x and "Apple Music saves $0.00" in x for x in t)
    proof = at.pills(key=next(k for k in at.session_state if str(k).startswith("proof_")))
    assert len(proof.options) >= 5
    proof.set_value(proof.options[3])                                            # the refund calculation
    run(at)
    assert any("Thu Nov 5" in x or "Thu, Nov 5" in x for x in texts(at))
    assert any("Draft email to Office of Student Financial Aid" in x for x in texts(at))
    do = next(b for b in at.button if str(b.key).startswith("ans_do_"))
    do.click()
    run(at)
    assert at.toggle(key="wf_refund").value and at.toggle(key="wf_cancel_Spotify").value
    assert not at.session_state["wf_cancel_Apple Music"]
    assert 'rw-green">$5.81' in figures(at)[0]
    assert at.session_state["history"][0].text == "Done. Your forecast is updated."      # said in the panel
    assert at.session_state["history"][1].mode == "live" and at.session_state["history"][1].sections


def test_how_runway_thought_shows_the_plan_json(asked):
    at = asked
    key = next(k for k in at.session_state if str(k).startswith("nerd_plan_"))
    at.toggle(key=key).set_value(True)
    run(at)
    plan = next(c.value for c in at.code if c.language == "json")
    assert '"tool": "can_afford"' in plan and '"date": "2026-11-10"' in plan
    assert any("The plan Nemotron wrote" in plain(c.value) for c in at.caption)


def test_streaming_answer_is_laid_out_like_the_finished_one():
    import agent
    from ui import ask
    assert agent.parse_sections("ANSWER: Yes, if you do 2 ▌") is None                 # a finished answer needs WHY
    sec = agent.parse_sections("ANSWER: Yes, if you do 2 things [C1].\nWHY:\n- Without ▌", partial=True)
    html = ask.sections_html(sec, {})
    assert html.startswith('<div class="rw-ans">Yes, if you do 2 things.</div>') and "<li>Without ▌</li>" in html
    assert "ANSWER:" not in html and "[C1]" not in html


def test_judge_setup_no_key_replay_mode(monkeypatch):
    """A fresh clone: no NVIDIA key, local data, replay mode. The committed demo answers serve every suggested
    question (with nothing changed and with both fixes on); a typed question gets a friendly message."""
    import functools

    import agent
    monkeypatch.setattr(config, "DATA_BACKEND", "local")
    monkeypatch.setattr(config, "ANSWER_MODE", "replay")
    monkeypatch.setattr(config, "NVIDIA_API_KEY", None)
    monkeypatch.setattr(agent, "run", functools.partial(agent.run, typing_s=0))     # no typing delay
    at = AppTest.from_file("../ui/app.py", default_timeout=60)
    at.run()
    at.button(key="chat_fab_btn").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    for fixes in (False, True):
        if fixes:
            at.toggle(key="wf_refund").set_value(True)
            at.toggle(key="wf_cancel_Spotify").set_value(True)
            run(at)
            at.button(key="ask_new").click()          # the panel said "Done. Your forecast is updated.": clear it
            run(at)
        for i in range(5):                                # all 5 suggested questions have saved answers
            at.button(key=f"ask_suggest_{i}").click()
            run(at)
            a = at.session_state["history"][0]
            assert a.mode == "replay" and a.text.startswith("ANSWER:"), (fixes, a.question, a.mode)
            at.button(key="ask_new").click()                     # suggested questions show in an empty thread
            run(at)
    at.chat_input(key="ask_input").set_value("Can I afford a $90 jacket?")
    run(at)
    a = at.session_state["history"][0]
    assert a.mode == "no_key" and a.text.startswith("Live answers need Meterless Nightshift (or an NVIDIA key).")
    assert any("Live answers need Meterless Nightshift (or an NVIDIA key)." in t for t in texts(at))
    assert not at.exception


# --- Behind the scenes --------------------------------------------------------------------------

def test_behind_the_scenes_drills_into_records(at):
    records = at.selectbox(key="explain_record")
    lowest = next(o for o in records.options if "lowest checking balance" in o)
    records.set_value(lowest.split(":")[0])
    run(at)
    pills = at.pills(key="explain_input")
    assert "C1" in pills.options
    pills.set_value("C1")
    run(at)
    assert at.selectbox(key="explain_record").value == "C1"
    at.pills(key="explain_input").set_value("ACCT-CHK-01")
    run(at)
    assert any("checking/account.csv" in c.value for c in at.code)


# --- chart: see tests/test_chart.py -----------------------------------------------------------


# --- the check-in ----------------------------------------------------------------------------------------

def checkin_texts(at):
    return [t for t in texts(at) if 'class="rw-ci-' in t and not t.startswith("<style>")]


def test_checkin_under_the_status_card(at):
    ts = checkin_texts(at)
    assert any(">Hi Maya. 6 things need your attention.<" in t for t in ts)        # run-out: the status card
    assert any(">Start with the first one. It's the most urgent.<" in t for t in ts)        # the fixed line
    cards = [t for t in ts if 'class="rw-ci-title"' in t]
    assert [c.split('rw-ci-title">')[1].split("<")[0] for c in cards] == [
        "Send your verification form", "Rent is due Sun, Nov 1",
        "You may qualify for a $500 emergency grant", "A tight week is coming", "You pay for 2 music apps",
        "Your dining dollars run out around Sun, Nov 22"]
    see_all = next(e for e in at.expander if e.label.startswith("See all"))
    assert see_all.label == "See all (3 more)"
    order = [t for t in texts(at) if 'class="rw-status' in t or 'class="rw-ci-head' in t]
    assert "rw-status" in order[0] and "rw-ci-head" in order[1]                               # right under it


def test_mark_done_updates_forecast_checkin_and_chat_then_undo(at):
    assert len([b for b in at.button if str(b.key).startswith("ci_done_") and "bud" not in str(b.key)]) == 6
    at.button(key="ci_done_refund").click()
    run(at)
    assert ">You're covered all semester.<" in status(at)                                 # the form counts as sent today
    assert any(">Hi Maya. 4 things need your attention.<" in t for t in checkin_texts(at))
    titles = [t.split('rw-ci-title">')[1].split("<")[0] for t in checkin_texts(at) if 'class="rw-ci-title"' in t]
    assert titles == ["Rent is due Sun, Nov 1", "A tight week is coming", "You pay for 2 music apps",
                      "Your dining dollars run out around Sun, Nov 22"]           # no gap now: no grant
    said = [plain(m.value) for m in at.chat_message[0].markdown]
    assert said == ["Nice. With the form sent, your refund should arrive around Wed, Nov 4. Your money now lasts "
                    "all semester. Your lowest point is $5.81 on Mon, Nov 2."]
    assert at.toggle(key="wf_refund").value is True and at.toggle(key="wf_refund").disabled
    log = at.session_state["action_log"]
    assert [x["kind"] for x in log].count("prepared") >= 4 and log[-1]["kind"] == "done"
    assert log[-1]["what"] == "Marked done: Form sent (Send your verification form)"
    at.button(key="ci_undo_refund").click()
    run(at)
    assert ">Your money runs out in 2 weeks, on Mon, Nov 9.<" in status(at)
    assert any(">Hi Maya. 6 things need your attention.<" in t for t in checkin_texts(at))
    assert at.toggle(key="wf_refund").value is False and not at.toggle(key="wf_refund").disabled
    assert at.session_state["action_log"][-1]["kind"] == "undone"


def test_cancel_spotify_done_and_all_caught_up(at):
    for key in ("ci_done_refund", "ci_done_rent", "ci_done_tight_week", "ci_done_subscriptions",
                "ci_done_meal_plan"):
        at.button(key=key).click()
        run(at)
    assert any(">Hi Maya. You're all caught up.<" in t for t in checkin_texts(at))
    assert at.session_state[f"wf_cancel_Spotify"] is True
    said = [plain(m.markdown[0].value) for m in at.chat_message]
    assert any("Nice. With Spotify cancelled, you keep $23.98 this semester." in x for x in said)
    assert said[-1].endswith("You're all caught up.")
    assert not [b for b in at.button if str(b.key) == "ci_cal_all"]                        # nothing left to remind


def test_what_should_i_do_this_week_shows_the_same_buttons(at, monkeypatch, tmp_path):
    import json
    plan = json.dumps({"calls": [{"tool": "action_plan", "args": {"start": "2026-10-26", "end": "2026-11-01"}}]})
    _fake_models(monkeypatch, tmp_path, [plan], ["x", "x"])                 # bad AI answer: the quick answer stays
    at.chat_input(key="ask_input").set_value("What should I do this week?")
    run(at)
    a = at.session_state["history"][0]
    assert a.actions == [{"id": "attention", "kind": "attention", "title": "What to do", "to": "", "subject": "",
                          "body": "", "items": ["refund", "rent"]}]
    chat_keys = [str(b.key) for b in at.button if str(b.key).startswith("ci_done_chat")]
    assert len(chat_keys) == 2 and chat_keys[0].endswith("_refund")
    at.button(key=chat_keys[0]).click()                                   # "Form sent" from the chat answer
    run(at)
    assert ">You're covered all semester.<" in status(at)
    assert "refund" in at.session_state["done"]


# --- the Budget tab --------------------------------------------------------------------------------------------

def budget_texts(at):
    return [t for t in texts(at) if ('class="rw-bud' in t) and not t.startswith("<style>")]


def test_budget_tab_spending_view(at):
    assert [t.label for t in at.tabs] == ["Semester", "Budget", "Afford it?", "Find money", "Findings"]
    line = next(t for t in budget_texts(at) if "rw-bud-line" in t)
    assert ">So far in October, you spent $1,757. Most went to Rent ($725) and Shopping ($461).<" in line
    table = next(t for t in budget_texts(at) if "rw-bud-table" in t)
    names = [r.split("</span>")[1].split("<")[0] for r in table.split("<tr>")[2:]]
    assert names == ["Rent", "Shopping", "School", "Groceries", "Eating out", "Bills & utilities", "Fees",
                     "Subscriptions"]
    assert "<td>41%</td><td>$725</td>" in table and "<th>Budget</th>" not in table      # no budget yet
    at.number_input(key="bud_amt_Groceries").set_value(185)
    run(at)
    table = next(t for t in budget_texts(at) if "rw-bud-table" in t)
    assert "<th>Budget</th><th>Left</th>" in table and ">fixed<" in table
    assert "Groceries</td><td>10%</td><td>$176</td><td>$185</td><td>$8.51 left</td>" in table
    at.number_input(key="bud_amt_Groceries").set_value(0)
    at.segmented_control(key="bud_month").set_value("2026-09")
    at.segmented_control(key="bud_account").set_value("card")
    run(at)
    line = next(t for t in budget_texts(at) if "rw-bud-line" in t)
    assert "In September, you spent" in line and "on the card" in line
    at.segmented_control(key="bud_month").set_value("2026-11")
    run(at)
    assert any("Nothing spent yet in November" in t for t in budget_texts(at))
    assert not [t for t in budget_texts(at) if "rw-bud-table" in t]


def test_budget_tab_purchases_are_the_proof(at):
    at.pills(key="bud_pick").set_value("Shopping")
    run(at)
    df = at.dataframe[0].value
    assert list(df.columns) == ["Date", "What", "Account", "Amount"]
    assert df.to_dict("records") == [{"Date": "Sun, Oct 18", "What": "Burlington", "Account": "Card",
                                      "Amount": "$171.99"},
                                     {"Date": "Sat, Oct 3", "What": "uBreakiFix", "Account": "Card",
                                      "Amount": "$289.00"}]


def test_donut_has_top_five_plus_other(ds_local=None):
    import engine as e
    import normalize
    from ui import budget
    sp = e.spending_by_category("2026-10-01", "2026-10-26", "both", normalize.load("local"))
    rows = budget.donut_rows(sp)
    assert [n for n, _ in rows] == ["Rent", "Shopping", "School", "Groceries", "Eating out", "Other"]
    assert sum(v for _, v in rows) == sp.total.value                      # Other = Bills + Fees + Subscriptions



def test_budget_section_base_case(at):
    head = next(t for t in texts(at) if 'class="rw-bud-head"' in t)
    assert ">Without your refund, November's bills are $101 more than your money. Send the verification form " \
           "first.<" in head
    assert at.button(key="ci_done_bud_refund").label == "Form sent"              # the action, right there
    assert at.button(key="bud_suggest").disabled and at.toggle(key="wf_budget").disabled


def test_suggest_budget_left_to_assign_and_progress(at):
    at.button(key="ci_done_refund").click()
    run(at)
    assert any(">You have $1,749 to spend after rent and bills in November.<" in t for t in texts(at))
    at.button(key="bud_suggest").click()
    run(at)
    assert [at.number_input(key=f"bud_amt_{c}").value for c in ("Shopping", "Groceries", "Eating out",
                                                                  "Transportation", "Meal plan")] == [18, 185, 96, 14, 0]
    assert any(">Left to assign: $1,436<" in t for t in texts(at))
    prog = next(t for t in texts(at) if 'class="rw-prog"' in t)
    assert "Shopping</span><span>$18 left" in prog                                # everyday purchases only
    assert "Plus a $289 one-off: uBreakiFix" in prog and "Plus a $172 one-off: Burlington" in prog
    assert "Groceries</span><span>$8.51 left" in prog and "spending fast" in prog
    at.number_input(key="bud_amt_Shopping").set_value(1500)
    run(at)
    left = next(t for t in texts(at) if 'class="rw-bud-left' in t)
    assert "rw-red" in left and ">Left to assign: $45.53 over<" in left        # 1,749.47 - (1,500 + 185 + 96 + 14)
    assert at.session_state["action_log"][-1]["what"] == "Filled in the suggested budget"


def test_budget_switch_updates_the_forecast(at):
    at.number_input(key="bud_amt_Groceries").set_value(60)
    run(at)
    at.toggle(key="wf_budget").set_value(True)
    run(at)
    assert ">Your money runs out in 2.8 weeks, on Sun, Nov 15.<" in status(at)
    effect = next(t for t in texts(at) if 'class="rw-bud-effect"' in t)
    assert ">If you stick to this budget, your money lasts until Sun, Nov 15 (6 days longer).<" in effect
    at.toggle(key="wf_budget").set_value(False)
    run(at)
    assert ">Your money runs out in 2 weeks, on Mon, Nov 9.<" in status(at)



def test_chat_budget_question_uses_the_budget_tab_amounts(at, monkeypatch, tmp_path):
    import json
    plan = json.dumps({"calls": [{"tool": "budget_status", "args": {"category": "food"}}]})
    _fake_models(monkeypatch, tmp_path, [plan], ["x", "x"])
    at.number_input(key="bud_amt_Groceries").set_value(185)
    at.number_input(key="bud_amt_Eating out").set_value(96)
    run(at)
    at.chat_input(key="ask_input").set_value("How much is left in my food budget?")
    run(at)
    assert at.session_state["history"][0].text.startswith("ANSWER: You have $23.19 left in your food budget")


# --- Find money and the meal plan card (sources 7 and 8) -------------------------------------------------------

def test_find_money_tab(at):
    assert [t.label for t in at.tabs] == ["Semester", "Budget", "Afford it?", "Find money", "Findings"]
    assert any(">You may qualify for 3 opportunities worth up to $1,750, plus a work-study job.<" in t for t in texts(at))
    heads = [plain(m.value) for m in at.markdown if m.value.startswith("#### ")
             and m.value not in ("#### Ways to fix it",) and not m.value.startswith("#### Your budget")]
    assert heads[:3] == ["#### Could help before you run out", "#### Helps later", "#### Almost (what you'd need)"]
    cards = {t.split('rw-fm-title">')[1].split("<")[0]: t for t in texts(at)
             if 'class="rw-fm-meta"' in t and 'rw-fm-title">' in t}
    grant = cards["Student Emergency Grant"]
    assert "Grant · Up to $500 · Apply anytime" in grant and "If approved, it arrives around Mon, Nov 2." in grant
    spring = cards["Spring Opportunity Scholarship"]
    assert "paid Fri, Jan 15, 2027, after the semester. So it adds $0.00 this semester." in spring
    assert "You'd need a 3.50 GPA (yours is 3.40)." in cards["Dean's Merit Scholarship"]
    assert at.toggle(key="wf_approved_OPP-04").disabled and not at.toggle(key="wf_approved_OPP-01").disabled
    assert any("1 more you don't qualify for: Engineering Senior Design Grant." in plain(c.value) for c in at.caption)


def test_if_approved_is_a_labelled_what_if(at):
    at.toggle(key="wf_approved_OPP-01").set_value(True)
    run(at)
    s = status(at)
    assert ">Your money runs out in 5.1 weeks, on Tue, Dec 1.<" in s            # from Mon, Nov 9
    assert ">Counting 1 aid award as if approved. It isn't certain money.<" in s
    at.toggle(key="wf_approved_OPP-01").set_value(False)
    run(at)
    assert ">Your money runs out in 2 weeks, on Mon, Nov 9.<" in status(at)


def test_application_draft_is_plain_and_true(at):
    code = next(c.value for c in at.code if "I'd like to apply for the Student Emergency Grant." in c.value)
    assert "a full-time sophomore majoring in Biology" in code
    assert "My $360 card payment is due Mon, Nov 9, and my checking account will be $59.84 below zero that day." in code
    assert "- Short statement of what happened (2-3 sentences)" in code
    link = next(b for b in at.get("link_button") if b.proto.label == "Open in my email app" and "Emergency" in b.proto.url)
    assert link.proto.url.startswith("mailto:finaid@stateu.example?subject=Application%3A%20Student%20Emergency")


# the meal plan card and its slider: tests/test_meal_card.py (the card was replaced in the meal plan upgrade)
