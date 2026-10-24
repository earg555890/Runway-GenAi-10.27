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
    assert [b.label for b in at.button if str(b.key).startswith("ask_suggest_")][3] == \
        "Can I afford a $400 flight home for Thanksgiving?"
    assert [t.label for t in at.toggle][:3] == ["**Send the verification form**", "**Cancel Spotify**",
                                               "**Pick up an extra shift**"]
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


def test_extra_shift_shows_added_pay(at):
    assert any("Adds $57.35 to your Wed, Nov 18 paycheck." in t for t in texts(at))
    at.toggle(key="wf_shift_on").set_value(True)
    run(at)
    assert at.session_state["wf_shift_on"] and figures(at)[0].count("rw-delta") == 1


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
        assert f"#### {title}" in body and sentence in body, title
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
    at.button(key="ask_suggest_0").click()
    run(at)
    return at


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
    assert at.session_state["history"][0].mode == "live" and at.session_state["history"][0].sections


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


# --- chart --------------------------------------------------------------------------------------

def _spec(changed):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import engine
    import normalize
    from ui import chart
    ds, ledger = normalize.load("local"), engine.Ledger()
    base = engine.project(engine.Scenario(), ds, ledger)
    cur = engine.project(engine.Scenario(refund_released=True, cancel_subscriptions=("Spotify",)), ds, ledger) \
        if changed else base
    return chart.build(base, cur, changed).to_dict(validate=True)


def _labels(spec):
    return [r["t"] for d in spec["datasets"].values() for r in d if "t" in r]


def test_chart_layers_base():
    spec = _spec(False)
    marks = [l["mark"]["type"] if isinstance(l["mark"], dict) else l["mark"] for l in spec["layer"]]
    assert marks.count("area") == 2 and "rule" in marks and "tick" in marks and "line" in marks
    labels = _labels(spec)
    assert {"$0", "Today", "Lowest point"} <= set(labels)          # amounts live in the figures above the chart
    assert not any("below zero" in x for x in labels)
    assert {"Rent", "Card payment", "Paycheck"} <= set(labels)
    days = next(d for d in spec["datasets"].values() if d and "events" in d[0])
    nov9 = next(r for r in days if r["when"] == "Mon, Nov 9")
    assert "Card payment: $360 out" in nov9["events"] and nov9["bal"] == "$59.84 below zero"   # under $100: cents kept
    assert nov9["balance"] == -59.84                                                       # the exact value
    assert "Before your changes" not in str(spec)


def test_chart_layers_changed_shows_before_line_and_legend():
    spec = _spec(True)
    assert "Before your changes" in str(spec) and "With your changes" in str(spec)
    assert {"Lowest point", "Refund"} <= set(_labels(spec))
