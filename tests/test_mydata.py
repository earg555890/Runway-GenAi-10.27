"""My data mode with the three FAKE bank exports: detection, signs, recurring items, the projection on her own dates,
every tab rendering, the agent's graceful answers, privacy (nothing in user_data/ is committed or cached), and Maya
mode unchanged. All files here are fake (tests/fixtures/fake_bank/README.txt)."""
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import agent
import config
import engine
import importer
import mydata

FAKE = Path(__file__).parent / "fixtures" / "fake_bank"
FILES = {"a": "fake_bank_a_amount.csv", "b": "fake_bank_b_debit_credit.csv", "c": "fake_bank_c_parens.csv"}


def text(key):
    return (FAKE / FILES[key]).read_text(encoding="utf-8")


@pytest.fixture
def userdir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USER_DATA_DIR", tmp_path / "user_data")
    monkeypatch.setattr(config, "ANSWER_CACHE_DIR", tmp_path / "answers")
    return tmp_path


def imported(key, balance=None):
    t = text(key)
    m = importer.detect(t)
    mydata.save(importer.normalize_rows(t, m), m, FILES[key], balance_today=balance, register=False)
    return mydata.dataset("local")


# --- detection --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("key,expect", [
    ("a", dict(date="Date", date_format="%m/%d/%Y", description="Description", amount="Amount", debit=None,
               credit=None, balance=None, sign="negative_out")),
    ("b", dict(date="Posting Date", date_format="%Y-%m-%d", description="Description", amount=None, debit="Debit",
               credit="Credit", balance="Balance", sign="debit_credit")),
    ("c", dict(date="Date", date_format="%d-%m-%Y", description="Payee", amount="Amount", debit=None, credit=None,
               balance="Running Balance", sign="negative_out")),
])
def test_detects_all_three_layouts(key, expect):
    m = importer.detect(text(key))
    assert {k: getattr(m, k) for k in expect} == expect
    rows = importer.normalize_rows(text(key), m)
    assert len(rows) == 55 and rows[0]["date"] == date(2026, 8, 1) and rows[-1]["date"] == date(2026, 10, 24)
    assert sum(r["amount"] for r in rows) == Decimal("-788.28")             # $1,200.00 -> $411.72
    rent = next(r for r in rows if "RENT" in r["description"])
    assert rent["amount"] == Decimal("-1050.00")
    pay = next(r for r in rows if "PAYROLL" in r["description"])
    assert pay["amount"] == Decimal("612.40")


def test_all_three_files_import_the_same_rows():
    a, b, c = (importer.normalize_rows(text(k), importer.detect(text(k))) for k in "abc")
    strip = lambda rows: [(r["date"], r["description"], r["amount"]) for r in rows]   # noqa: E731
    assert strip(a) == strip(b) == strip(c)
    assert b[-1]["balance"] == c[-1]["balance"] == Decimal("411.72")


def test_money_and_sign_handling():
    assert importer.money("(1,050.00)") == Decimal("-1050.00") and importer.money("$612.40") == Decimal("612.40")
    assert importer.money("45.10-") == Decimal("-45.10") and importer.money("12.00 DR") == Decimal("-12.00")
    assert importer.money("12.00 CR") == Decimal("12.00") and importer.money("-$5") == Decimal("-5")
    assert importer.money("") is None and importer.money("n/a") is None
    flipped = "Date,Description,Amount,Balance\n2026-10-01,Start,0.00,100.00\n2026-10-02,Coffee,4.50,95.50\n" \
              "2026-10-03,Pay,-50.00,145.50\n2026-10-04,Lunch,10.00,135.50\n"
    m = importer.detect(flipped)
    assert m.sign == "positive_out"                                        # the balance shows purchases are positive
    assert [r["amount"] for r in importer.normalize_rows(flipped, m)][1:] == \
        [Decimal("-4.50"), Decimal("50.00"), Decimal("-10.00")]


@pytest.mark.parametrize("bad,message", [
    ("hello,world\nfoo,bar\n", "date column"),
    ("Date,Description\n2026-10-01,Coffee\n2026-10-02,Tea\n", "amount column"),
    ("", "header row"),
])
def test_rejects_files_it_cant_understand(bad, message):
    with pytest.raises(importer.ImportProblem, match=message):
        importer.detect(bad)


# --- her data in the engine -------------------------------------------------------------------------------------

def test_recurring_and_projection(userdir):
    ds = imported("c")
    assert ds.checking_account.current_balance == Decimal("411.72")      # the latest running balance
    today, start, end = mydata.dates(ds)
    assert (today, start, end) == (date(2026, 10, 24), date(2026, 8, 1), config.SEMESTER_END)
    with config.as_of(today, start, end, start):
        recurring = {(r.merchant, r.category) for r in engine.recurring_items(ds)}
        assert {("Maple Court Apts Rent", "recurring_bill"), ("Netflix", "subscription"),
                ("Metro Wireless Bill", "recurring_bill")} <= recurring
        pay = engine.recurring_income(ds, engine.Ledger())
        assert [(d, a) for d, a, _, _ in pay] == [(date(2026, 10, 30), Decimal("612.40")),
                                                  (date(2026, 11, 13), Decimal("612.40")),
                                                  (date(2026, 11, 27), Decimal("612.40")),
                                                  (date(2026, 12, 11), Decimal("612.40"))]
        p = engine.project(engine.Scenario(), ds)
        assert p.first_below_zero.value == date(2026, 11, 1)             # $1,050 rent
        assert p.start_balance.value == Decimal("411.72")
        assert p.end_balance.value == p.start_balance.value + sum(e.amount for e in p.events) - \
            p.checking_rate.value * (end - today).days
        assert [a.kind for a in engine.attention_items(engine.Scenario(), ds)] == ["run_out"]


