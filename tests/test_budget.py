"""Budgets: spending by category (ties out to the transactions), fixed vs flexible, money left after fixed bills,
the suggested budget, and the budget in the forecast. Deterministic, no network."""
from datetime import date
from decimal import Decimal

import pytest

import config
import engine
import normalize

FORM_SENT = engine.Scenario(refund_released=True, refund_submit_date=config.DEMO_TODAY)


@pytest.fixture(scope="module")
def ds():
    return normalize.load("local")


def test_fixed_and_flexible_cover_every_spending_category():
    assert normalize.FIXED == ("Rent", "Subscriptions", "Bills & utilities", "Fees", "School")
    assert normalize.FLEXIBLE == ("Groceries", "Eating out", "Meal plan", "Shopping", "Entertainment",
                                  "Transportation", "Other")
    assert set(normalize.FIXED) | set(normalize.FLEXIBLE) == set(normalize.SPENDING_OUT)


@pytest.mark.parametrize("start,end,account", [("2026-10-01", "2026-10-31", "both"), ("2026-08-01", "2026-08-31", "card"),
                                               ("2026-08-24", "2026-10-26", "checking")])
def test_category_totals_tie_out_to_the_transactions(ds, start, end, account):
    sp = engine.spending_by_category(start, end, account, ds)
    s, e = date.fromisoformat(start), min(date.fromisoformat(end), config.DEMO_TODAY)
    txns = [t for t in (ds.checking_txns + ds.card_txns if account == "both" else ds.txns(account))
            if s <= t.date <= e and t.amount < 0 and t.spending_category != normalize.TRANSFER]
    assert sp.count == len(txns) == sum(len(c.txns) for c in sp.categories)
    assert {t.row_id for c in sp.categories for t in c.txns} == {t.row_id for t in txns}
    for c in sp.categories:
        assert c.spent.value == -sum(t.amount for t in c.txns) and c.spent.inputs == [t.row_id for t in c.txns]
        assert all(t.spending_category == c.name for t in c.txns)
        assert c.kind == ("fixed" if c.name in normalize.FIXED else "flexible")
    assert sp.total.value == sum(c.spent.value for c in sp.categories)
    assert [c.spent.value for c in sp.categories] == sorted((c.spent.value for c in sp.categories), reverse=True)


def test_october_by_category(ds):
    sp = engine.spending_by_category("2026-10-01", "2026-10-31", "both", ds)
    assert sp.end == date(2026, 10, 26) and sp.total.value == Decimal("1756.78") and sp.count == 21
    assert [(c.name, c.spent.value) for c in sp.categories] == [
        ("Rent", Decimal("725.00")), ("Shopping", Decimal("460.99")), ("School", Decimal("200.00")),
        ("Groceries", Decimal("176.49")), ("Eating out", Decimal("81.32")), ("Bills & utilities", Decimal("55.00")),
        ("Fees", Decimal("35.00")), ("Subscriptions", Decimal("22.98"))]
    assert all(t.spending_category != normalize.TRANSFER for c in sp.categories for t in c.txns)


def test_money_to_budget_november(ds):
    m = engine.money_to_budget("2026-11", engine.Scenario(), ds)
    assert m.money_in.value == Decimal("516.15")                    # paychecks Nov 3 $401.45 + Nov 18 $114.70
    assert m.fixed.value == Decimal("1002.98")    # rent 725 + tuition 200 + Venmo 55 + Spotify 11.99 + Apple Music 10.99
    assert m.amount.value == Decimal("-486.83")
    assert not any("card statement" in label for label, *_ in m.lines)        # card payments aren't fixed bills
    sent = engine.money_to_budget("2026-11", FORM_SENT, ds)
    assert sent.money_in.value == Decimal("2366.15") and sent.amount.value == Decimal("1363.17")   # + the $1,850 refund
    spotify = engine.money_to_budget("2026-11", engine.Scenario(cancel_subscriptions=("Spotify",)), ds)
    assert spotify.fixed.value == Decimal("990.99")


def test_suggest_budget_is_her_average_when_it_fits(ds):
    sg = engine.suggest_budget("2026-11", FORM_SENT, ds)
    assert sg.fits and sg.available.amount.value == Decimal("1363.17")
    # Aug 1 to Oct 26 is 87 days; a 30-day month: Shopping $659.47 / 87 x 30 = $227.40 -> $227
    assert sg.amounts() == {"Shopping": Decimal("227.00"), "Groceries": Decimal("185.00"),
                            "Eating out": Decimal("96.00"), "Transportation": Decimal("14.00")}
    assert sg.total.value == Decimal("522.00") == sg.average_total.value
    assert set(sg.amounts()) <= set(normalize.FLEXIBLE)


def test_suggest_budget_scales_down_to_fit(ds, monkeypatch):
    real = engine.money_to_budget

    def tight(month, scenario=None, ds=None, ledger=None):
        m = real(month, scenario, ds, ledger)
        m.amount.value = Decimal("300.00")
        return m

    monkeypatch.setattr(engine, "money_to_budget", tight)
    sg = engine.suggest_budget("2026-11", engine.Scenario(), ds)
    assert sg.fits and sg.total.value <= Decimal("300.00")
    scale = Decimal("300.00") / Decimal("522.00")
    for x in sg.lines:
        assert x.suggested.value == (x.average.value * scale).quantize(Decimal("1"), rounding="ROUND_DOWN")
    assert sg.amounts()["Shopping"] == Decimal("130.00")                        # 227 x 0.5747, rounded down


def test_suggest_budget_when_nothing_is_left(ds):
    sg = engine.suggest_budget("2026-11", engine.Scenario(), ds)
    assert not sg.fits and sg.total.value == 0 and all(x.average.value > 0 for x in sg.lines)
