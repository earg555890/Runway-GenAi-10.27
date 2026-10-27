"""The hosted demo (Streamlit Community Cloud, docs/DEPLOY.md): HOSTED_DEMO forces sample mode, shows one banner line,
hides My data, and keeps each visitor's meal log, college and memory in their own session (no shared files). A disk
that can't be written never crashes the app."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import college
import config
import mealplan
from test_ui import plain, run, texts

ROOT = Path(__file__).resolve().parent.parent
PROBE = "import config; print(config.HOSTED_DEMO, config.SAMPLE_MODE, config.DATA_BACKEND, config.ANSWER_MODE)"


def test_hosted_demo_secret_forces_sample_mode():
    env = {k: v for k, v in os.environ.items() if k not in ("HOSTED_DEMO", "SAMPLE_MODE")}
    env.update(HOSTED_DEMO="true", SAMPLE_MODE="false", DATA_BACKEND="zetaris", ANSWER_MODE="live")
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["True", "True", "local", "replay"]


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setattr(config, "HOSTED_DEMO", True)
    monkeypatch.setattr(config, "SAMPLE_MODE", True)
    monkeypatch.setattr(config, "DATA_BACKEND", "local")
    monkeypatch.setattr(config, "ANSWER_MODE", "replay")


def app():
    at = AppTest.from_file("../ui/app.py", default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_banner_and_no_my_data(hosted):
    at = app()
    assert any("Live demo in sample mode: recorded answers, made-up student data. Run locally for live Nemotron and "
               "Zetaris." in plain(c.value) for c in at.caption)
    assert not at.get("button_group") or all(getattr(g, "key", None) != "data_mode" for g in at.get("button_group"))
    at.session_state["data_mode"] = "mine"                                  # even if a session asks for it
    run(at)
    assert not at.get("file_uploader")
    assert any(">Your money runs out in 2 weeks, on Mon, Nov 9.<" in t for t in texts(at))


def test_each_visitor_has_their_own_meal_log_college_and_memory(hosted):
    a, b = app(), app()
    a.button(key="meal_plus").click()
    run(a)
    a.text_input(key="college_name").set_value("Example University")
    a.button(key="FormSubmitter:college_form-Save").click()
    run(a)
    assert a.session_state["meal_data"]["log"] and a.session_state["college_data"]["college"]["name"] == "Example University"
    assert not mealplan.path("maya").exists() and not college.path("maya").exists()      # no shared files
    a.button(key="chat_fab_btn").click()
    run(a)
    assert any("You attend Example University." in t for t in texts(a))               # her memory, this session
    b.button(key="chat_fab_btn").click()
    run(b)
    assert not any("You attend Example University." in t for t in texts(b))           # another visitor's is empty
    assert b.session_state["meal_data"]["log"] == [] and b.session_state["college_data"]["college"] is None


def test_a_disk_that_cant_be_written_never_crashes(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(mealplan, "FOLDER", blocker / "sub")                     # mkdir under a file: OSError
    monkeypatch.setattr(college, "FOLDER", blocker / "sub")
    mealplan.save("maya", mealplan.empty())
    college.save("maya", college.empty())
    college.save_found("maya", {"results": []})
    monkeypatch.setattr(config, "DATA_BACKEND", "local")
    at = app()
    at.button(key="meal_plus").click()
    run(at)
    assert at.session_state["meal_data"]["log"][0]["meals"] == 1                 # kept in the session
