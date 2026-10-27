"""The official H-MEM conformance suite (engines/hmem/conformance in github.com/Meterless/Meterless), run against
PocketMoney's hmem.py: the unchanged vectors.json and a Python port of runner.ts, one test per vector id. A green run is
the spec's definition of done ("An implementation is done when this suite is green")."""
import json
import math
from pathlib import Path

import pytest

from hmem import HMEM

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "hmem_conformance" / "vectors.json").read_text())
T0 = VECTORS["clock"]
DAY = 24 * 60 * 60 * 1000


def cases(section):
    return pytest.mark.parametrize("c", VECTORS["sections"][section], ids=lambda c: c["id"])


def approx(a, b, eps=1e-9):
    return a is not None and abs(a - b) < eps


@cases("record-validation")
def test_record_validation(c):
    hmem = HMEM(clock=lambda: T0)
    try:
        hmem.add(content=c["input"]["content"], source=c["input"]["source"])
        rejected = False
    except Exception:
        rejected = True
    assert rejected == (c["expect"] == "reject"), c["description"]


@cases("feedback-deltas")
def test_feedback_deltas(c):
    hmem = HMEM(clock=lambda: T0)
    m = hmem.add(content="feedback target record", confidence=c["start"], source="conformance")
    access_before = m.access_count
    hmem.feedback(m.id, c["kind"])
    after = hmem.store.get(m.id)
    assert approx(after.confidence, c["expectConfidence"]), (after.confidence, c["description"])
    if "expectAccessDelta" in c:
        assert after.access_count - access_before == c["expectAccessDelta"]
    if c.get("expectTag"):
        assert c["expectTag"] in after.tags


@cases("ranking-order")
def test_ranking_order(c):
    hmem = HMEM(clock=lambda: T0)
    by_key = {r["key"]: hmem.add(content=r["content"], confidence=r["confidence"], layer=r["layer"],
                                 source="conformance") for r in c["records"]}
    for r in c["records"]:
        if r.get("supersededByKey"):
            by_key[r["key"]].superseded_by = by_key[r["supersededByKey"]].id
    order = [rm.memory.id for rm in hmem.query(c["query"], threshold=0, top_n=10).memories]
    expected = [by_key[k].id for k in c["expectOrder"]]
    for a, b in zip(expected, expected[1:]):
        assert order.index(a) < order.index(b), (c["description"], order)


@cases("sleep-guardrails")
def test_sleep_guardrails(c):
    now = [T0]
    hmem = HMEM(clock=lambda: now[0])
    by_key = {r["key"]: hmem.add(content=r["content"], source=r["source"], derived_from=r.get("derivedFrom"))
              for r in c["records"]}
    now[0] = T0 + c["ageDays"] * DAY
    before = sorted(m.id for m in hmem.store.all())
    preview = hmem.sleep.preview()
    assert sorted(m.id for m in hmem.store.all()) == before, "preview mutated the store"
    for k in c["expectArchived"]:
        assert by_key[k].id in preview["toArchive"], f"{k} should be archivable"
    for k in c["expectProtected"]:
        assert by_key[k].id not in preview["toArchive"], f"{k} is guardrail-protected and must not archive"
    report = hmem.sleep.execute(preview)
    for k in c["expectProtected"]:
        assert hmem.store.get(by_key[k].id) is not None, f"{k} was deleted despite guardrails"
    assert isinstance(report["backupId"], str) and report["backupId"], "execute must return a backupId"


@cases("conflict-gate")
def test_conflict_gate(c):
    hmem = HMEM(clock=lambda: T0)
    a = hmem.add(content=c["a"]["content"], confidence=c["a"]["confidence"], source="conformance")
    b = hmem.add(content=c["b"]["content"], confidence=c["b"]["confidence"], source="conformance")
    found = hmem.conflicts.scan()
    assert found, "opposing always/never pair on similar content must be detected"
    outcome = hmem.conflicts.auto_resolve(found[0])
    assert outcome in ("resolved", "queued")
    if outcome == "resolved":
        assert any(m.superseded_by for m in (hmem.store.get(a.id), hmem.store.get(b.id))), \
            "resolved conflicts must mark the loser supersededBy"
    assert hmem.store.get(a.id) and hmem.store.get(b.id), "conflict resolution must never delete records"


@cases("ledger-audit")
def test_ledger_audit(c):
    hmem = HMEM(clock=lambda: T0)
    m = hmem.add(content="audited record", confidence=c["start"], source="conformance")
    hmem.feedback(m.id, c["kind"])
    history = hmem.ledger.history(m.id)
    assert [h["action"] for h in history] == c["expectActions"]
    fb = history[-1]
    assert approx(fb.get("previousState", {}).get("confidence"), c["expectPrev"])
    assert approx(fb.get("newState", {}).get("confidence"), c["expectNew"])


@cases("dream-boundary")
def test_dream_boundary(c):
    hmem = HMEM(clock=lambda: T0)
    for r in c["records"]:
        hmem.add(content=r["content"], type=r["type"], source="conformance")
    count_before = len(hmem.store.all())
    proposals = hmem.dreaming.dream()
    assert proposals, "two related preferences must produce at least one proposal"
    assert len(hmem.store.all()) == count_before, "dreaming must not materialize anything before approval"
    created = hmem.dreaming.approve(proposals[0]["id"])
    if created:
        assert created.layer == "long_term", "approved proposals materialize as long_term"
        assert created.derived_from, "approved proposals carry derivedFrom lineage"


def test_every_section_of_the_official_suite_is_covered():
    assert set(VECTORS["sections"]) == {"record-validation", "feedback-deltas", "ranking-order", "sleep-guardrails",
                                        "conflict-gate", "ledger-audit", "dream-boundary"}
    assert sum(len(v) for v in VECTORS["sections"].values()) == 13
