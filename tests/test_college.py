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


# --- Part 2: jobs near campus -------------------------------------------------------------------------------------
import agent  # noqa: E402
import llm_client  # noqa: E402
from test_agent import FakeLLM  # noqa: E402

COLLEGE = {"name": UIUC[0], "city": UIUC[1], "housing": "off", "travel": "5", "demo": False}
JOB_PAGES = {"data": {"web": [
    {"title": "Campus Jobs | The Career Center - University of Illinois", "url": "https://careercenter.illinois.edu/jobs",
     "markdown": "Student jobs in Champaign. Library assistant, $15.50 an hour, 10-15 hours per week."},
    {"title": "Hiring Now: 278 Part Time Student Jobs in Champaign, IL - Indeed",
     "url": "https://www.indeed.com/q-part-time-student-l-champaign,-il-jobs.html",
     "markdown": "Barista $15 an hour. Tutor $20 an hour. Cashier $25 - $35 an hour. 20 hours per week."},
    {"title": "A guide", "url": "https://www.reddit.com/r/UIUC/x", "markdown": ""}]}}


def fake_post(pages):
    calls = []

    def post(query, limit=None):
        calls.append(query)
        return pages
    post.calls = calls
    return post


def test_job_results_show_only_what_the_page_says():
    post = fake_post(JOB_PAGES)
    found = college.search_jobs(COLLEGE, post=post)
    assert post.calls == ["student jobs on campus University of Illinois Urbana-Champaign Champaign, IL",
                          "part-time jobs for college students near University of Illinois Urbana-Champaign "
                          "Champaign, IL within 5 miles"]
    a, b, c = found["results"]                                                    # deduplicated by link
    assert (a["employer"], a["place"], a["pay"], a["hours"]) == ("careercenter.illinois.edu", "Champaign, IL",
                                                                 "$15.50 an hour", "10-15 hours per week")
    assert (b["pay"], b["hours"]) == (college.SEE, "20 hours per week")           # many pays on a listing page
    assert (c["place"], c["pay"], c["hours"]) == (college.SEE, college.SEE, college.SEE)
    assert college.pay_number(a["pay"]) == D("15.50") and college.pay_number("$15 - $18 an hour") is None
    assert college.pay_number(college.SEE) is None


def test_no_search_fallback_never_raises():
    from ui import college as college_ui

    def down(*a, **k):
        raise OSError("offline")
    assert college_ui._search(lambda c: college.search_jobs(c, post=down), COLLEGE) == {"error": True}
    assert college.job_queries({**COLLEGE, "travel": "campus"}) == [
        "student jobs on campus University of Illinois Urbana-Champaign Champaign, IL"]


def test_new_job_paychecks_and_what_if(ds):
    job = e.NewJob(D("15"), D("10"), date(2026, 11, 2), "biweekly", D("7.5"))
    pay = e.new_job_pay(job, e.Ledger())
    assert [(p.start, p.end, p.pay_date, p.hours, p.net.value) for p in pay] == [
        (date(2026, 11, 2), date(2026, 11, 15), date(2026, 11, 20), D("20.00"), D("277.50")),
        (date(2026, 11, 16), date(2026, 11, 29), date(2026, 12, 4), D("20.00"), D("277.50")),
        (date(2026, 11, 30), date(2026, 12, 13), date(2026, 12, 18), D("20.00"), D("277.50"))]   # 300 - 7.5%
    w = e.job_what_if(job, e.Scenario(), ds)
    assert w.first_pay.value == date(2026, 11, 20) and w.before_run_out is False      # after Mon, Nov 9
    assert w.before.first_below_zero.value == w.after.first_below_zero.value == date(2026, 11, 9)
    assert (w.before.lowest.value, w.after.lowest.value) == (D("-1462.37"), D("-907.37"))
    assert w.total.value == D("832.50") and w.days_longer.value == 0
    early = e.job_what_if(e.NewJob(D("15"), D("10"), date(2026, 10, 27), "weekly", D("7.5")), e.Scenario(), ds)
    assert early.pay[0].hours == D("8.57") and early.first_pay.value == date(2026, 11, 6)  # 6 of 7 days, Fri after
    assert early.before_run_out is True and early.after.first_below_zero.value == date(2026, 12, 1)
    assert early.days_longer.value == 22
    assert e.project(e.Scenario(), ds).lowest.value == D("-1462.37")                   # her plan is unchanged


def test_job_validation():
    assert e.new_job_problem(0, 10, date(2026, 11, 2)) == "Pay per hour must be more than $0 and at most $100."
    assert e.new_job_problem(15, 41, date(2026, 11, 2)) == "Hours a week must be more than 0 and at most 40."
    assert e.new_job_problem(15, 10, date(2026, 10, 26)).startswith("Pick a start date after")
    assert e.new_job_problem(15, 10, date(2026, 11, 2), "monthly") == "Pick weekly or every two weeks."
    with pytest.raises(ValueError):
        e.Scenario(new_jobs=(e.NewJob(D("15"), D("50"), date(2026, 11, 2)),))


