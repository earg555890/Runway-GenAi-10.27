"""data_access: named queries cover the answer key (local backend), validation, cache, and Zetaris parity."""
import json
import socket
import time

import pytest

import config
import data_access as da

SEMESTER_HISTORY = {"start_date": "2026-07-01", "end_date": "2026-12-31"}

# Which named query (and parameters) retrieves each kind of answer-key evidence.
EVIDENCE_QUERY = {
    ("checking", "account"): ("checking_account", {}),
    ("checking", "transactions"): ("checking_transactions", SEMESTER_HISTORY),
    ("card", "transactions"): ("card_transactions", SEMESTER_HISTORY),
    ("card", "statements"): ("card_statements", {}),
    ("aid", "disbursements"): ("aid_disbursements", {}),
    ("aid", "requirements"): ("aid_requirements", {}),
    ("bursar", "ledger"): ("bursar_ledger", {"term": "FA26"}),
    ("bursar", "holds"): ("bursar_active_holds", {}),
    ("bursar", "refunds"): ("bursar_refunds", {}),
    ("bursar", "payment_plan"): ("bursar_payment_plan", {}),
    ("lease", "lease_terms"): ("lease_terms", {}),
    ("lease", "rent_schedule"): ("rent_schedule", {}),
    ("shifts", "job"): ("job_info", {}),
    ("shifts", "pay_periods"): ("pay_periods", {}),
    ("shifts", "shifts"): ("shifts", SEMESTER_HISTORY),
    ("opportunities", "opportunities"): ("aid_opportunities", {}),
    ("opportunities", "application_requirements"): ("opportunity_requirements", {}),
    ("opportunities", "student_profile"): ("student_profile", {}),
    ("meal_plan", "plan"): ("meal_plan", {}),
    ("meal_plan", "transactions"): ("meal_transactions", {"start_date": "2026-08-24", "end_date": "2026-10-26"}),
}

# Parameters used when every named query is run (parity, timings).
DEFAULT_PARAMS = {name: params for name, params in EVIDENCE_QUERY.values()}
DEFAULT_PARAMS["federated_recurring_charges"] = {}
DEFAULT_PARAMS["mydata_transactions"] = {}         # the student's own data: not in Maya's answer key, not in parity


def answer_key():
    return json.loads((config.DATA_DIR / "answer_key.json").read_text(encoding="utf-8"))


def evidence_items():
    for story in answer_key()["stories"]:
        for ev in story["evidence"]:
            yield pytest.param(story["id"], ev, id=f"story{story['id']}-{ev['source']}.{ev['table']}")


# --- local backend: every proof row is retrievable -------------------------------------------

def test_registry_covers_every_queried_table_and_all_queries_are_used():
    assert set(DEFAULT_PARAMS) == set(da.REGISTRY)


@pytest.mark.parametrize("story_id,ev", list(evidence_items()))
def test_answer_key_rows_retrievable_locally(story_id, ev):
    name, params = EVIDENCE_QUERY[(ev["source"], ev["table"])]
    result = da.run(name, backend="local", **params)
    missing = set(ev["row_ids"]) - set(result.evidence.row_ids)
    assert not missing, f"story {story_id}: {name} did not return {sorted(missing)}"


def test_federated_query_finds_both_music_subscriptions():
    story2 = next(s for s in answer_key()["stories"] if s["id"] == 2)
    proof = {rid for ev in story2["evidence"] for rid in ev["row_ids"]}
    result = da.run("federated_recurring_charges", backend="local")
    assert proof <= set(result.evidence.row_ids)
    assert {r["source"] for r in result.rows} == {"checking", "card"}
    assert result.evidence.sources == ["card", "checking"]


def test_evidence_record_is_complete():
    r = da.run("checking_transactions", backend="local", start_date="2026-10-01", end_date="2026-10-02")
    ev = r.evidence.to_dict()
    assert ev["query"] == "checking_transactions"
    assert ev["tables"] == ["checking/transactions.csv"]
    assert ev["sql"] == "checking/transactions.csv where posted_date between 2026-10-01 and 2026-10-02"
    assert ev["params"] == {"start_date": "2026-10-01", "end_date": "2026-10-02"}
    assert ev["row_ids"] == ["CHK-0042", "CHK-0043", "CHK-0044"]   # rent, overdraft fee, paycheck (story 3)
    assert ev["backend"] == "local"
    assert ev["duration_s"] >= 0


def test_catalog_lists_every_query_with_typed_params():
    cat = {q["name"]: q for q in da.catalog()}
    assert set(cat) == set(da.REGISTRY)
    assert cat["bursar_ledger"]["params"][0]["choices"] == ["SU26", "FA26"]
    assert [p["type"] for p in cat["shifts"]["params"]] == ["date", "date"]


