"""Runway's memory on H-MEM (runway_memory.py, ui/memory.py): persisted across sessions with provenance and an
audit ledger, superseded (not deleted) when something changes, recalled into PLAN only (never EXPLAIN), forgettable,
and used by the check-in in a later session."""
import json

import pytest
from streamlit.testing.v1 import AppTest

import agent
import config
import engine
import normalize
import runway_memory
from test_agent import FLIGHT_PLAN, GOOD_FLIGHT
from test_chat import RecordingLLM

Q17 = "Can I afford the flight on Nov 17?"


@pytest.fixture
def mem(tmp_path):
    return runway_memory.RunwayMemory(persist_dir=tmp_path / "mem")


def test_memories_persist_across_sessions_with_provenance_and_a_ledger(tmp_path):
    first = runway_memory.RunwayMemory(persist_dir=tmp_path / "m")
    first.remember_done("refund", "Form sent", "Send your verification form")
    first.remember_conversation("Can I afford a $400 flight home if I book it Nov 10?", "Yes, if you do 2 things.")
    again = runway_memory.RunwayMemory(persist_dir=tmp_path / "m")                     # a new session
    items = again.items()
    assert [m.content for m in items] == ["Asked “Can I afford a $400 flight home if I book it Nov 10?” "
                                          "Runway: “Yes, if you do 2 things.”",
                                          "Marked done: Form sent (Send your verification form)."]
    done = items[1]
    assert done.layer == "long_term" and done.source == "checkin:done" and "item:refund" in done.tags
    assert done.provenance["origin"] == "manual" and done.provenance["label"].startswith("You clicked")
    assert items[0].layer == "short_term" and items[0].provenance["origin"] == "model_response"
    assert [e["action"] for e in again.engine.ledger.all()] == ["create", "create"]
    assert (tmp_path / "m" / "state.json").exists() and (tmp_path / "m" / "ledger.jsonl").exists()


def test_a_new_budget_supersedes_the_old_one_which_is_kept(mem):
    old = mem.remember_budget({"Groceries": 185, "Shopping": 227})
    new = mem.remember_budget({"Groceries": 160, "Shopping": 227})
    assert mem.remember_budget({"Groceries": 160, "Shopping": 227}).id == new.id          # unchanged: no new record
    assert [m.content for m in mem.items()] == ["Monthly budget: Groceries $160, Shopping $227."]
    kept = mem.engine.store.get(old.id)
    assert kept.superseded_by == new.id and new.supersedes == old.id                    # kept, penalised
    assert [e["action"] for e in mem.engine.ledger.history(old.id)] == ["create", "update"]


def test_undo_supersedes_the_done_memory(mem):
    d = mem.remember_done("refund", "Form sent", "Send your verification form")
    mem.remember_undone("refund", "Form sent", "Send your verification form")
    assert mem.engine.store.get(d.id).superseded_by and mem.done_before("refund", 10 ** 15) is None


def test_recall_ranks_the_right_memory_first(mem):
    mem.remember_intent("refund", "Opened the email draft: Verification worksheet for my aid file")
    mem.remember_budget({"Groceries": 160, "Eating out": 96})
    mem.remember_conversation("Can I afford a $400 flight home for Thanksgiving if I book it Nov 10?",
                              "Yes, if you do 2 things.")
    r = mem.engine.query(Q17, top_n=3, threshold=runway_memory.PLAN_THRESHOLD)
    assert r.memories and "flight" in r.memories[0].memory.content
    assert r.context.startswith("[MEMORY CONTEXT]") and r.trace["retrievalReason"].startswith("hybrid ranking")
    budget = mem.engine.query("How much is left in my food budget?", top_n=3, threshold=0, touch=False)
    assert budget.memories[0].memory.content.startswith("Monthly budget")


def test_memories_reach_plan_but_never_explain(mem, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ANSWER_CACHE_DIR", tmp_path / "answers")
    mem.remember_conversation("Can I afford a $400 flight home for Thanksgiving if I book it Nov 10?",
                              "Yes, if you do 2 things.")
    recall = mem.engine.query(Q17, top_n=3, threshold=runway_memory.PLAN_THRESHOLD)
    llm = RecordingLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT])
    a = agent.ask(Q17, engine.Scenario(), ds=normalize.load(), mode="live", llm=llm, typing_s=0, memory=recall)
    plan_prompt = json.dumps(llm.plan_messages[0])
    assert "What Runway remembers from earlier sessions (H-MEM)" in plan_prompt and "[MEMORY CONTEXT]" in plan_prompt
    assert all("MEMORY CONTEXT" not in json.dumps(m) for _, m in llm.messages)        # EXPLAIN: evidence only
    assert a.models["memories"][0]["content"].startswith("Asked")
    trace = json.loads((config.LOGS_DIR / "traces.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert trace["memories_recalled_for_plan"][0]["id"] == recall.memories[0].memory.id


def test_her_own_data_never_uses_memory(mem, tmp_path, monkeypatch):
    mem.remember_conversation("Can I afford a $400 flight home?", "Yes, if you do 2 things.")
    recall = mem.engine.query("Can I afford the flight?", top_n=3, threshold=0)
    llm = RecordingLLM(plans=[FLIGHT_PLAN], answers=[GOOD_FLIGHT])
    agent.ask("Can I afford the flight?", engine.Scenario(), ds=normalize.load(), mode="live", llm=llm, typing_s=0,
              memory=recall, private=True)
    assert "MEMORY CONTEXT" not in json.dumps(llm.plan_messages[0])


def test_forget_one_mark_wrong_and_forget_everything_are_logged(mem):
    a = mem.remember_preference("Prefers fast answers.", "think")
    b = mem.remember_done("refund", "Form sent", "Send your verification form")
    mem.mark_wrong(b.id)
    assert "review" in mem.engine.store.get(b.id).tags and mem.engine.store.get(b.id).confidence == pytest.approx(0.5)
    mem.forget(a.id)
    assert [m.id for m in mem.items()] == [b.id]
    mem.forget_all()
    assert mem.items() == []
    assert mem.engine.ledger.stats()["delete"] == 2 and mem.engine.ledger.stats()["feedback"] == 1


def test_the_check_in_remembers_across_sessions(monkeypatch):
    monkeypatch.setattr(config, "DATA_BACKEND", "local")
    first = AppTest.from_file("../ui/app.py", default_timeout=60)
    first.run()
    first.button(key="ci_done_refund").click()
    first.run()
    assert not first.exception
    second = AppTest.from_file("../ui/app.py", default_timeout=60)                    # a new session, same computer
    second.run()
    texts = [m.value for m in second.markdown]
    assert any("Last time you clicked “Form sent”. Still true? Click it again." in t for t in texts)
    remembers = next(e for e in second.expander if e.label.startswith("What Runway remembers"))
    assert remembers.label == "What Runway remembers (1)"
    assert any("Marked done: Form sent (Send your verification form)." in m.value for m in remembers.markdown)
