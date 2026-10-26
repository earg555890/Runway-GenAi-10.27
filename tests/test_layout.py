"""The page layout: header, the important notices (status card + check-in), the tabs (Semester first), Behind the
scenes at the bottom, and the floating "Ask Runway" button that opens the chat panel (st.dialog) with the whole chat.
Buttons in the panel that change the forecast update the page; the panel reopens and says so."""
import pytest
from streamlit.testing.v1 import AppTest

import config
from ui import ask


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setattr(config, "DATA_BACKEND", "local")
    at = AppTest.from_file("../ui/app.py", default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _top_level(at):
    out = []
    for c in at.main.children.values():
        name = type(c).__name__
        label = getattr(c, "key", None) or getattr(c, "label", None) or ""
        if name == "Block" and any(type(x).__name__ == "Tab" for x in c.children.values()):
            label = "tabs:" + ",".join(x.label for x in c.children.values())
        out.append(label)
    return out


def test_page_order_notices_then_tabs_then_behind_the_scenes(page):
    order = [x for x in _top_level(page) if x in ("notices", "Behind the scenes") or str(x).startswith("tabs:")]
    assert order == ["notices", "tabs:Semester,Budget,Afford it?,Find money,Findings", "Behind the scenes"]
    notices = next(c for c in page.main.children.values() if getattr(c, "key", None) == "notices")
    assert "rw-status" in next(iter(notices.children.values())).value                  # the status card first
    assert any(getattr(c, "key", None) == "checkin" for c in notices.children.values())  # then the check-in


def test_the_chat_is_not_in_the_page_body_until_the_button_opens_the_panel(page):
    assert [b.label for b in page.button if b.key == "chat_fab_btn"] == ["Ask Runway"]
    assert not page.chat_input and not [b for b in page.button if str(b.key).startswith("ask_suggest_")]
    assert not any(e.label.startswith("What Runway remembers") for e in page.expander)
    page.button(key="chat_fab_btn").click()
    page.run()
    assert page.session_state["chat_open"] is True
    assert len([b for b in page.button if str(b.key).startswith("ask_suggest_")]) == 5
    assert len(page.chat_input) == 1 and any(t.key == "ask_think" for t in page.toggle)
    assert any(e.label.startswith("What Runway remembers") for e in page.expander)


def test_closing_and_reopening_keeps_the_thread(page, monkeypatch, tmp_path):
    from test_agent import FLIGHT_PLAN, GOOD_FLIGHT
    from test_ui import _fake_models
    _fake_models(monkeypatch, tmp_path, [FLIGHT_PLAN], [GOOD_FLIGHT])
    page.button(key="chat_fab_btn").click()
    page.run()
    page.button(key="ask_suggest_0").click()
    page.run()
    assert len(page.session_state["history"]) == 1 and "ask_pending" not in page.session_state
    page.session_state["chat_open"] = False                     # what the panel's X (on_dismiss) does
    page.run()
    assert not page.chat_input
    page.button(key="chat_fab_btn").click()
    page.run()
    assert [m.name for m in page.chat_message] == ["user", "assistant"]


def test_do_these_in_the_panel_updates_the_page_and_says_so(page, monkeypatch, tmp_path):
    from test_agent import FLIGHT_PLAN, GOOD_FLIGHT
    from test_ui import _fake_models, status
    _fake_models(monkeypatch, tmp_path, [FLIGHT_PLAN], [GOOD_FLIGHT])
    page.button(key="chat_fab_btn").click()
    page.run()
    page.button(key="ask_suggest_0").click()
    page.run()
    assert ">Your money runs out in 2 weeks, on Mon, Nov 9.<" in status(page)
    next(b for b in page.button if str(b.key).startswith("ans_do_")).click()
    page.run()
    assert ">You're covered all semester.<" in status(page)                        # the page updated
    assert page.session_state["chat_open"] is True                                   # the panel is open again
    assert page.session_state["history"][0].text == ask.UPDATED                      # and says what happened


def test_forecast_signature_sees_what_ifs_done_items_and_budget():
    import streamlit as st
    st.session_state.clear()
    base = ask.forecast_sig()
    st.session_state["wf_refund"] = True
    assert ask.forecast_sig() != base
    st.session_state["done"] = {"refund": {}}
    assert ask.forecast_sig() != base