def test_add_to_my_plan_changes_the_forecast_only_then(ds):
    data = college.load("maya")
    job = e.NewJob(D("15"), D("20"), date(2026, 10, 27), "weekly", D("7.5"), "Library assistant")
    assert e.project(e.Scenario(**college.scenario_part(data)), ds).first_below_zero.value == date(2026, 11, 9)
    college.add_job(data, job)
    college.add_job(data, job)                                                    # once only
    college.save("maya", data)
    part = college.scenario_part(college.load("maya"))
    assert part == {"new_jobs": (job,)}
    p = e.project(e.Scenario(**part), ds)
    assert p.first_below_zero.value == date(2026, 12, 7) and p.lowest.value == D("-49.99")
    assert [ev.date.day for ev in p.events if ev.kind == "new_job"] == [6, 13, 20, 27, 4, 11, 18]   # Fridays
    college.remove_job(data, 0)
    assert college.scenario_part(data) == {}


def ask(q, plan, ds, scenario=None):
    return agent.ask(q, scenario or e.Scenario(), ds=ds, mode="live",
                     llm=FakeLLM(plans=[plan], explain_error=llm_client.LLMError("down")))


def test_chat_job_what_if_required_facts(ds, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ANSWER_CACHE_DIR", tmp_path)
    a = ask("Would a $15/hour job at 10 hours a week help?",
            '{"calls": [{"tool": "find_jobs", "args": {"hourly_rate": 15, "hours_per_week": 10}}]}', ds)
    assert a.check["ok"], a.check
    assert [(f["key"], f["appended"]) for f in a.facts] == [("first_pay", False), ("timing", False), ("lowest", False),
                                                            ("assumption", False), ("assumption", False)]
    assert a.sections["answer"].startswith("Your first paycheck would come Fri, Nov 20")
    assert a.sections["why"][0].startswith("That's after you run out on Mon, Nov 9")
    assert "Your lowest point would be $907 below zero" in a.sections["why"][1]
    assert a.sections["note"].count("I assumed Mon, Nov 2") == 1
    assert agent.keyword_plan("Would a $15/hour job at 10 hours a week help?", []).args["hours_per_week"] == "10.00"


def test_chat_find_jobs_cites_web_links_not_records(ds, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ANSWER_CACHE_DIR", tmp_path)
    monkeypatch.setattr(college, "ACTIVE_MODE", "maya")
    a = ask("Find me a job near campus", '{"calls": [{"tool": "find_jobs"}]}', ds)
    assert a.check["ok"] and a.sections["answer"] == "I haven't found jobs near State University yet."
    college.save_found("maya", college.search_jobs(COLLEGE, post=fake_post(JOB_PAGES)))
    a = ask("Find me a job near campus", '{"calls": [{"tool": "find_jobs"}]}', ds)
    assert a.check["ok"], a.check
    assert a.sections["answer"] == "Here are 3 job pages near State University I found online. Check before applying."
    assert a.sections["why"][0].startswith("[Campus Jobs | The Career Center - University of Illinois]"
                                           "(https://careercenter.illinois.edu/jobs)")
    assert "pay $15.50 an hour" in a.sections["why"][0]
    assert not any(it.get("kind") == "source" for it in a.pack["items"])         # no records: web links only


def test_jobs_card_offline_and_what_if_form(at, monkeypatch):
    assert any("Add your college's city in My college to search for jobs near campus." in plain(c.value)
               for c in at.caption)                                                # the demo school has no city
    before = status(at)
    at.button(key="job_open_btn").click()
    run(at)
    at.number_input(key="job_rate").set_value(15.0)
    at.button(key="FormSubmitter:job_form-See what changes").click()
    run(at)
    t = [x for x in texts(at) if "Your first paycheck would come" in x]
    assert t and "Fri, Nov 20" in t[0] and "after you run out on Mon, Nov 9" in t[0]
    assert '<span class="rw-red">$907 below zero</span>' in t[0]
    assert status(at) == before                                                    # a what-if only
    at.button(key="job_add").click()
    run(at)
    assert ">Your money runs out in 2 weeks, on Mon, Nov 9.<" in status(at)          # paid after the run-out
    assert college.load("maya")["jobs"][0]["hourly_rate"] == "15.00"
    at.button(key="job_rm_0").click()
    run(at)
    assert college.load("maya")["jobs"] == [] and status(at) == before
    monkeypatch.setattr(config, "ANSWER_MODE", "replay")
    run(at)
    assert any("Searching online is off in this offline demo." in plain(c.value) for c in at.caption)
