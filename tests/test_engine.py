"""engine: reproduces the answer key to the cent (local backend, no network, no LLM)."""
import json
from datetime import date
from decimal import Decimal

import pytest

import config
import engine as e
import normalize

FLIGHT = e.Purchase(Decimal("400.00"), date(2026, 11, 10), "checking", "flight home")


@pytest.fixture(scope="module")
def ds():
    return normalize.load("local")


@pytest.fixture(scope="module")
def key():
    k = json.loads((config.DATA_DIR / "answer_key.json").read_text(encoding="utf-8"))
    return {s["id"]: s for s in k["stories"]}


def rows_by_table(ds, row_ids):
    out = {}
    for rid in row_ids:
        r = ds.row(rid)
        out.setdefault((r.source, r.table), set()).add(rid)
    return out


def key_rows(story):
    out = {}
    for ev in story["evidence"]:
        out.setdefault((ev["source"], ev["table"]), set()).update(ev["row_ids"])
    return out


# --- projection inputs -----------------------------------------------------------------------

def test_projection_inputs(ds, key):
    inputs = key[5]["projection_inputs"]
    p = e.project(ds=ds)
    assert p.start_balance.value == Decimal("783.38") == Decimal(key[5]["key_numbers"]["start_balance_oct_26"])
    assert p.checking_rate.value == Decimal("7.51") == Decimal(inputs["checking_variable_per_day"])
    assert p.card_rate.value == Decimal("3.23") == Decimal(inputs["card_variable_per_day"])
    autopays = {c.pay_date: c.amount.value for c in p.cycles}
    assert autopays[date(2026, 11, 9)] == Decimal("359.53") == Decimal(inputs["card_autopay_nov_9"])
    assert autopays[date(2026, 12, 7)] == Decimal("285.22") == Decimal(inputs["card_statement_nov_12_projected"])
    assert e.refund_release_date(ds, e.Scenario()) == date(2026, 11, 5)
    assert key[5]["key_numbers"]["refund_date_if_released"] == "2026-11-05"


SCENARIOS = {
    "no_refund_no_cancel": (e.Scenario(purchases=(FLIGHT,)), "-1862.37", "2026-12-17"),
    "refund_only": (e.Scenario(refund_released=True, purchases=(FLIGHT,)), "-12.37", "2026-12-17"),
    "cancel_spotify_only": (e.Scenario(cancel_subscriptions=("Spotify",), purchases=(FLIGHT,)), "-1838.39", "2026-12-17"),
    "refund_and_cancel_spotify": (e.Scenario(refund_released=True, cancel_subscriptions=("Spotify",),
                                             purchases=(FLIGHT,)), "5.81", "2026-11-02"),
    "no_flight_no_refund": (e.Scenario(), "-1462.37", "2026-12-17"),
}


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_minimums(ds, key, name):
    scenario, low, low_date = SCENARIOS[name]
    expected = key[5]["key_numbers"]["scenarios"][name]
    p = e.project(scenario, ds)
    assert (str(p.lowest.value), p.lowest_date.value.isoformat()) == (low, low_date)
    assert (expected["min_balance"], expected["min_date"]) == (low, low_date)
    if "balance_dec_18" in expected:
        assert str(p.end_balance.value) == expected["balance_dec_18"]


def test_results_shape(ds):
    p = e.project(ds=ds)
    assert p.daily[0][0] == date(2026, 10, 27) and p.daily[-1][0] == config.SEMESTER_END
    assert p.first_below_zero.value == date(2026, 11, 9)      # the Nov 9 card autopay
    assert p.runway_weeks.value == Decimal("2.0")            # 14 days
    both = e.project(SCENARIOS["refund_and_cancel_spotify"][0], ds)
    assert both.first_below_zero.value is None and both.lasts_through_semester
    assert both.runway_weeks.value == Decimal("7.5")         # 53 days to Dec 18


# --- affordability and timing-aware savings --------------------------------------------------

def test_flight_is_yes_if_refund_and_spotify(ds):
    a = e.can_afford("400.00", "2026-11-10", "checking", ds=ds)
    assert a.verdict == "yes_if"
    assert sorted(f.name for f in a.fixes) == ["Spotify", "refund released"]
    assert a.alternatives == []
    assert a.with_fixes.lowest.value == Decimal("5.81")
    savings = {f.name: f.savings.value for f in a.considered}
    assert savings == {"refund released": Decimal("1850.00"), "Spotify": Decimal("23.98"),
                       "Apple Music": Decimal("0.00")}