# --- validation ------------------------------------------------------------------------------

@pytest.mark.parametrize("name,params,message", [
    ("no_such_query", {}, "unknown query"),
    ("checking_account", {"x": 1}, "unknown parameter"),
    ("shifts", {"start_date": "2026-10-01"}, "missing parameter end_date"),
    ("shifts", {"start_date": "10/01/2026", "end_date": "2026-10-31"}, "must be YYYY-MM-DD"),
    ("shifts", {"start_date": "2026-02-30", "end_date": "2026-03-01"}, "not a real date"),
    ("shifts", {"start_date": "2026-11-01", "end_date": "2026-10-01"}, "start_date is after end_date"),
    ("bursar_ledger", {"term": "FA26'; DROP"}, "must be one of"),
])
def test_bad_requests_are_rejected(name, params, message):
    with pytest.raises(ValueError, match=message):
        da.run(name, backend="local", **params)


# --- Zetaris cache (with a fake Zetaris; no network) ------------------------------------------

def test_zetaris_results_are_cached_by_name_and_params(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ZETARIS_CACHE_DIR", tmp_path)
    calls = []

    def fake_zetaris(q, sql):
        calls.append(sql)
        return ["REFUND_ID", "STATUS"], [{"REFUND_ID": "RFD-01", "STATUS": "HELD"}]

    monkeypatch.setattr(da, "_zetaris", fake_zetaris)
    first = da.run("bursar_refunds", backend="zetaris", use_cache=True)
    second = da.run("bursar_refunds", backend="zetaris", use_cache=True)
    assert len(calls) == 1
    assert first.evidence.backend == "zetaris"
    assert second.evidence.backend == "zetaris-cached"
    assert second.rows == first.rows
    assert second.evidence.sql == first.evidence.sql == "SELECT * FROM RUNWAY_BURSAR.refunds ORDER BY REFUND_ID"
    assert second.evidence.original_duration_s is not None
    da.run("bursar_refunds", backend="zetaris", use_cache=False)
    assert len(calls) == 2


def test_jvm_is_not_destroyed_at_exit():
    """The JVM's own shutdown waits for the (Streamlit script) thread that started it, so the app hung on exit."""
    import jpype.config
    import zetaris_db  # noqa: F401
    assert jpype.config.destroy_jvm is False


# --- parity: Zetaris vs local (skipped automatically when Zetaris is unreachable) -------------

def _zetaris_reachable():
    try:
        host_port = config.require("ZETARIS_JDBC_URL").rsplit("@", 1)[1]
        host, port = host_port.split(":")
        with socket.create_connection((host, int(port)), timeout=3):
            pass
        from zetaris_db import query
        return query("SELECT 1") == [(1,)]
    except Exception:
        return False


@pytest.fixture(scope="module")
def zetaris():
    if not _zetaris_reachable():
        pytest.skip("Zetaris is not reachable")


@pytest.mark.zetaris
@pytest.mark.parametrize("name", sorted(n for n in da.REGISTRY if n != "mydata_transactions"))
def test_zetaris_parity(zetaris, name):
    params = DEFAULT_PARAMS[name]
    start = time.perf_counter()
    z = da.run(name, backend="zetaris", use_cache=False, **params)
    elapsed = time.perf_counter() - start
    local = da.run(name, backend="local", **params)
    print(f"\n[zetaris timing] {name}: {elapsed:.2f}s, {len(z.rows)} rows")
    assert z.evidence.backend == "zetaris"
    assert z.evidence.row_ids == local.evidence.row_ids
    assert z.rows == local.rows


def test_is_cached_validates_and_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ZETARIS_CACHE_DIR", tmp_path)
    assert not da.is_cached("bursar_ledger", term="FA26")
    with pytest.raises(da.QueryError):
        da.is_cached("bursar_ledger", term="XX99")


def test_local_mode_never_starts_java():
    """The whole app in local mode (a fresh process) never imports the JDBC bridge, so no JVM starts."""
    import subprocess
    import sys
    from pathlib import Path
    code = ("import sys, config; config.DATA_BACKEND = 'local'; config.AI_GREETING = False\n"
            "from streamlit.testing.v1 import AppTest\n"
            "at = AppTest.from_file('ui/app.py', default_timeout=120); at.run()\n"
            "assert not at.exception\n"
            "print('jpype' in sys.modules, 'zetaris_db' in sys.modules)")
    root = Path(__file__).resolve().parent.parent
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=300)
    assert out.stdout.strip().splitlines()[-1] == "False False", out.stderr[-2000:]
