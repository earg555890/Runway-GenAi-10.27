"""Import the student's own bank export (CSV): detect the columns and sign convention, preview, then normalize.

    m = importer.detect(text)                # Mapping with the guessed columns, date format and sign rule
    importer.preview(text, m)                # first rows as the importer reads them (shown before importing)
    rows = importer.normalize_rows(text, m)  # [{"date", "description", "amount", "balance"}], money out negative

Rule-based, no AI. Handles commas and $ in amounts, parentheses for negatives, trailing minus or CR/DR, separate
debit and credit columns, newest-first files, and the common date formats. A file it can't understand raises
ImportProblem with a plain message. Nothing here writes anywhere: see mydata.save().
"""
import csv
import io
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d-%m-%Y", "%m-%d-%Y", "%Y/%m/%d", "%d %b %Y",
                "%b %d, %Y", "%d-%b-%Y"]
DATE_WORDS = ("date", "posted", "posting", "transaction date", "trans date")
DESC_WORDS = ("description", "desc", "payee", "memo", "details", "merchant", "name", "narrative", "transaction")
AMOUNT_WORDS = ("amount", "amt", "value")
DEBIT_WORDS = ("debit", "withdrawal", "withdrawals", "money out", "paid out", "charge")
CREDIT_WORDS = ("credit", "deposit", "deposits", "money in", "paid in")
BALANCE_WORDS = ("balance", "running", "bal")
SIGNS = {"negative_out": "Money out is negative (e.g. -45.10)",
         "positive_out": "Money out is positive (e.g. 45.10 for a purchase)",
         "debit_credit": "Separate money-out and money-in columns"}


class ImportProblem(ValueError):
    """A file the importer can't use, with a message in plain words."""


@dataclass
class Mapping:
    date: str | None = None
    date_format: str | None = None
    description: str | None = None
    amount: str | None = None              # one signed column ...
    debit: str | None = None               # ... or money out / money in columns
    credit: str | None = None
    balance: str | None = None
    sign: str = "negative_out"
    header: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def read(text):
    """(header, rows) from CSV text: the first row that looks like a header (mostly non-numeric) and the rows after
    it with as many cells. Blank lines and bank preamble lines are skipped."""
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    for i, r in enumerate(rows[:15]):
        if len(r) >= 2 and sum(1 for c in r if c and not _num_like(c)) >= max(2, len(r) - 1):
            body = [x for x in rows[i + 1:] if len(x) == len(r)]
            if body:
                return r, body
    raise ImportProblem("I couldn't find a header row (column names like Date, Description, Amount) in this file.")


def _num_like(s):
    return bool(re.fullmatch(r"[\s$()+\-.,0-9CRDcrd]*\d[\s$()+\-.,0-9CRDcrd]*", s))


def money(s):
    """Decimal from a bank amount: "$1,050.00", "-45.10", "(45.10)", "45.10-", "45.10 CR", "45.10 DR". "" -> None."""
    s = (s or "").strip()
    if not s:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    up = s.upper()
    if up.endswith("DR"):
        neg, s = True, s[:-2]
    elif up.endswith("CR"):
        s = s[:-2]
    s = s.strip()
    if s.endswith("-"):
        neg, s = True, s[:-1]
    if s.startswith("-"):
        neg, s = not neg if neg else True, s[1:]
    s = s.replace("$", "").replace(",", "").replace(" ", "").lstrip("+")
    try:
        v = Decimal(s)
    except InvalidOperation:
        return None
    return -v if neg else v


def parse_date(s, fmt):
    try:
        d = datetime.strptime(s.strip(), fmt).date()
    except ValueError:
        return None
    return d if fmt != "%m/%d" else None             # a date without a year is not enough


def _best_date_format(values):
    """(format, share parsed) for a column; dd/mm vs mm/dd is decided by values over 12."""
    best = (None, 0.0)
    for fmt in DATE_FORMATS:
        ok = sum(1 for v in values if v and parse_date(v, fmt))
        share = ok / max(1, sum(1 for v in values if v))
        if share > best[1] + 1e-9:
            best = (fmt, share)
    return best


def _named(header, words):
    low = [h.lower() for h in header]
    for wd in words:
        for i, h in enumerate(low):
            if wd == h or re.search(r"\b" + re.escape(wd) + r"\b", h):
                return header[i]
    return None