def test_typed_balance_when_the_file_has_none(userdir):
    ds = imported("a", balance=Decimal("411.72"))
    assert ds.checking_account.current_balance == Decimal("411.72")
    assert ds.checking_account.overdraft_rule == "Balance you typed in"


def test_the_agent_says_when_school_data_is_missing(userdir):
    from test_agent import FakeLLM
    ds = imported("c")
    today, start, end = mydata.dates(ds)
    llm = FakeLLM(plans=['{"calls": [{"tool": "refund_status", "args": {}}]}'], answers=[])
    with config.as_of(today, start, end, start):
        events = list(agent.run("Why is my refund on hold?", engine.Scenario(), ds=ds, mode="live", llm=llm,
                                typing_s=0, private=True))
    a = events[-1][1]
    assert a.text == agent.NOT_AVAILABLE and a.mode == "unavailable"
    assert not list((userdir / "answers").glob("*.json"))                 # never cached


def test_private_answers_are_never_cached(userdir):
    from test_agent import FakeLLM
    ds = imported("c")
    today, start, end = mydata.dates(ds)
    plan = '{"calls": [{"tool": "runway", "args": {}}]}'
    with config.as_of(today, start, end, start):
        events = list(agent.run("How long will my money last?", engine.Scenario(), ds=ds, mode="cached",
                                llm=FakeLLM(plans=[plan], answers=["x", "x"]), typing_s=0, private=True))
    a = events[-1][1]
    assert a.text.startswith("ANSWER: Your money runs out on Sun, Nov 1")
    assert not list((userdir / "answers").glob("*.json"))


# --- the app in My data mode ------------------------------------------------------------------------------------

def _app(monkeypatch):
    monkeypatch.setattr(config, "DATA_BACKEND", "local")
    at = AppTest.from_file("../ui/app.py", default_timeout=90)
    at.session_state["data_mode"] = "mine"
    at.run()
    if any(b.key == "chat_fab_btn" for b in at.button):          # no chat button on the import screen
        at.button(key="chat_fab_btn").click()
        at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _texts(at):
    return [m.value.replace("&#36;", "$").replace("\\$", "$") for m in at.markdown] + [c.value for c in at.caption] + \
        [i.value for i in at.info]


def test_every_tab_renders_in_my_data_mode(userdir, monkeypatch):
    imported("c")
    at = _app(monkeypatch)
    ts = _texts(at)
    assert [t.label for t in at.tabs] == ["Semester", "Budget", "Afford it?", "Find money", "Findings"]
    assert any(">Your money runs out in 1.1 weeks, on Sun, Nov 1.<" in t for t in ts)       # 8 days
    assert any(">Hi. See the ways to fix it below.<" in t for t in ts)        # run-out is the status card
    assert any("Connect your school data to see grants and scholarships" in t for t in ts)
    assert any("Connect your school data to see your financial aid" in t for t in ts)
    assert any("Connect your work schedule" in t for t in ts)
    assert any("Most went to Rent" in t for t in ts)                       # Budget tab, her categories
    assert [b.label for b in at.button if str(b.key).startswith("ask_suggest_")] == agent.MYDATA_SUGGESTED
    assert any("Your bank file" in t for t in ts) and not any("Maya's 8 data sources" in t for t in ts)
    notice = "Your questions go through Meterless Nightshift on this computer, which keeps a local log of requests."
    assert any(notice in t for t in ts) == (config.AI_PROVIDER == "meterless")
    assert not any(notice in t for t in _texts(_maya(monkeypatch)))                       # only in My data mode


def _maya(monkeypatch):
    monkeypatch.setattr(config, "DATA_BACKEND", "local")
    at = AppTest.from_file("../ui/app.py", default_timeout=90)
    at.run()
    return at


def test_import_screen_when_no_data(userdir, monkeypatch):
    at = _app(monkeypatch)
    assert any("Use your own bank data" in t for t in _texts(at))
    assert at.get("file_uploader")


def test_maya_mode_unchanged_after_using_my_data(userdir, monkeypatch):
    imported("c")
    at = _app(monkeypatch)
    at.segmented_control(key="data_mode").set_value("maya")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    status = next(t for t in _texts(at) if 'class="rw-status' in t)
    assert ">Your money runs out in 2 weeks, on Mon, Nov 9.<" in status
    assert config.DEMO_TODAY == date(2026, 10, 26) and config.SEMESTER_START == date(2026, 8, 24)


def test_nothing_from_user_data_is_ever_committed():
    root = Path(__file__).resolve().parent.parent
    tracked = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split()
    assert not [p for p in tracked if p.startswith("user_data/")]
    probe = subprocess.run(["git", "check-ignore", "user_data/mydata/transactions.csv"], cwd=root,
                           capture_output=True, text=True)
    assert probe.returncode == 0                                              # ignored
    assert "user_data/" in (root / ".gitignore").read_text(encoding="utf-8")
