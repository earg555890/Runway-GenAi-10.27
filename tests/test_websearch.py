"""Live scholarship search (websearch.py) with mocked Firecrawl responses: only text written on the page is shown,
a model's amount that isn't on the page becomes "see website", failures fall back to the cache or the saved set,
replay never searches, and the chat answer says "check before applying" and never "you qualify". No network."""
import json
from types import SimpleNamespace

import pytest

import agent
import config
import engine
import llm_client
import websearch
from test_agent import FakeLLM

PAGE = ("# Sophomore Science Award\n\nThe award amount is $2,500 for one student each year. Funded by a $2 million "
        "endowment.\n\nApplication deadline: March 1, 2027.\n")


def response(*items):
    return {"success": True, "data": {"web": [dict(url=u, title=t, markdown=m, metadata={}) for u, t, m in items]}}


class FakeSuggest:
    """The fast model's amount/deadline suggestion (websearch.suggest)."""

    def __init__(self, reply):
        self.reply = reply

    def chat(self, messages, **kwargs):
        return SimpleNamespace(text=json.dumps(self.reply))


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(websearch, "CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(websearch, "SAVED", tmp_path / "saved.json")
    return tmp_path


def test_amount_and_deadline_only_when_on_the_page():
    r = websearch.extract("Sophomore Science Award", "https://example.org/award", PAGE)
    assert (r.amount, r.deadline, r.organization) == ("$2,500", "March 1, 2027", "example.org")   # not "$2" million
    bare = websearch.extract("Grants", "https://example.org/g", "Apply for emergency help any time.")
    assert (bare.amount, bare.deadline) == (websearch.SEE, websearch.SEE)


def test_a_model_amount_that_isnt_on_the_page_is_dropped():
    claims = FakeSuggest({"amount": "$5,000", "deadline": "April 30, 2027"})          # neither is on the page
    r = websearch.extract("Sophomore Science Award", "https://example.org/award", PAGE, llm=claims)
    assert (r.amount, r.deadline) == ("$2,500", "March 1, 2027")                   # the page's own words kept
    r = websearch.extract("Help", "https://example.org/h", "Emergency grants for students.", llm=claims)
    assert (r.amount, r.deadline) == (websearch.SEE, websearch.SEE)
    ok = FakeSuggest({"amount": "$2,500", "deadline": "March 1, 2027"})
    assert websearch.extract("A", "https://example.org/award", PAGE, llm=ok).amount == "$2,500"


def test_directory_pages_get_no_single_amount():
    page = "Awards: $500, $1,000, $1,500, $2,000, $5,000 and $10,000. Deadline Jan 5. Deadline Feb 9. Deadline Mar 3."
    r = websearch.extract("Scholarship directory", "https://example.org/dir", page)
    assert (r.amount, r.deadline) == (websearch.SEE, websearch.SEE)


def test_search_dedupes_and_caches(paths):
    calls = []

    def post(q):
        calls.append(q)
        return response(("https://example.org/award", "Sophomore Science Award", PAGE),
                        ("https://example.org/award", "Duplicate", PAGE))

    profile = SimpleNamespace(class_year="sophomore", major="Biology")
    found = websearch.get(profile, "cached", post=post)
    assert calls == websearch.queries(profile) == ["scholarships for college sophomores",
                                                   "emergency grants for college students",
                                                   "scholarships for biology majors"]
    assert [r["url"] for r in found["results"]] == ["https://example.org/award"]
    assert websearch.load(websearch.CACHE) == found
    assert websearch.get(profile, "cached", post=lambda q: pytest.fail("cache is fresh")) == found


def test_timeouts_fall_back_and_never_raise(paths):
    def post(q):
        raise TimeoutError("slow")

    assert websearch.get(None, "live", post=post) is None                          # nothing at all: None
    websearch.save({"found_at": "2026-10-25T23:24", "provider": "x", "results": [{"title": "Saved"}]},
                   websearch.SAVED)
    assert websearch.get(None, "live", post=post)["results"][0]["title"] == "Saved"


def test_replay_never_searches(paths):
    assert websearch.get(None, "replay") is None
    websearch.save({"found_at": "2026-10-25T23:24", "provider": "x", "results": []}, websearch.SAVED)
    assert websearch.get(None, "replay")["found_at"] == "2026-10-25T23:24"


def test_the_committed_saved_set_only_has_page_text():
    found = json.loads(config.DEMO_ANSWERS_DIR.joinpath("web_scholarships.json").read_text(encoding="utf-8"))
    assert found["found_at"] and found["results"]
    for r in found["results"]:
        assert r["url"].startswith("https://") and r["title"]
        assert r["amount"] == websearch.SEE or r["amount"].startswith("$")


def test_chat_answer_says_check_before_applying(paths, monkeypatch):
    websearch.save({"found_at": "2026-10-25T23:24", "provider": "Firecrawl (keyless search)", "results": [
        websearch.asdict(websearch.extract("Sophomore Science Award", "https://example.org/award", PAGE)),
        websearch.asdict(websearch.extract("Emergency Help", "https://example.org/help", "Emergency grants."))]},
        websearch.SAVED)
    monkeypatch.setattr(config, "ANSWER_MODE", "replay")
    llm = FakeLLM(plans=['{"calls": [{"tool": "search_scholarships", "args": {}}]}'],
                  explain_error=llm_client.LLMError("down"))
    a = list(agent.run("Find me scholarships online", engine.Scenario(), mode="live", llm=llm, typing_s=0))[-1][1]
    assert a.explain_source == "template" and a.check["ok"], a.check
    assert "Check before applying" in a.text and "$2,500" in a.text and "Mon, Mar 1, 2027" in a.text
    assert "https://example.org/help" in a.text and "see website" in a.text
    assert "qualify for" not in a.text.lower()


def test_checker_rejects_you_qualify():
    assert agent.web_claim_problems("Good news: you qualify for the Sophomore Science Award.")
    assert agent.web_claim_problems("You are eligible for it [E2].")
    assert not agent.web_claim_problems("Check before applying: read who can apply.")


def test_planner_fallback_routes_online_searches():
    assert agent.keyword_plan("Find me scholarships online", []).tool == "search_scholarships"
    assert agent.keyword_plan("What grants can I get?", []).tool == "find_aid"


def test_find_money_tab_shows_the_saved_set_without_searching(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(config, "DATA_BACKEND", "local")
    monkeypatch.setattr(config, "ANSWER_MODE", "replay")
    monkeypatch.setattr(websearch, "_post", lambda *a, **k: pytest.fail("no live search on page load"))
    at = AppTest.from_file("../ui/app.py", default_timeout=90)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    texts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    assert any("Found online - check before applying" in t for t in texts)
    assert any("scholarshipamerica.org" in t and "December 15, 2026" in t for t in texts)
    assert any(t.startswith("Found Sun, Oct 25 at 11:24 PM with Firecrawl") for t in texts)
    web = [t for t in texts if "scholarshipamerica.org" in t or t.startswith("Found Sun, Oct 25")]
    assert web and not any("qualify" in t.lower() for t in web)       # the school list may say it; online never