def detect(text):
    """Guess the mapping. Raises ImportProblem if there is no usable date or amount column."""
    header, rows = read(text)
    cols = {h: [r[i] for r in rows] for i, h in enumerate(header)}
    m = Mapping(header=list(header))
    dates = {h: _best_date_format(v) for h, v in cols.items()}
    by_name = _named(header, DATE_WORDS)
    candidates = sorted(((share, h) for h, (fmt, share) in dates.items() if share >= 0.8), reverse=True)
    if by_name and dates[by_name][1] >= 0.8:
        m.date = by_name
    elif candidates:
        m.date = candidates[0][1]
    if not m.date:
        raise ImportProblem("I couldn't find a date column. Bank exports usually have one called Date or Posted.")
    m.date_format = dates[m.date][0]
    moneyish = {h: v for h, v in cols.items() if h != m.date
                and sum(1 for x in v if x and money(x) is not None) >= 0.8 * max(1, sum(1 for x in v if x))
                and any(x for x in v)}
    m.balance = _named([h for h in header if h in moneyish], BALANCE_WORDS)
    m.debit = _named([h for h in header if h in moneyish and h != m.balance], DEBIT_WORDS)
    m.credit = _named([h for h in header if h in moneyish and h not in (m.balance, m.debit)], CREDIT_WORDS)
    if m.debit and m.credit:
        m.sign = "debit_credit"
    else:
        m.debit = m.credit = None
        m.amount = (_named([h for h in header if h in moneyish and h != m.balance], AMOUNT_WORDS)
                    or next((h for h in header if h in moneyish and h != m.balance), None))
        if not m.amount:
            raise ImportProblem("I couldn't find an amount column (or separate debit and credit columns).")
        m.sign = _guess_sign(rows, header, m)
    texty = [h for h in header if h not in moneyish and h != m.date]
    m.description = _named(texty, DESC_WORDS) or max(texty, key=lambda h: len(set(cols[h])), default=None)
    if not m.description:
        raise ImportProblem("I couldn't find a description column (what each transaction was).")
    return m


def _guess_sign(rows, header, m):
    """With a balance column, the sign that makes balance changes match the amounts; else negative amounts mean
    money out if the file has any, and positive-means-out (flagged for the student to check) if it has none."""
    ai = header.index(m.amount)
    amounts = [money(r[ai]) for r in rows]
    if m.balance:
        bi = header.index(m.balance)
        bals = [money(r[bi]) for r in rows]
        agree = flip = 0
        for k in range(1, len(rows)):
            if None in (bals[k], bals[k - 1], amounts[k]):
                continue
            step = bals[k] - bals[k - 1]
            agree += step == amounts[k] or -step == amounts[k - 1]          # oldest first, or newest first
            flip += step == -amounts[k] or step == amounts[k - 1]
        if agree or flip:
            return "negative_out" if agree >= flip else "positive_out"
    if any(a is not None and a < 0 for a in amounts):
        return "negative_out"
    m.notes.append("Every amount is positive and there's no balance to check against, so I assumed they're money "
                   "out. Change it below if some are deposits.")
    return "positive_out"


def _row(r, header, m):
    get = lambda col: r[header.index(col)] if col else ""   # noqa: E731
    d = parse_date(get(m.date), m.date_format)
    if m.sign == "debit_credit":
        out, inn = money(get(m.debit)), money(get(m.credit))
        amount = (inn or Decimal(0)) - abs(out or Decimal(0)) if (out is not None or inn is not None) else None
    else:
        a = money(get(m.amount))
        amount = None if a is None else (a if m.sign == "negative_out" else -a)
    return {"date": d, "description": get(m.description), "amount": amount,
            "balance": money(get(m.balance)) if m.balance else None}


def normalize_rows(text, m):
    """Every row as {date, description, amount (money out negative), balance or None}, oldest first (file order kept
    within a day). Raises ImportProblem if too many rows can't be read."""
    header, rows = read(text)
    for col in (m.date, m.description, m.amount, m.debit, m.credit, m.balance):
        if col and col not in header:
            raise ImportProblem(f"The column {col!r} isn't in this file.")
    out = [_row(r, header, m) for r in rows]
    good = [x for x in out if x["date"] and x["amount"] is not None]
    if len(good) < max(3, 0.8 * len(out)):
        raise ImportProblem("Too many rows have a date or amount I can't read with this mapping. Check the columns "
                            "and the date format.")
    newest_first = len(good) > 1 and good[0]["date"] > good[-1]["date"]
    if newest_first:
        good.reverse()
    return sorted(good, key=lambda x: x["date"])         # stable: keeps the file's order within a day


def preview(text, m, n=6):
    """The first n rows as they will be imported (for the student to check the mapping)."""
    return normalize_rows(text, m)[:n]
