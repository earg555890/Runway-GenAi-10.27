"""ui/app.py through Streamlit's AppTest, local backend, no network, no LLM."""
import html

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


def answer(at):
    return next((t for t in texts(at) if 'class="rw-answer' in t), "")


def run(at):
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_base_status_and_fix_cards(at):
    s = status(at)
    assert "Your money runs out Mon Nov 9, 2 weeks from today." in s
    assert "credit card payment of $359.53" in s
    assert not at.chat_input[0].disabled
    assert [b.label for b in at.button if str(b.key).startswith("ask_suggest_")][1] == "How long will my money last?"
    assert [t.label for t in at.toggle][:3] == ["**Send the verification form to financial aid**", "**Cancel Spotify**",
                                               "**Pick up an extra shift**"]
    body = "\n".join(texts(at))
    assert "Releases your $1,850.00 refund around Thu Nov 5." in body
    assert "Saves $23.98 before the semester ends." in body
    why = next(e for e in at.expander if e.label == "Cancelling Apple Music won't help this semester. Why?")
    assert "Thu Jan 7, 2027" in plain(why.markdown[0].value) and "saves $0.00" in plain(why.markdown[0].value)


def test_flight_yes_if_two_things_then_do_these(at):
    at.button(key="buy_check").click()
    run(at)
    assert "Yes, if you do 2 things" in answer(at)
    at.button(key="buy_do").click()
    run(at)
    assert at.toggle(key="wf_refund").value and at.toggle(key="wf_cancel_Spotify").value
    assert not at.session_state["wf_cancel_Apple Music"]
    assert "You can afford it." in answer(at)
    body = "\n".join(texts(at))
    assert "Your lowest point would be $5.81 on Mon Nov 2. That's cutting it close." in body
    assert "Lowest point: $5.81 on Mon Nov 2." in status(at)


def test_start_over_resets(at):
    at.toggle(key="wf_refund").set_value(True)
    at.toggle(key="wf_cancel_Spotify").set_value(True)
    at.button(key="buy_check").click()
    run(at)
    assert "covered" in status(at)
    at.button(key="start_over").click()
    run(at)
    assert "Your money runs out Mon Nov 9" in status(at)
    assert not at.toggle(key="wf_refund").value and not at.session_state["buy_active"]


def test_extra_shift_shows_added_pay(at):
    assert any("Adds $57.35 to your Wed Nov 18 paycheck." in t for t in texts(at))
    at.toggle(key="wf_shift_on").set_value(True)
    run(at)
    assert "extra shift Wed Nov 4 (4.0 hours)" in status(at)


def test_found_cards_and_proof(at):
    body = "\n".join(texts(at))
    for title in ("Your $1,850.00 refund is on hold", "You pay for 2 music apps", "Rent caused a $35.00 overdraft fee",
                  "Money is tight the week of Nov 16"):
        assert f"#### {title}" in body, title
    assert "$22.98 a month for Spotify and Apple Music." in body
    assert "Rent is due the 1st but your paycheck came Fri Oct 2." in body
    assert "(estimated)" in body
    proof = [e for e in at.expander if e.label == "Show proof"]
    assert len(proof) == 4
    assert "Your checking account" in proof[2].dataframe[0].value["Where"].tolist()


def test_no_jargon_outside_behind_the_scenes(at):
    behind = next(e for e in at.expander if e.label == "Behind the scenes")
    hidden = {plain(m.value) for m in behind.markdown} | {plain(c.value) for c in behind.caption}
    visible = [t for t in texts(at) if t not in hidden and not t.startswith("<style>")]
    for word in ("scenario", "Computed", "evidence", "row ID", "backend", "ledger", "projection", "delta"):
        assert not any(word in t for t in visible), word


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


# --- Ask Runway (mocked models) -----------------------------------------------------------------

