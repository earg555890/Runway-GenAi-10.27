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
    assert m.start_balance.value == Decimal("745.83")                # projected checking at the end of Oct 31
    assert m.money_in.value == Decimal("516.15")                     # paychecks Nov 3 $401.45 + Nov 18 $114.70
    # rent 725 + tuition 200 + Venmo 55 + Spotify 11.99 + Apple Music 10.99 + the Oct 12 card statement (Nov 9) 359.53
    assert m.fixed.value == Decimal("1362.51")
    assert m.amount.value == Decimal("-100.53")                      # 745.83 + 516.15 - 1,362.51
    owed = [label for label, *_ in m.lines if label.startswith("card bill")]
    assert owed == ["card bill (statement closed 2026-10-12)"]       # the Dec 7 bill is still being built: not here
    sent = engine.money_to_budget("2026-11", FORM_SENT, ds)
    assert sent.money_in.value == Decimal("2366.15") and sent.amount.value == Decimal("1749.47")   # + the $1,850 refund
    spotify = engine.money_to_budget("2026-11", engine.Scenario(cancel_subscriptions=("Spotify",)), ds)
    assert spotify.fixed.value == Decimal("1350.52")


def test_suggest_budget_is_her_everyday_average_when_it_fits(ds):
    sg = engine.suggest_budget("2026-11", FORM_SENT, ds)
    assert sg.fits and sg.available.amount.value == Decimal("1749.47")
    # Aug 1 to Oct 26 is 87 days; a 30-day month. Shopping: $52.10 of everyday purchases (3 one-offs of $100+ left
    # out, like the forecast) / 87 x 30 = $17.97 -> $18
    assert sg.amounts() == {"Shopping": Decimal("18.00"), "Groceries": Decimal("185.00"),
                            "Eating out": Decimal("96.00"), "Transportation": Decimal("14.00")}
    assert "leaving out 3 one-off purchases of $100 or more" in sg.lines[0].average.how
    assert sg.total.value == Decimal("313.00") == sg.average_total.value
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
    scale = Decimal("300.00") / Decimal("313.00")
    for x in sg.lines:
        assert x.suggested.value == (x.average.value * scale).quantize(Decimal("1"), rounding="ROUND_DOWN")
    assert sg.amounts()["Groceries"] == Decimal("177.00")                     # 185 x 0.9585, rounded down


def test_suggest_budget_when_nothing_is_left(ds):
    sg = engine.suggest_budget("2026-11", engine.Scenario(), ds)
    assert not sg.fits and sg.total.value == 0 and all(x.average.value > 0 for x in sg.lines)


# --- the budget in the forecast ------------------------------------------------------------------------------

SUGGESTED = (("Shopping", Decimal("18.00")), ("Groceries", Decimal("185.00")), ("Eating out", Decimal("96.00")),
             ("Transportation", Decimal("14.00")))


def test_budget_replaces_the_average_and_ties_out(ds):
    from datetime import timedelta
    sc = engine.Scenario(budget=SUGGESTED)
    ledger = engine.Ledger()
    p = engine.project(sc, ds, ledger)
    rates = engine.budget_rates(sc, ds, engine.Ledger())
    assert rates[("checking", 2026, 11)].value == Decimal("7.50") and rates[("card", 2026, 11)].value == Decimal("2.93")
    # end balance = today's balance + every scheduled item - each day's budgeted checking spending, to the cent
    spent = sum(rates[("checking", d.year, d.month)].value for d in engine.days(config.DEMO_TODAY + timedelta(days=1),
                                                                                 config.SEMESTER_END))
    assert p.end_balance.value == p.start_balance.value + sum(e.amount for e in p.events) - spent
    # the Dec 7 card bill = card purchases already made in the cycle + each day's budgeted card spending
    cyc = next(c for c in p.cycles if c.statement_id is None)
    actual = -sum(t.amount for t in ds.card_txns if cyc.start <= t.date <= config.DEMO_TODAY
                  and t.category != "card_payment")
    budgeted = sum(rates[("card", d.year, d.month)].value
                   for d in engine.days(config.DEMO_TODAY + timedelta(days=1), cyc.closing))
    assert cyc.amount.value == actual + budgeted                     # Apple Music's next charge is after closing
    assert engine.project(engine.Scenario(), ds).end_balance.value == Decimal("-1412.53")      # no budget: unchanged


