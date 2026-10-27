"""My college, jobs near campus and the school's published costs (college.py, ui/college.py, the engine's new-job and
estimate math, the chat's find_jobs tool). The web search is always mocked: no live calls in tests. Maya's default
state stays exactly the same."""
import dataclasses
from datetime import date
from decimal import Decimal

import pytest
from streamlit.testing.v1 import AppTest

import college
import config
import engine as e
import normalize
import runway_memory
from test_ui import plain, run, status, texts

D = Decimal
UIUC = ("University of Illinois Urbana-Champaign", "Champaign, IL")


@pytest.fixture(scope="module")
def ds():
    return normalize.load("local")


@pytest.fixture(scope="module")
def bare(ds):
    """My data mode: no school records (no bursar bill, no job)."""
    return dataclasses.replace(ds, ledger=[], installments=[], refunds=[], disbursements=[], job=None, pay_periods=[],
                               shifts=[])


# --- Part 1: My college --------------------------------------------------------------------------------------------
def test_default_is_maya_demo_school_and_nothing_reaches_the_engine():
    data = college.load("maya")
    assert data == college.empty()
    c = college.current(data, "maya")
    assert c["name"] == "State University" and c["demo"] and not c["city"]
    assert college.current(college.load("mine"), "mine") is None                  # My data mode: empty until set
    assert college.scenario_part(data) == {}


def test_set_edit_remove_and_storage():
    data = college.load("maya")
    assert college.set_college(data, "", "x") == "Type your college's name."
    assert college.set_college(data, "x" * 81) == "That name is too long."
    assert college.set_college(data, "  Example   University ", "Champaign, IL", "off", "5") is None
    college.save("maya", data)
    back = college.load("maya")
    assert college.current(back, "maya") == {"name": "Example University", "city": "Champaign, IL",
                                             "housing": "off", "travel": "5", "demo": False}
    assert college.memory_text(back["college"]) == ("You attend Example University in Champaign, IL. You live off "
                                                    "campus. You can travel within 5 miles for work.")
    college.remove_college(back)
    assert college.current(back, "maya") is None                                  # removed: no demo school either
    assert college.load("mine") == college.empty() and college.path("maya") != college.path("mine")


def test_files_are_gitignored():
    ignored = (config.PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".cache/" in ignored and "user_data/" in ignored
    college.FOLDER, saved = None, college.FOLDER
    try:
        assert college.path("maya") == config.PROJECT_ROOT / ".cache" / "college.json"
        assert college.path("mine") == config.USER_DATA_DIR / "college.json"
    finally:
        college.FOLDER = saved


def test_memory_with_provenance_supersedes_and_forgets(tmp_path):
    mem = runway_memory.RunwayMemory(persist_dir=tmp_path / "m")
    mem.remember_college("You attend Example University in Champaign, IL.")
    mem.remember_college("You attend Other College in Springfield, IL.")
    live = [m for m in mem.items() if "college" in m.tags]
    assert len(live) == 1 and live[0].content.startswith("You attend Other College")
    assert live[0].provenance["label"] == "You set this in My college"
    mem.forget_college()
    assert not [m for m in mem.items() if "college" in m.tags]


@pytest.fixture
def at(monkeypatch):
    monkeypatch.setattr(config, "DATA_BACKEND", "local")
    app = AppTest.from_file("../ui/app.py", default_timeout=60)
    app.run()
    assert not app.exception, [x.value for x in app.exception]
    return app


def save_college(at, name, city, housing="off", travel="5"):
    at.text_input(key="college_name").set_value(name)
    at.text_input(key="college_city").set_value(city)
    at.selectbox(key="college_housing").set_value(housing)
    at.selectbox(key="college_travel").set_value(travel)
    at.button(key="FormSubmitter:college_form-Save").click()
    run(at)


def test_card_demo_school_then_her_college_in_memory(at):
    before = status(at)
    assert any("A demo school from Maya's made-up data." in plain(c.value) for c in at.caption)
    save_college(at, *UIUC)
    assert any("<b>University of Illinois Urbana-Champaign, Champaign, IL</b> · Off campus · within 5 miles" in t
               for t in texts(at))
    assert college.load("maya")["college"]["name"] == UIUC[0]
    at.button(key="chat_fab_btn").click()
    run(at)
    assert any("You attend University of Illinois Urbana-Champaign in Champaign, IL." in t for t in texts(at))
    assert status(at) == before                                                    # nothing changes the forecast
    at.button(key="college_remove").click()
    run(at)
    assert not any("You attend" in t for t in texts(at))
    assert any("Add your college to find jobs near campus" in t for t in texts(at))
