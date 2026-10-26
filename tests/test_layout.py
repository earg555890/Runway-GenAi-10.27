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


def test_the_panel_holds_only_the_chat_never_page_content(page):
    """The chat panel's own element tree: chat elements only. (The bug report showed the graph under "What Runway
    remembers": a see-through overlay made the page under the panel's edge look like part of it; style.py now dims
    and blurs the page and gives the panel a solid card.)"""
    page.button(key="chat_fab_btn").click()
    page.run()

    def dialogs(n):
        for c in getattr(n, "children", {}).values():
            if getattr(c, "type", None) == "dialog":
                yield c
            yield from dialogs(c)

    def kinds(n, out):
        for c in getattr(n, "children", {}).values():
            out.add((type(c).__name__, getattr(c, "key", None)))
            kinds(c, out)
        return out

    (panel,) = list(dialogs(page._tree))
    inside = kinds(panel, set())
    names = {k for k, _ in inside}
    assert not names & {"Tab", "VegaLiteChart", "ArrowVegaLiteChart", "UnknownElement"}, names
    assert not any(key in ("balance_card", "balance_chart", "notices", "checkin") for _, key in inside)
    assert any(key == "ask_input" for _, key in inside)
    from ui import style
    css = style.css("light")
    assert '[data-testid="stDialog"] {background: rgba(9,16,28,.62)' in css and "backdrop-filter: blur" in css
    assert 'div:has(> [role="dialog"]) {background: var(--rw-card)' in css


def test_demo_config_hides_the_toolbar_and_numbers_use_a_plain_zero():
    import tomllib
    from pathlib import Path
    cfg = tomllib.loads((Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert cfg["client"]["toolbarMode"] == "minimal"                       # no Deploy button, no top-right menu
    assert cfg["theme"]["font"].startswith("Runway Body") and cfg["theme"]["codeFont"].startswith("Runway Mono")
    faces = cfg["theme"]["fontFaces"]
    for fam in ("Runway Body", "Runway Mono"):
        letters = [f for f in faces if f["family"] == fam and f["unicodeRange"] != "U+0030-0039"]
        digits = [f for f in faces if f["family"] == fam and f["unicodeRange"] == "U+0030-0039"]
        assert letters and all("dmsans" in f["url"] for f in digits)               # digits: DM Sans, a plain zero
        # every letter face has a digit face with the same weight and style (browsers match weight first)
        assert {(f["weight"], f["style"]) for f in letters} == {(f["weight"], f["style"]) for f in digits}


def test_my_data_privacy_says_nightshift_not_nvidia():
    from ui import myimport
    assert "Meterless Nightshift on this computer" in myimport.PRIVACY and "local log" in myimport.PRIVACY
    assert "committed or uploaded" in myimport.PRIVACY and "go to NVIDIA" not in myimport.PRIVACY