@pytest.mark.parametrize("merchant", ["Spotify", "Apple Music"])
def test_subscription_savings_match_projection(ds, merchant):
    sub = next(s for s in e.subscriptions(ds) if s.merchant == merchant)
    saved = e.subscription_savings(sub, ds, e.Ledger()).value
    diff = e.project(e.Scenario(cancel_subscriptions=(merchant,)), ds).end_balance.value - e.project(ds=ds).end_balance.value
    assert saved == diff


def test_apple_music_next_charge_is_paid_after_semester(ds):
    p = e.project(ds=ds)
    cycle = next(c for c in p.cycles if c.start <= date(2026, 11, 22) <= c.closing)
    assert cycle.pay_date == date(2027, 1, 7)


def test_affordability_yes_and_no(ds):
    assert e.can_afford("20.00", "2026-11-10", ds=ds, scenario=e.Scenario(refund_released=True)).verdict == "yes"
    assert e.can_afford("5000.00", "2026-11-10", ds=ds).verdict == "no"


def test_card_purchase_lands_in_its_cycle(ds):
    base = e.project(ds=ds)
    card = e.project(e.Scenario(purchases=(e.Purchase(Decimal("400"), date(2026, 11, 10), "card"),)), ds)
    assert card.balance_on("2026-12-06") == base.balance_on("2026-12-06")
    assert card.balance_on("2026-12-07") == base.balance_on("2026-12-07") - Decimal("400.00")


def test_extra_shift_adds_net_pay_on_pay_date(ds):
    base = e.project(ds=ds)
    more = e.project(e.Scenario(extra_shifts=(e.ExtraShift(date(2026, 11, 4), Decimal("4")),)), ds)
    # Nov 1-15 goes from 8 to 12 hours: net 114.70 -> 172.05, paid Wed Nov 18
    assert more.balance_on("2026-11-17") == base.balance_on("2026-11-17")
    assert more.balance_on("2026-11-18") - base.balance_on("2026-11-18") == Decimal("57.35")


def test_scenario_from_dict_and_validation():
    s = e.scenario_from_dict({"refund_released": True, "cancel_subscriptions": ["Spotify"],
                              "purchases": [{"cost": "400", "date": "2026-11-10"}]})
    assert s.refund_released and s.purchases[0].account == "checking"
    with pytest.raises(ValueError):
        e.Scenario(purchases=(e.Purchase(Decimal("10"), date(2026, 10, 1)),))   # in the past


def test_pay_date_rule_matches_pay_periods(ds):
    for p in ds.pay_periods:
        assert e.pay_period_for(p.start) == (p.start, p.end, p.pay_date), p.row_id


def test_computed_inputs_are_traceable(ds):
    a = e.can_afford("400.00", "2026-11-10", ds=ds)
    seen = set()
    for c in a.ledger.items:
        for i in c.inputs:
            assert i in seen or ds.row(i), f"{c.id} cites unknown input {i}"
        seen.add(c.id)
    assert all(c.how for c in a.ledger.items)


# --- stories 1-4 -----------------------------------------------------------------------------

def test_story1_refund_hold(ds, key):
    f = e.refund_status(ds=ds)
    kn = key[1]["key_numbers"]
    for k in ("refund_amount", "pell_held", "fall_charges", "aid_disbursed"):
        assert str(f.computed[k].value) == kn[k], k
    assert f.computed["hold_since"].value.isoformat() == kn["hold_since"]
    assert f.computed["release_rule_business_days"].value == kn["release_rule_business_days"]
    assert {k: set(v) for k, v in f.row_ids.items()} == key_rows(key[1])


def test_story2_duplicate_subscriptions(ds, key):
    leak = next(l for l in e.find_leaks(ds=ds) if l.kind == "duplicate_subscriptions")
    vals = {c.label: c.value for c in leak.computed}
    kn = key[2]["key_numbers"]
    assert str(vals["Spotify monthly cost"]) == kn["spotify_monthly"]
    assert str(vals["Apple Music monthly cost"]) == kn["apple_music_monthly"]
    assert str(vals["combined monthly cost of music streaming subscriptions"]) == kn["combined_monthly"]
    assert vals["Spotify billing day"] == kn["spotify_day"] and vals["Apple Music billing day"] == kn["apple_music_day"]
    assert vals["which music streaming subscription to cancel"] == "Spotify"
    assert rows_by_table(ds, leak.row_ids) == key_rows(key[2])