def test_budget_effect_direction(ds):
    sent = engine.budget_effect(engine.Scenario(refund_released=True, refund_submit_date=config.DEMO_TODAY,
                                                budget=SUGGESTED), ds)
    # the suggestion is her everyday spending, like the forecast, rounded: a little less on the card, a bit more left
    assert sent.without.lasts_through_semester and sent.with_budget.lasts_through_semester
    assert sent.days_longer.value is None and sent.end_change.value == Decimal("11.60")
    assert sent.end_change.value == sent.with_budget.end_balance.value - sent.without.end_balance.value
    lean = engine.budget_effect(engine.Scenario(budget=(("Groceries", Decimal("60")),)), ds)
    assert lean.without.first_below_zero.value == date(2026, 11, 9)
    assert lean.with_budget.first_below_zero.value == date(2026, 11, 15) and lean.days_longer.value == 6
    assert lean.lowest_change.value == Decimal("352.03") > 0


def test_budget_validation():
    with pytest.raises(ValueError):
        engine.Scenario(budget=(("Rent", Decimal("500")),))               # fixed, not budgetable
    with pytest.raises(ValueError):
        engine.Scenario(budget=(("Groceries", Decimal("-5")),))
    assert "budget Groceries $60.00/month" in engine.Scenario(budget=(("Groceries", Decimal("60")),)).describe()


# --- the Budget tab's top line --------------------------------------------------------------------------------

import summary  # noqa: E402
from types import SimpleNamespace  # noqa: E402


def _sp(ds, key, account="both"):
    per = summary.period(key)
    return engine.spending_by_category(per.start, min(per.end, config.DEMO_TODAY), account, ds), per


def test_top_line_sentences(ds):
    assert summary.sentence(*_sp(ds, "2026-10")) == \
        "So far in October, you spent $1,757. Most went to Rent ($725) and Shopping ($461)."
    assert summary.sentence(*_sp(ds, "2026-09")) == \
        "In September, you spent $1,291. Most went to Rent ($725) and School ($200)."
    assert summary.sentence(*_sp(ds, "2026-10", "card")) == ("So far in October, you spent $544 on the card. Most went to "
                                                             "Shopping ($461) and Eating out ($46.89).")
    per = summary.period("2026-11")
    assert summary.sentence(engine.spending_by_category(per.start, per.start, "both", ds), per) == \
        "Nothing spent yet in November: it hasn't started."


def test_ai_summary_is_checked(ds):
    sp, per = _sp(ds, "2026-10")

    def fake(text):
        return SimpleNamespace(chat=lambda *a, **k: SimpleNamespace(text=text))

    good = "You spent $1,757 so far. Shopping at $461 is the biggest flexible cost."
    assert summary.ai_summary(sp, per, fake(good)) == good
    for bad in ("You spent $1,800 so far.",                          # not a total
                "Shopping was 26% of your spending.",                # percentages aren't in the data
                "You spent $40 on Transportation.",                  # nothing on Transportation in October
                "Most went to Rent on Oct 1.",                       # dates
                "You spent $1,757 and most of it went to"):          # cut off
        assert summary.ai_summary(sp, per, fake(bad)) is None, bad
    boom = SimpleNamespace(chat=lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    assert summary.ai_summary(sp, per, boom) is None


# --- allocating: left to assign, progress and pace, the forecast line -------------------------------------------

def test_left_to_assign_and_progress(ds):
    m = engine.money_to_budget("2026-11", FORM_SENT, ds)
    left = engine.budget_left(m.amount, dict(SUGGESTED), engine.Ledger())
    assert left.value == Decimal("1436.47")                                   # 1,749.47 - 313
    assert engine.budget_left(m.amount, {"Shopping": 2000}, engine.Ledger()).value == Decimal("-250.53")
    rows = {r.category: r for r in engine.budget_progress(dict(SUGGESTED), None, ds)}
    # October so far, day 26 of 31: the budget's share for the days gone is budget x 26/31
    assert rows["Shopping"].spent.value == Decimal("460.99") and rows["Shopping"].pace == "over"
    assert rows["Shopping"].left.value == Decimal("-442.99")       # real spending, one-offs too
    assert rows["Groceries"].expected.value == Decimal("155.16") and rows["Groceries"].pace == "spending fast"
    assert rows["Groceries"].left.value == Decimal("8.51")
    assert rows["Transportation"].spent.value == 0 and rows["Transportation"].pace == "on pace"


def test_budget_effect_lines(ds):
    lean = engine.budget_effect(engine.Scenario(budget=(("Groceries", Decimal("60")),)), ds)
    assert summary.budget_effect_line(lean) == \
        "If you stick to this budget, your money lasts until Sun, Nov 15 (6 days longer)."
    sent = engine.budget_effect(engine.Scenario(refund_released=True, refund_submit_date=config.DEMO_TODAY,
                                                budget=SUGGESTED), ds)
    assert summary.budget_effect_line(sent) == ("Your money lasts all semester either way. You'd end the semester "
                                                "with $11.60 more.")
    same = engine.budget_effect(engine.Scenario(budget=(("Groceries", Decimal("185")), ("Eating out", Decimal("96")))),
                                ds)
    assert summary.budget_effect_line(same).startswith("Your money still runs out on Mon, Nov 9.")
