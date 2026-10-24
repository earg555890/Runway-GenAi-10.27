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
    assert at.chat_input[0].disabled
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
