"""ui/app.py through Streamlit's AppTest, local backend, no network, no LLM."""
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


def metric(at, label_start):
    return next(m for m in at.metric if m.label.startswith(label_start))


def test_renders_base_scenario(at):
    assert metric(at, "Runway").value == "2.0 weeks, until Mon Nov 9"
    assert metric(at, "Lowest balance").value == "-$1,462.37"
    assert metric(at, "Balance at semester end").value == "-$1,412.53"
    assert at.chat_input[0].disabled
    labels = [c.label for c in at.checkbox]
    assert "Cancel Spotify - saves $23.98 before Fri Dec 18" in labels
    assert "Cancel Apple Music - saves $0.00 before Fri Dec 18" in labels
    assert any("Thu Jan 7, 2027" in c.value for c in at.caption)      # why Apple Music saves $0


def test_refund_spotify_and_flight_resolve_yes_if(at):
    at.toggle(key="wf_refund").set_value(True)
    at.checkbox(key="wf_cancel_Spotify").check()
    at.toggle(key="wf_buy_on").set_value(True)
    at.run()
    assert not at.exception
    assert any(w.value.startswith("**Yes, if**") for w in at.warning)
    assert any(s.value.startswith("**Resolved.**") and "$5.81" in s.value for s in at.success)
    assert metric(at, "Lowest balance").value == "$5.81"
    assert metric(at, "Runway").value == "Lasts the whole semester"


def test_apply_these_fixes_turns_toggles_on(at):
    at.toggle(key="wf_buy_on").set_value(True)
    at.run()
    at.button(key="wf_apply").click()
    at.run()
    assert at.toggle(key="wf_refund").value and at.checkbox(key="wf_cancel_Spotify").value
    assert not at.checkbox(key="wf_cancel_Apple Music").value
    assert metric(at, "Lowest balance").value == "$5.81"
    at.button(key="wf_reset").click()
    at.run()
    assert metric(at, "Lowest balance").value == "-$1,462.37"


def test_extra_shift_add_and_remove(at):
    at.button(key="wf_add_shift").click()
    at.run()
    assert len(at.session_state["wf_shifts"]) == 1
    assert metric(at, "Lowest balance").delta is not None
    at.button(key="wf_rm_0").click()
    at.run()
    assert at.session_state["wf_shifts"] == []


def test_fee_savings_labelled_estimated(at):
    assert any("**Estimated** fees" in m.value and "(estimated)" in m.value for m in at.markdown)


def test_explainer_drills_into_rows_and_records(at):
    records = at.selectbox(key="explain_record")
    lowest = next(o for o in records.options if "lowest checking balance" in o)
    records.set_value(lowest.split(":")[0])
    at.run()
    pills = at.pills(key="explain_input")
    assert "C1" in pills.options                                     # the start balance record
    pills.set_value("C1")
    at.run()
    assert at.selectbox(key="explain_record").value == "C1"          # jumped to the record
    at.pills(key="explain_input").set_value("ACCT-CHK-01")
    at.run()
    assert any("checking_account" in m.value and "`local`" in m.value for m in at.markdown)
    assert any("checking/account.csv" in c.value for c in at.code)   # the evidence's query text (local backend)