def test_story3_overdraft_fee(ds, key):
    leak = next(l for l in e.find_leaks(ds=ds) if l.kind == "fee")
    vals = [c.value for c in leak.computed]
    kn = key[3]["key_numbers"]
    for k in ("balance_sep_30", "rent", "balance_after_rent", "overdraft_fee", "paycheck_oct_2"):
        assert Decimal(kn[k]) in vals, k
    assert kn["rent_due_day"] in vals
    assert rows_by_table(ds, leak.row_ids) == key_rows(key[3])


def test_story4_installment_in_short_paycheck_week(ds, key):
    (f,) = e.cash_crunches(ds=ds)
    kn = key[4]["key_numbers"]
    assert str(f.computed["installment"].value) == kn["installment"]
    assert f.computed["installment_due"].value.isoformat() == kn["installment_due"]
    assert f.computed["paycheck_date"].value.isoformat() == kn["paycheck_date"]
    assert str(f.computed["scheduled_hours"].value) == kn["nov_1_15_scheduled_hours"]
    assert str(f.computed["normal_period_hours"].value) == kn["normal_period_hours"]
    assert str(f.computed["hourly_rate"].value) == kn["hourly_rate"]
    assert str(f.computed["withholding_pct"].value) == kn["withholding_pct"]
    assert {k: set(v) for k, v in f.row_ids.items()} == key_rows(key[4])


def test_compare_gives_what_if_deltas(ds):
    ledger = e.Ledger()
    base = e.project(e.Scenario(), ds, ledger)
    cur = e.project(SCENARIOS["refund_and_cancel_spotify"][0], ds, ledger)
    d = e.compare(base, cur, ledger)
    assert d["lowest"].value == Decimal("5.81") - Decimal("-1462.37")
    assert d["end_balance"].value == Decimal("61.45") - Decimal("-1412.53")
    assert d["runway_weeks"].value == Decimal("5.5")
    assert set(d["lowest"].inputs) == {cur.lowest.id, base.lowest.id}


def test_subscription_timing(ds):
    subs = {s.merchant: s for s in e.subscriptions(ds)}
    assert e.subscription_timing(subs["Apple Music"], ds)[0] == (date(2026, 11, 22), date(2027, 1, 7))
    assert e.subscription_timing(subs["Spotify"], ds)[:2] == [(date(2026, 11, 14),) * 2, (date(2026, 12, 14),) * 2]


def test_main_reason(ds):
    r = e.main_reason(e.project(ds=ds))
    assert (r.date, r.event.kind, r.event.amount, r.balance_before) == \
        (date(2026, 11, 9), "card_autopay", Decimal("-359.53"), Decimal("307.20"))
    r = e.main_reason(e.project(SCENARIOS["refund_and_cancel_spotify"][0], ds))
    assert (r.date, r.event.kind, r.event.date) == (date(2026, 11, 2), "rent", date(2026, 11, 1))


def test_extra_shift_pay(ds):
    pay, added = e.extra_shift_pay(e.ExtraShift(date(2026, 11, 4), Decimal("4")), ds)
    assert (pay, added.value) == (date(2026, 11, 18), Decimal("57.35"))
    pay, added = e.extra_shift_pay(e.ExtraShift(date(2026, 12, 17), Decimal("4")), ds)
    assert pay > config.SEMESTER_END and added.value == Decimal("0.00")


def test_latest_shift_paid_before_run_out(ds):
    shift, pay = e.latest_shift_paid_before(date(2026, 11, 9), ds)
    assert (shift.value, pay.value) == (date(2026, 10, 31), date(2026, 11, 3))     # Sat Oct 31 -> Tue Nov 3
    assert "PAY-05" in shift.inputs and "JOB-01" in shift.inputs
    assert e.latest_shift_paid_before(date(2026, 10, 28), ds) is None              # nothing is paid that soon
    shift, pay = e.latest_shift_paid_before(date(2026, 11, 20), ds)
    assert (shift.value, pay.value) == (date(2026, 11, 15), date(2026, 11, 18))
