"""normalize: date formats, signs, merchant normalization, classification (local backend, no network)."""
from datetime import date
from decimal import Decimal

import pytest

import normalize as n


@pytest.fixture(scope="module")
def ds():
    return n.load("local")


@pytest.mark.parametrize("raw,fmt,expected", [
    ("2026-10-01", "iso", date(2026, 10, 1)),
    ("10/03/2026", "mdy", date(2026, 10, 3)),
    ("20260918", "ymd8", date(2026, 9, 18)),
    ("10-SEP-2026", "banner", date(2026, 9, 10)),
    ("2026/11/01", "slash", date(2026, 11, 1)),
    ("11/7/26", "short", date(2026, 11, 7)),
    ("", "iso", None),
])
def test_parse_date(raw, fmt, expected):
    assert n.parse_date(raw, fmt) == expected


def test_signs_money_out_is_negative(ds):
    assert ds.row("CHK-0042").amount == Decimal("-725.00")          # rent, checking
    assert ds.row("CRD-0019").amount == Decimal("-289.00")          # card purchase (stored +289.00)
    assert ds.row("STM-004").amount == Decimal("-359.53")           # statement to be paid
    assert ds.row("LED-004").amount == Decimal("-4890.00")          # bursar charge (stored +4890.00)
    assert ds.row("LED-010").amount == Decimal("1900.00")           # aid credit (stored -1900.00)
    assert ds.row("PPI-04").amount == Decimal("-200.00")
    assert ds.row("RS-04").amount == Decimal("-725.00")
    assert ds.row("RFD-01").amount == Decimal("1850.00")
    assert ds.row("CHK-0055").amount == Decimal("573.50")           # paycheck
    assert ds.checking_account.overdraft_fee == Decimal("-35.00")


def test_every_record_keeps_source_table_and_row_id(ds):
    for t in ds.txns():
        assert (t.source, t.table) in (("checking", "transactions"), ("card", "transactions"))
    assert (ds.row("SHF-040").source, ds.row("SHF-040").table) == ("shifts", "shifts")
    assert (ds.row("HLD-01").source, ds.row("HLD-01").table) == ("bursar", "holds")
    assert len(ds.evidence) == len(n.queries())


def test_same_merchant_matches_across_sources(ds):
    assert ds.row("CHK-0002").description == "KROGER #0412"
    assert ds.row("CRD-0002").description == "Kroger 0412 Midtown"
    assert ds.row("CHK-0002").merchant == ds.row("CRD-0002").merchant == "Kroger"
    assert ds.row("CHK-0004").merchant == ds.row("CRD-0006").merchant      # autopay, both sides


@pytest.mark.parametrize("row_id,category", [
    ("CHK-0001", "rent"), ("CHK-0023", "income"), ("CHK-0050", "income"),
    ("CHK-0003", "recurring_bill"),        # Venmo utility share, same amount 3+ months
    ("CHK-0015", "recurring_bill"),        # payment-plan installment
    ("CHK-0009", "subscription"), ("CRD-0003", "subscription"),
    ("CHK-0004", "card_payment"), ("CRD-0006", "card_payment"),
    ("CHK-0043", "fee"),
    ("CHK-0016", "one_off"), ("CRD-0008", "one_off"), ("CRD-0022", "one_off"),
    ("CHK-0002", "variable"), ("CHK-0040", "variable"), ("CRD-0012", "variable"),
])
def test_classification(ds, row_id, category):
    assert ds.row(row_id).category == category


def test_categories_are_known(ds):
    assert {t.category for t in ds.txns()} <= set(n.CATEGORIES)


def test_merchant_rules_first_match_wins():
    assert n.merchant_rule("UBER   *TRIP HELP.UBER.COM")[0] == "Uber"
    assert n.merchant_rule("APPLE.COM/BILL 866-712-7753 CA")[:3] == ("Apple Music", "subscription", "music streaming")
    assert n.merchant_rule("SOMETHING NEW 123")[0] == "SOMETHING NEW 123"
