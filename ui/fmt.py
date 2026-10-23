"""Display formatting only. No money math here (rule 2): every number comes from engine.Computed."""
from datetime import date
from decimal import Decimal

from engine import fmt_money


def money(x):
    return fmt_money(x)


def signed_money(x):
    """+$1,467.18 / -$12.37 / None for no change (for st.metric deltas)."""
    if x is None or Decimal(x) == 0:
        return None
    return ("+" if Decimal(x) > 0 else "") + fmt_money(x)


def day(d):
    """Mon Nov 9"""
    return f"{d:%a %b} {d.day}" if d else "never"


def day_year(d):
    """Thu Jan 7, 2027 (when the year is not the demo year)"""
    return f"{day(d)}, {d.year}" if d.year != 2026 else day(d)


def value(c):
    """A Computed record's value, formatted by its unit."""
    v = c.value
    if v is None:
        return "none"
    if c.unit == "USD":
        return money(v)
    if isinstance(v, date):
        return day_year(v)
    if c.unit == "weeks":
        return f"{v} weeks"
    if c.unit == "hours":
        return f"{v} hours"
    if c.unit == "percent":
        return f"{v}%"
    return str(v)
