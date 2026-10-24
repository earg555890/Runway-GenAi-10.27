"""Plain-English wording shared by the UI and the agent. Formatting only: no money math (rule 2)."""
import html as _html
import re
from datetime import date
from decimal import Decimal

import normalize as n
from engine import fmt_money

STUDENT_NAME = "Maya Rivera"
SOURCE_PLAIN = {"checking": "Your checking account", "card": "Your credit card", "aid": "Financial aid office",
                "bursar": "Student account (bursar)", "lease": "Your lease", "shifts": "Your work schedule"}
TERMS = {"FA": "Fall", "SP": "Spring", "SU": "Summer"}


_ROW_ID = re.compile(r"\s*\(?\b(?:ACCT|AWD|CHK|CRD|DSB|HLD|JOB|LED|LT|PAY|PPI|REQ|RFD|RS|SHF|STM)-[A-Z0-9-]+\b\)?:?")


def strip_ids(text):
    """Remove source row IDs (e.g. "Refund RFD-01 ($1,850.00)") from engine text shown to students."""
    return re.sub(r"\s+([.,;])", r"\1", _ROW_ID.sub("", text)).strip()


def term_name(code):
    """FA26 -> Fall 2026"""
    return f"{TERMS.get(code[:2], code[:2])} 20{code[2:]}"


def money(x):
    return fmt_money(x)


def md(s):
    """Text for st.markdown / captions / labels: a bare $ would start a math formula."""
    return s.replace("$", "\\$")


def html(s):
    return _html.escape(s).replace("$", "&#36;")


def day(d):
    """Mon Nov 9 (adds the year when it is not the demo year)."""
    if not d:
        return "never"
    return f"{d:%a %b} {d.day}" + (f", {d.year}" if d.year != 2026 else "")


def weeks_words(v):
    v = Decimal(v)
    if v < 1:
        return "less than a week"
    whole = v == v.to_integral_value()
    shown = f"{int(v)}" if whole else f"{v}"
    return f"{shown} week" + ("" if shown == "1" else "s")


def ordinal(k):
    return f"{k}{'th' if 11 <= k % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(k % 10, 'th')}"


def things(k):
    return f"{k} thing" + ("" if k == 1 else "s")


def event_name(e):
    """A projected event in plain words, e.g. 'credit card payment'."""
    return {"rent": "rent", "card_autopay": "credit card payment", "installment": "tuition payment",
            "paycheck": "paycheck", "refund": "refund", "purchase": e.label,
            "subscription": e.label.rsplit(" ", 1)[0], "recurring_bill": e.label.rsplit(" ", 1)[0] + " payment"}[e.kind]


def describe(rec):
    """(date, what, amount) for one source record, for the 'Show proof' tables."""
    m = money
    if isinstance(rec, n.Txn):
        return rec.date, rec.merchant, m(rec.amount)
    if isinstance(rec, n.CheckingAccount):
        return rec.as_of, f"Checking balance (overdraft fee {m(-rec.overdraft_fee)} per item)", m(rec.current_balance)
    if isinstance(rec, n.Statement):
        return rec.due, f"Card bill for {day(rec.cycle_start)} to {day(rec.closing)} ({rec.status.lower()})", m(rec.amount)
    if isinstance(rec, n.Disbursement):
        return rec.scheduled, f"Aid payment ({rec.status.lower()})", m(rec.net)
    if isinstance(rec, n.Requirement):
        return rec.requested, f"{rec.description}: {rec.status.lower()}", ""
    if isinstance(rec, n.LedgerEntry):
        return rec.date, rec.description, m(rec.amount)
    if isinstance(rec, n.Hold):
        return rec.from_date, f"Hold: {rec.description} (blocks {rec.blocks.lower()})", ""
    if isinstance(rec, n.Refund):
        return None, f"Refund ({rec.status.lower()}): {rec.release_rule.lower()}", m(rec.amount)
    if isinstance(rec, n.Installment):
        return rec.due, f"Payment-plan installment {rec.number} ({rec.status.lower()})", m(rec.amount)
    if isinstance(rec, n.RentDue):
        return rec.due, f"Rent for {rec.period} ({rec.status.lower()})", m(rec.amount)
    if isinstance(rec, n.LeaseTerms):
        return rec.start, f"Lease: rent due on the {ordinal(rec.rent_due_day)}", m(rec.monthly_rent)
    if isinstance(rec, n.Job):
        return None, f"{rec.employer}: {m(rec.hourly_rate)}/hour, {rec.withholding_pct}% withheld", ""
    if isinstance(rec, n.PayPeriod):
        return rec.pay_date, f"Paycheck for {day(rec.start)} to {day(rec.end)} ({rec.status.lower()})", \
            m(rec.net) if rec.net is not None else ""
    if isinstance(rec, n.Shift):
        return rec.date, f"Shift {rec.start_time}-{rec.end_time}, {rec.hours} hours ({rec.status.lower()})", ""
    return None, rec.row_id, ""


def value(c):
    """A calculation's value, formatted by its unit (Behind the scenes)."""
    v = c.value
    if v is None:
        return "none"
    if c.unit == "USD":
        return money(v)
    if isinstance(v, date):
        return day(v)
    if c.unit == "weeks":
        return f"{v} weeks"
    if c.unit == "hours":
        return f"{v} hours"
    if c.unit == "percent":
        return f"{v}%"
    return str(v)