@pytest.fixture
def asked(at, monkeypatch, tmp_path):
    import agent
    import llm_client
    from test_agent import FLIGHT_PLAN, GOOD_FLIGHT, FakeLLM

    fake = FakeLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT])
    monkeypatch.setattr(llm_client, "chat_json", fake.chat_json)
    monkeypatch.setattr(llm_client, "stream_chat", fake.stream_chat)
    monkeypatch.setattr(config, "ANSWER_MODE", "live")
    monkeypatch.setattr(config, "ANSWER_CACHE_DIR", tmp_path / "answers")
    at.button(key="ask_suggest_0").click()
    run(at)
    assert agent.SUGGESTED[0].startswith("Can I afford a $400 flight")
    return at


def test_ask_flight_question_shows_answer_chips_and_do_these(asked):
    at = asked
    assert any(":orange-badge[Yes, if you do 2 things]" in t for t in texts(at))     # the verdict chip
    answer = next(t for t in texts(at) if t.startswith("Yes, if you do 2 things"))
    assert ":blue-badge[1]" in answer and "[C1]" not in answer             # citations became footnote chips
    proof = at.pills(key=next(k for k in at.session_state if str(k).startswith("proof_")))
    assert len(proof.options) >= 5
    proof.set_value(proof.options[1])
    run(at)
    assert any("Thu Nov 5" in t for t in texts(at))                          # the refund proof, in plain words
    assert any("Draft email to Office of Student Financial Aid" in t for t in texts(at))
    do = next(b for b in at.button if str(b.key).startswith("ans_do_"))
    do.click()
    run(at)
    assert at.toggle(key="wf_refund").value and at.toggle(key="wf_cancel_Spotify").value
    assert not at.session_state["wf_cancel_Apple Music"]
    assert "Lowest point: $5.81 on Mon Nov 2." in status(at)
    assert len(at.session_state["history"]) == 1 and at.session_state["history"][0].mode == "live"


# --- big number and chart -----------------------------------------------------------------------

def test_big_number_and_figures(at):
    t = texts(at)
    assert any('class="rw-today">$783.38<' in x and "in your checking account today" in x for x in t)
    fig = next(x for x in t if 'class="rw-fig"' in x)
    assert "rw-red\">-$1,462.37</span> on Thu Dec 17" in fig and "End of semester:" in fig and "-$1,412.53" in fig
    assert "rw-delta" not in fig
    at.toggle(key="wf_refund").set_value(True)
    run(at)
    fig = next(x for x in texts(at) if 'class="rw-fig"' in x)
    assert "rw-green\">$5.81</span> on Mon Nov 2" in fig and "rw-up\">+$1,468.18<" in fig and "+$1,850.00" in fig


def _spec(changed):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import engine
    import normalize
    from ui import chart
    ds, ledger = normalize.load("local"), engine.Ledger()
    base = engine.project(engine.Scenario(), ds, ledger)
    cur = engine.project(engine.Scenario(refund_released=True, cancel_subscriptions=("Spotify",)), ds, ledger) \
        if changed else base
    return chart.build(base, cur, changed).to_dict(validate=True)


def test_chart_layers_base():
    spec = _spec(False)
    marks = [l["mark"]["type"] if isinstance(l["mark"], dict) else l["mark"] for l in spec["layer"]]
    assert marks.count("area") == 2 and "rule" in marks and "tick" in marks and "line" in marks
    labels = [r["t"] for d in spec["datasets"].values() for r in d if "t" in r]
    assert "$0" in labels and "Today $783.38" in labels and "Lowest: -$1,462.37, Thu Dec 17" in labels
    assert "-$1,412.53" in labels and {"Rent", "Card payment", "Paycheck"} <= set(labels)
    days = next(d for d in spec["datasets"].values() if d and "events" in d[0])
    nov9 = next(r for r in days if r["when"] == "Mon Nov 9")
    assert "Card payment -$359.53" in nov9["events"] and nov9["bal"] == "-$59.84"     # $307.20 - $359.53 - $7.51
    assert "Before your changes" not in str(spec)


def test_chart_layers_changed_shows_before_line_and_legend():
    spec = _spec(True)
    assert "Before your changes" in str(spec) and "With your changes" in str(spec)
    labels = [r["t"] for d in spec["datasets"].values() for r in d if "t" in r]
    assert "Lowest: $5.81, Mon Nov 2" in labels and "Refund" in labels
