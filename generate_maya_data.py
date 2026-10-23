"""Generate Maya's synthetic demo data into data/maya/ (one folder per source).

    .venv/Scripts/python generate_maya_data.py

Reproducible: fixed seed, no network, no real accounts. The CSVs are the source of truth;
the two PDFs (aid award letter, lease) are rendered from the same data for display only.

Maya: sophomore at a state public university, lives off campus, works part-time at a campus
cafe, has a Pell grant and a subsidized loan, and has a payment plan for her summer balance.
Demo "today" is config.DEMO_TODAY (Mon Oct 26, 2026); checking history runs Aug 1 - Oct 26.

The sources are deliberately inconsistent with each other (date formats, column names,
merchant spellings, sign conventions), the way real exports are.

Planted stories (expected findings, numbers and row IDs go to data/maya/answer_key.json):
  1. $1,850 aid refund held: verification hold for a missing form.
  2. Two music subscriptions: Spotify on checking, Apple Music on the credit card.
  3. $35 overdraft fee in early October: rent due on the 1st, payday the 3rd.
  4. November payment-plan installment due the same week as a short paycheck.
  5. The $400 Thanksgiving flight (booked by Nov 10) is affordable only if the refund is
     released AND one music subscription is cancelled.

Story 5's projection is the money engine's job (engine.py): tests/test_engine.py checks that the
engine reproduces the story-5 numbers recorded in the answer key (STORY5_EXPECTED) to the cent.
"""
import csv
import json
import random
import shutil
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import config

SEED = 20261026
OUT = Path(__file__).resolve().parent / "data" / "maya"

TODAY = config.DEMO_TODAY                      # Mon Oct 26, 2026
HISTORY_START = date(2026, 8, 1)
SEMESTER_START = config.SEMESTER_START         # Aug 24
SEMESTER_END = config.SEMESTER_END             # Dec 18
CARD_HISTORY_START = date(2026, 7, 13)         # start of the cycle that closes Aug 12


def D(x):
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def days(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def prev_business_day(d):
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def next_business_day(d):
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


# ---------------------------------------------------------------------------------------
# Maya's facts. Every number in the stories comes from here.
# ---------------------------------------------------------------------------------------
STUDENT = dict(name="Maya Rivera", student_id="U00418273", email="maya.rivera@stateu.example.edu",
               school="State University", year="Sophomore", address="1417 W Oak St, Apt 2B")

CHECKING_OPEN_BALANCE = D("3010.00")   # Aug 1, 2026 (summer job savings) -- tuned for story 5
OVERDRAFT_FEE = D("35.00")

RENT = D("725.00")
RENT_DUE_DAY = 1
RENT_GRACE_DAYS = 5
RENT_LATE_FEE = D("50.00")
UTIL_SHARE = D("55.00")               # flat monthly Venmo to roommate for electric + internet, on the 5th

SPOTIFY = D("11.99")                  # checking, 14th of each month
SPOTIFY_DAY = 14
APPLE_MUSIC = D("10.99")              # credit card, 22nd of each month
APPLE_MUSIC_DAY = 22

HOURLY_RATE = D("15.50")
WITHHOLDING_PCT = Decimal("7.5")            # federal + state income tax; student FICA exemption applies

CARD_CLOSING_DAY = 12
CARD_DUE_DAY = 7
CARD_JUL_STATEMENT_BALANCE = D("58.40")  # statement closed Jul 12, paid Aug 7

# Bursar / aid (Fall 2026)
TUITION_FA26 = D("4890.00")
FEES_FA26 = [("SSVC", "Student Services Fee", D("412.00")), ("HLTH", "Health Service Fee", D("268.22")),
             ("TECH", "Technology Fee", D("225.00")), ("TRAN", "Transportation Fee", D("178.00"))]
PELL_FA26 = D("3697.00")
PELL_SP27 = D("3698.00")
SUB_LOAN_TERM_GROSS = D("2250.00")
SUB_LOAN_FEE_PCT = Decimal("1.057")
STATE_GRANT_FA26 = D("1900.00")
STATE_GRANT_SP27 = D("1900.00")
REFUND_RELEASE_BUSINESS_DAYS = 7      # bursar policy: refund within 7 business days after the hold clears

# Summer 2026 balance on a 4-installment plan
SU26_TUITION = D("770.00")
PLAN_FEE = D("30.00")
PLAN_INSTALLMENT = D("200.00")
PLAN_DUE_DATES = [date(2026, 8, 20), date(2026, 9, 20), date(2026, 10, 20), date(2026, 11, 20)]

# Thanksgiving flight (story 5)
FLIGHT_COST = D("400.00")
FLIGHT_BOOK_BY = date(2026, 11, 10)


# ---------------------------------------------------------------------------------------
# Shifts
# ---------------------------------------------------------------------------------------
@dataclass
class Shift:
    day: date
    start: str
    end: str
    hours: Decimal
    status: str   # WORKED, CALLED_OFF, SCHEDULED
    note: str = ""


WEEKLY = {0: ("7:00 AM", "11:00 AM"), 2: ("7:00 AM", "11:00 AM"), 4: ("7:00 AM", "11:00 AM"),
          5: ("9:00 AM", "1:00 PM")}   # Mon, Wed, Fri mornings + Sat
CALLED_OFF = {date(2026, 9, 9): "called off (sick)"}
EXTRA_SHIFTS = {date(2026, 10, 11): ("10:00 AM", "2:00 PM", "extra shift (fall break)"),
                date(2026, 10, 13): ("7:00 AM", "11:00 AM", "extra shift (fall break)")}
RENOVATION = (date(2026, 10, 26), date(2026, 12, 11))   # cafe kitchen renovation: Saturdays only
RENOVATION_NOTE = "reduced schedule: kitchen renovation Oct 26 - Dec 11 (Saturdays only)"
THANKSGIVING_OFF = (date(2026, 11, 23), date(2026, 11, 29))
FINALS_OFF_FROM = date(2026, 12, 12)


def build_shifts():
    shifts = []
    for d in days(SEMESTER_START, SEMESTER_END):
        if d in EXTRA_SHIFTS:
            start, end, note = EXTRA_SHIFTS[d]
            shifts.append(Shift(d, start, end, D(4), "WORKED" if d < TODAY else "SCHEDULED", note))
            continue
        if d.weekday() not in WEEKLY:
            continue
        start, end = WEEKLY[d.weekday()]
        note = ""
        if RENOVATION[0] <= d <= RENOVATION[1] and d.weekday() != 5:
            continue                              # not scheduled: renovation
        if THANKSGIVING_OFF[0] <= d <= THANKSGIVING_OFF[1] or d >= FINALS_OFF_FROM:
            continue                              # time off requested / finals
        if RENOVATION[0] <= d <= RENOVATION[1]:
            note = RENOVATION_NOTE
        status = "WORKED" if d < TODAY else "SCHEDULED"
        if d in CALLED_OFF:
            status, note = "CALLED_OFF", CALLED_OFF[d]
        shifts.append(Shift(d, start, end, D(4), status, note))
    return shifts


def pay_periods():
    """Semi-monthly: the 1st-15th is paid on the 18th; the 16th-end on the 3rd of next month.
    A pay date on a weekend moves to the Friday before."""
    periods = []
    for month in (8, 9, 10, 11, 12):
        first = date(2026, month, 1)
        mid = date(2026, month, 15)
        end = (date(2026, month + 1, 1) if month < 12 else date(2027, 1, 1)) - timedelta(days=1)
        periods.append((first, mid, prev_business_day(date(2026, month, 18))))
        nxt = date(2026, month + 1, 3) if month < 12 else date(2027, 1, 3)
        periods.append((date(2026, month, 16), end, prev_business_day(nxt)))
    # Only periods that contain semester shifts and are paid by the end of the semester
    return [p for p in periods if p[1] >= SEMESTER_START and p[2] <= SEMESTER_END]


def net_pay(hours):
    gross = D(hours * HOURLY_RATE)
    withholding = D(gross * WITHHOLDING_PCT / 100)
    return gross, withholding, gross - withholding


# ---------------------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------------------
@dataclass
class Txn:
    day: date
    desc: str
    amount: Decimal       # signed from Maya's point of view: money out is negative
    kind: str             # internal label used by the generator and the self-check only


def card_cycles():
    """(cycle_start, closing_date, due_date) for statements from Aug 12 on."""
    cycles = []
    for m in (8, 9, 10, 11):
        closing = date(2026, m, CARD_CLOSING_DAY)
        start = date(2026, m - 1, CARD_CLOSING_DAY + 1)
        due = date(2026, m + 1, CARD_DUE_DAY)
        cycles.append((start, closing, due))
    return cycles


def build_card_txns(rng):
    txns = []
    for d in days(CARD_HISTORY_START, TODAY):
        if d.day == APPLE_MUSIC_DAY:
            txns.append(Txn(d, "APPLE.COM/BILL 866-712-7753 CA", -APPLE_MUSIC, "apple_music"))
        if d == date(2026, 8, 10):
            txns.append(Txn(d, "AMAZON MKTPL*2K41L09T3 Amzn.com/bill WA", D("-146.38"), "card_oneoff"))
        if d == date(2026, 10, 3):
            txns.append(Txn(d, "UBREAKIFIX #0291 MIDTOWN", D("-289.00"), "card_oneoff"))
        if d == date(2026, 10, 18):
            txns.append(Txn(d, "BURLINGTON #1182", D("-171.99"), "card_oneoff"))
        if d.weekday() == 5 and rng.random() < 0.45:
            txns.append(Txn(d, rng.choice(["DOORDASH*PANDA EXPRESS", "DOORDASH*SWEETGREEN"]),
                            -D(rng.uniform(14, 26)), "card_var"))
        if d.weekday() == 6 and rng.random() < 0.30:
            txns.append(Txn(d, "Kroger 0412 Midtown", -D(rng.uniform(18, 42)), "card_var"))
        if rng.random() < 0.06:
            txns.append(Txn(d, "UBER   *TRIP HELP.UBER.COM", -D(rng.uniform(9, 17)), "card_var"))
        if d.day == 27 and d.month in (8, 10):
            txns.append(Txn(d, "TARGET 00012345 MIDTOWN", -D(rng.uniform(22, 38)), "card_var"))
    return txns


def card_statements(card_txns):
    """Statement balances from the card purchases; each is paid in full by autopay on the due date."""
    stmts = [dict(cycle_start=date(2026, 6, 13), closing=date(2026, 7, 12), due=date(2026, 8, 7),
                  balance=CARD_JUL_STATEMENT_BALANCE)]
    for start, closing, due in card_cycles():
        if closing > TODAY:
            break
        bal = -sum((t.amount for t in card_txns if start <= t.day <= closing), Decimal("0"))
        stmts.append(dict(cycle_start=start, closing=closing, due=due, balance=D(bal)))
    return stmts


def build_checking_txns(rng, shifts, periods, stmts):
    txns = []
    # fixed items
    for d in days(HISTORY_START, TODAY):
        if d.day == RENT_DUE_DAY:
            txns.append(Txn(d, "GREENWAY PROPERTY MGMT RENT WEB PMT", -RENT, "rent"))
        if d.day == 5:
            txns.append(Txn(d, "VENMO PAYMENT 1032457781 JORDAN K", -UTIL_SHARE, "util_share"))
        if d.day == SPOTIFY_DAY:
            txns.append(Txn(d, "SPOTIFY USA", -SPOTIFY, "spotify"))
    for due in PLAN_DUE_DATES:
        post = next_business_day(due)
        if post <= TODAY:
            n = PLAN_DUE_DATES.index(due) + 1
            txns.append(Txn(post, f"STATEU PAYPLAN ACH SU26 INST {n}/4", -PLAN_INSTALLMENT, "plan"))
    for s in stmts:
        post = next_business_day(s["due"])
        if HISTORY_START <= post <= TODAY:
            txns.append(Txn(post, "HORIZON CARD PYMT AUTOPAY", -s["balance"], "card_payment"))
    for start, end, pay_day in periods:
        if pay_day > TODAY:
            continue
        hours = sum((s.hours for s in shifts if start <= s.day <= end and s.status == "WORKED"), Decimal("0"))
        if hours:
            txns.append(Txn(pay_day, "STATE UNIV PAYROLL DIR DEP", net_pay(hours)[2], "paycheck"))
    # variable debit-card spending
    for d in days(HISTORY_START, TODAY):
        if d in (date(2026, 10, 1), date(2026, 10, 2)):
            continue   # nothing else posts while she is overdrawn (keeps it to one fee)
        if d.weekday() == 0:
            txns.append(Txn(d, "KROGER #0412", -D(rng.uniform(26, 48)), "chk_var"))
        if d.weekday() < 5 and rng.random() < 0.25:
            txns.append(Txn(d, "SQ *BEAN THERE CAFE", -D(rng.uniform(3.25, 6.75)), "chk_var"))
        if d.weekday() in (4, 5) and rng.random() < 0.30:
            txns.append(Txn(d, rng.choice(["CHIPOTLE 2291", "JIMMY JOHNS #1187", "POTBELLY 0442"]),
                            -D(rng.uniform(8, 14)), "chk_var"))
        if d == date(2026, 8, 21):
            txns.append(Txn(d, "STATEU BOOKSTORE #01", D("-187.45"), "chk_oneoff"))
        if d == date(2026, 9, 26):
            txns.append(Txn(d, "WALGREENS #07731", D("-18.62"), "chk_var"))
        if d == date(2026, 10, 12):
            txns.append(Txn(d, "MOBILE DEPOSIT CHECK #2041", D("300.00"), "gift_in"))
    order = {"rent": 0, "paycheck": 1, "gift_in": 1, "util_share": 2, "card_payment": 3, "plan": 4, "spotify": 5}
    txns.sort(key=lambda t: (t.day, order.get(t.kind, 9)))
    # overdraft fees: assessed when an item takes the balance below zero
    out, bal = [], CHECKING_OPEN_BALANCE
    for t in txns:
        before = bal
        bal += t.amount
        out.append(t)
        if t.amount < 0 and bal < 0 <= before:
            out.append(Txn(t.day, "COURTESY PAY FEE", -OVERDRAFT_FEE, "overdraft_fee"))
            bal -= OVERDRAFT_FEE
    return out


def running(txns, opening):
    bal, rows = opening, []
    for t in txns:
        bal += t.amount
        rows.append((t, bal))
    return rows


# ---------------------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------------------
def write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return len(rows)


def fmt_mdy(d):
    return d.strftime("%m/%d/%Y")


def fmt_banner(d):
    return d.strftime("%d-%b-%Y").upper()


def fmt_short(d):
    return f"{d.month}/{d.day}/{d.strftime('%y')}"


def pdf_escape(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_pdf(path, lines):
    """Minimal text-only PDF (Helvetica, US Letter). No dependencies."""
    per_page = 52
    pages = [lines[i:i + per_page] for i in range(0, len(lines), per_page)] or [[]]
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"]
    kids = []
    for page_lines in pages:
        ops = ["BT", "/F1 10.5 Tf", "14 TL", "56 740 Td"]
        for line in page_lines:
            if line.startswith("# "):
                ops += ["/F2 13 Tf", f"({pdf_escape(line[2:])}) Tj T*", "/F1 10.5 Tf"]
            else:
                ops.append(f"({pdf_escape(line)}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode('latin-1')}\nendstream")
        content_no = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_no} 0 R >>")
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode("latin-1")
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("latin-1")
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("latin-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))


def money(x):
    return f"${x:,.2f}"


# ---------------------------------------------------------------------------------------
# Story 5 expected results, written into the answer key. They are the money engine's outputs for
# this data; tests/test_engine.py fails if the engine stops reproducing them to the cent. If the
# data above changes, rerun the engine tests and copy the new values from the engine; never tune
# the projection rule (CLAUDE.md rule 11).
# ---------------------------------------------------------------------------------------
STORY5_METHOD = """(documented in answer_key.json so the real engine can reproduce it):
  - known scheduled items: rent (1st), utility share (5th), Spotify (14th), plan installment,
    card autopay (next business day after the 7th), paychecks from scheduled shifts;
  - variable spending at the semester-to-date daily average (checking debit and card separately);
  - the Nov 12 card statement = actual card spend Oct 13-26 + card daily average Oct 27-Nov 12
    (Apple Music's next charge, Nov 22, falls in the cycle paid Jan 7, after the semester);
  - the refund, if released, arrives REFUND_RELEASE_BUSINESS_DAYS business days after the hold
    clears, assuming the missing form is submitted on Tue Oct 27;
  - the flight is a $400 debit-card purchase on Nov 10."""
STORY5_EXPECTED = {
    "card_statement_nov_12_projected": "285.22",
    "scenarios": {
        "no_refund_no_cancel": {"min_balance": "-1862.37", "min_date": "2026-12-17", "balance_dec_18": "-1812.53"},
        "refund_only": {"min_balance": "-12.37", "min_date": "2026-12-17", "balance_dec_18": "37.47"},
        "cancel_spotify_only": {"min_balance": "-1838.39", "min_date": "2026-12-17", "balance_dec_18": "-1788.55"},
        "refund_and_cancel_spotify": {"min_balance": "5.81", "min_date": "2026-11-02", "balance_dec_18": "61.45"},
        "no_flight_no_refund": {"min_balance": "-1462.37", "min_date": "2026-12-17"},
    },
}
REFUND_FORM_SUBMITTED = date(2026, 10, 27)     # assumed submit date for the missing verification form


def add_business_days(d, n):
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


# ---------------------------------------------------------------------------------------
def main():
    rng = random.Random(SEED)
    if OUT.exists():
        shutil.rmtree(OUT)
    shifts = build_shifts()
    periods = pay_periods()
    card_txns = sorted(build_card_txns(rng), key=lambda t: t.day)
    stmts = card_statements(card_txns)
    chk_txns = build_checking_txns(rng, shifts, periods, stmts)
    chk_rows = running(chk_txns, CHECKING_OPEN_BALANCE)
    summary = {}

    # ---- checking -----------------------------------------------------------------------
    rows, ids = [], {}
    for i, (t, bal) in enumerate(chk_rows, start=1):
        tid = f"CHK-{i:04d}"
        ids.setdefault(t.kind, []).append((tid, t, bal))
        rows.append([tid, t.day.isoformat(), t.desc, f"{t.amount:.2f}", f"{bal:.2f}"])
    summary["checking/transactions.csv"] = write_csv(
        OUT / "checking" / "transactions.csv", ["txn_id", "posted_date", "description", "amount", "running_balance"], rows)
    end_balance = chk_rows[-1][1]
    summary["checking/account.csv"] = write_csv(
        OUT / "checking" / "account.csv",
        ["account_id", "institution", "account_type", "account_last4", "holder", "opening_balance_2026_08_01",
         "current_balance", "as_of", "overdraft_program", "overdraft_fee", "overdraft_fee_rule"],
        [["ACCT-CHK-01", "Prairie State Credit Union", "Student Checking", "4417", STUDENT["name"],
          f"{CHECKING_OPEN_BALANCE:.2f}", f"{end_balance:.2f}", TODAY.isoformat(), "Courtesy Pay",
          f"{OVERDRAFT_FEE:.2f}", "Fee per item that overdraws the account; max 3 per day"]])

    # ---- card (purchases positive, payments negative) -----------------------------------
    card_payments = [(next_business_day(s["due"]), s) for s in stmts if next_business_day(s["due"]) <= TODAY]
    entries = [(t.day, "txn", t) for t in card_txns] + [(d, "pay", s) for d, s in card_payments]
    entries.sort(key=lambda e: (e[0], e[1]))
    rows, card_ids = [], {}
    for i, (d, typ, obj) in enumerate(entries, start=1):
        cid = f"CRD-{i:04d}"
        post = d + timedelta(days=1 if typ == "txn" else 0)
        if typ == "txn":
            cat = "Digital Services" if obj.kind == "apple_music" else (
                "Groceries" if "Kroger" in obj.desc else "Transportation" if "UBER" in obj.desc else
                "Restaurants" if "DOORDASH" in obj.desc else "Merchandise")
            card_ids.setdefault(obj.kind, []).append((cid, obj))
            rows.append([cid, fmt_mdy(d), fmt_mdy(post), obj.desc, cat, f"{-obj.amount:.2f}"])
        else:
            card_ids.setdefault("payment", []).append((cid, obj))
            rows.append([cid, fmt_mdy(d), fmt_mdy(d), "PAYMENT - THANK YOU", "Payment", f"{-obj['balance']:.2f}"])
    summary["card/transactions.csv"] = write_csv(
        OUT / "card" / "transactions.csv", ["trans_id", "trans_date", "post_date", "merchant", "category", "amount"], rows)
    stmt_rows, stmt_ids = [], {}
    for i, s in enumerate(stmts, start=1):
        sid = f"STM-{i:03d}"
        stmt_ids[s["closing"]] = sid
        paid = next_business_day(s["due"]) <= TODAY
        min_due = min(s["balance"], max(D(25), D(s["balance"] * D("0.02"))))
        stmt_rows.append([sid, fmt_mdy(s["cycle_start"]), fmt_mdy(s["closing"]), fmt_mdy(s["due"]),
                          f"{s['balance']:.2f}", f"{min_due:.2f}", "STATEMENT BALANCE",
                          "PAID" if paid else "AUTOPAY SCHEDULED"])
    summary["card/statements.csv"] = write_csv(
        OUT / "card" / "statements.csv",
        ["statement_id", "cycle_start", "closing_date", "payment_due_date", "new_balance", "minimum_payment",
         "autopay_amount", "status"], stmt_rows)
    open_cycle_start = date(2026, 10, CARD_CLOSING_DAY + 1)
    open_cycle_spend = -sum((t.amount for t in card_txns if t.day >= open_cycle_start), Decimal("0"))
    summary["card/account.csv"] = write_csv(
        OUT / "card" / "account.csv",
        ["card_account", "issuer", "product", "last4", "credit_limit", "purchase_apr", "statement_closing_day",
         "payment_due_day", "autopay", "autopay_from", "current_balance", "as_of"],
        [["HZN-7731", "Horizon Bank", "Horizon Student Rewards Visa", "9012", "1500.00", "27.99",
          str(CARD_CLOSING_DAY), str(CARD_DUE_DAY), "STATEMENT BALANCE", "Prairie State CU checking x4417",
          f"{D(open_cycle_spend + stmts[-1]['balance']):.2f}", fmt_mdy(TODAY)]])

    # ---- aid (dates as YYYYMMDD, like the federal COD system) ----------------------------
    loan_fee = D(SUB_LOAN_TERM_GROSS * SUB_LOAN_FEE_PCT / 100)
    loan_net = SUB_LOAN_TERM_GROSS - loan_fee
    awards = [
        ["AWD-01", "2627", "PELL", "Federal Pell Grant", "FA26", f"{PELL_FA26:.2f}", f"{PELL_FA26:.2f}", "ACCEPTED"],
        ["AWD-02", "2627", "PELL", "Federal Pell Grant", "SP27", f"{PELL_SP27:.2f}", f"{PELL_SP27:.2f}", "ACCEPTED"],
        ["AWD-03", "2627", "DLSUB", "Federal Direct Subsidized Loan", "FA26", f"{SUB_LOAN_TERM_GROSS:.2f}",
         f"{SUB_LOAN_TERM_GROSS:.2f}", "ACCEPTED"],
        ["AWD-04", "2627", "DLSUB", "Federal Direct Subsidized Loan", "SP27", f"{SUB_LOAN_TERM_GROSS:.2f}",
         f"{SUB_LOAN_TERM_GROSS:.2f}", "ACCEPTED"],
        ["AWD-05", "2627", "SOG", "State Opportunity Grant", "FA26", f"{STATE_GRANT_FA26:.2f}",
         f"{STATE_GRANT_FA26:.2f}", "ACCEPTED"],
        ["AWD-06", "2627", "SOG", "State Opportunity Grant", "SP27", f"{STATE_GRANT_SP27:.2f}",
         f"{STATE_GRANT_SP27:.2f}", "ACCEPTED"],
        ["AWD-07", "2627", "DLUNS", "Federal Direct Unsubsidized Loan", "FA26", "1000.00", "0.00", "DECLINED"],
    ]
    summary["aid/award_lines.csv"] = write_csv(
        OUT / "aid" / "award_lines.csv",
        ["awd_line_id", "aid_yr", "fund_code", "fund_desc", "term", "offered_amt", "accepted_amt", "awd_status"], awards)
    disb = [
        ["DSB-01", "AWD-03", "20260824", f"{SUB_LOAN_TERM_GROSS:.2f}", f"{loan_fee:.2f}", f"{loan_net:.2f}", "DISBURSED", ""],
        ["DSB-02", "AWD-05", "20260914", f"{STATE_GRANT_FA26:.2f}", "0.00", f"{STATE_GRANT_FA26:.2f}", "DISBURSED", ""],
        ["DSB-03", "AWD-01", "20260918", f"{PELL_FA26:.2f}", "0.00", f"{PELL_FA26:.2f}", "HELD",
         "Selected for verification; required documents not received (see REQ-01)"],
        ["DSB-04", "AWD-02", "20270119", f"{PELL_SP27:.2f}", "0.00", f"{PELL_SP27:.2f}", "SCHEDULED", ""],
        ["DSB-05", "AWD-04", "20270119", f"{SUB_LOAN_TERM_GROSS:.2f}", f"{loan_fee:.2f}", f"{loan_net:.2f}", "SCHEDULED", ""],
        ["DSB-06", "AWD-06", "20270201", f"{STATE_GRANT_SP27:.2f}", "0.00", f"{STATE_GRANT_SP27:.2f}", "SCHEDULED", ""],
    ]
    summary["aid/disbursements.csv"] = write_csv(
        OUT / "aid" / "disbursements.csv",
        ["disb_id", "awd_line_id", "sched_disb_date", "gross_amt", "orig_fee_amt", "net_amt", "disb_status", "hold_reason"],
        disb)
    reqs = [
        ["REQ-01", "2627", "V1WS", "2026-27 Verification Worksheet (Dependent)", "20260910", "", "NOT RECEIVED",
         "Pell and refunds held until received and reviewed"],
        ["REQ-02", "2627", "PTAX", "Parent 2024 IRS Tax Return Transcript", "20260910", "20260929", "SATISFIED", ""],
        ["REQ-03", "2627", "MPN", "Direct Loan Master Promissory Note", "20260701", "20260708", "SATISFIED", ""],
    ]
    summary["aid/requirements.csv"] = write_csv(
        OUT / "aid" / "requirements.csv",
        ["req_id", "aid_yr", "req_code", "req_desc", "requested_dt", "received_dt", "req_status", "effect"], reqs)

    # ---- bursar (Banner style: charges positive, credits negative, DD-MON-YYYY) ---------
    led = [["SU26", date(2026, 5, 18), "TUIT", "Tuition Summer 2026 (3 cr)", SU26_TUITION, "N"],
           ["SU26", date(2026, 7, 15), "PLFE", "Payment Plan Enrollment Fee", PLAN_FEE, "N"],
           ["SU26", date(2026, 7, 15), "PLAN", "Payment Plan Contract SU26 (memo)", -(SU26_TUITION + PLAN_FEE), "Y"],
           ["FA26", date(2026, 8, 10), "TUIT", "Tuition Fall 2026 (15 cr)", TUITION_FA26, "N"]]
    led += [["FA26", date(2026, 8, 10), code, desc, amt, "N"] for code, desc, amt in FEES_FA26]
    led += [["FA26", date(2026, 8, 24), "DSUB", "Fed Direct Sub Loan (net)", -loan_net, "N"],
            ["FA26", date(2026, 9, 14), "SOGR", "State Opportunity Grant", -STATE_GRANT_FA26, "N"],
            ["FA26", date(2026, 9, 18), "PELL", "Fed Pell Grant - ANTICIPATED (not disbursed)", -PELL_FA26, "Y"]]
    fa_charges = TUITION_FA26 + sum((a for _, _, a in FEES_FA26), Decimal("0"))
    refund_amt = PELL_FA26 + loan_net + STATE_GRANT_FA26 - fa_charges
    led_rows, led_ids = [], {}
    for i, (term, d, code, desc, amt, memo) in enumerate(led, start=1):
        lid = f"LED-{i:03d}"
        led_ids[(term, code)] = lid
        led_rows.append([lid, term, fmt_banner(d), code, desc, f"{amt:.2f}", memo])
    summary["bursar/ledger.csv"] = write_csv(
        OUT / "bursar" / "ledger.csv",
        ["LEDGER_ID", "TERM_CODE", "ENTRY_DATE", "DETAIL_CODE", "DESCRIPTION", "AMOUNT", "MEMO_FLAG"], led_rows)
    plan_rows = []
    for n, due in enumerate(PLAN_DUE_DATES, start=1):
        paid = next_business_day(due) <= TODAY
        plan_rows.append([f"PPI-{n:02d}", "SU26", f"{n}/4", fmt_banner(due), f"{PLAN_INSTALLMENT:.2f}",
                          "PAID" if paid else "DUE", fmt_banner(next_business_day(due)) if paid else "",
                          "Auto-debit Prairie State CU x4417"])
    summary["bursar/payment_plan.csv"] = write_csv(
        OUT / "bursar" / "payment_plan.csv",
        ["INSTALLMENT_ID", "TERM_CODE", "INSTALLMENT", "DUE_DATE", "AMOUNT", "STATUS", "PAID_DATE", "METHOD"], plan_rows)
    summary["bursar/holds.csv"] = write_csv(
        OUT / "bursar" / "holds.csv",
        ["HOLD_ID", "HOLD_CODE", "HOLD_DESC", "FROM_DATE", "TO_DATE", "ORIGINATOR", "BLOCKS", "STATUS"],
        [["HLD-01", "FV", "Financial Aid Verification Incomplete", "10-SEP-2026", "", "Office of Student Financial Aid",
          "Aid disbursement; credit balance refunds", "ACTIVE"],
         ["HLD-02", "IM", "Immunization Record Missing", "01-JUL-2026", "12-AUG-2026", "Student Health",
          "Registration", "RELEASED"]])
    summary["bursar/refunds.csv"] = write_csv(
        OUT / "bursar" / "refunds.csv",
        ["REFUND_ID", "TERM_CODE", "REFUND_AMOUNT", "BASIS", "STATUS", "STATUS_REASON", "RELEASE_RULE", "METHOD"],
        [["RFD-01", "FA26", f"{refund_amt:.2f}",
          "Anticipated credit balance: aid (incl. anticipated Pell) exceeds Fall 2026 charges", "HELD",
          "Hold FV (HLD-01) active", f"Within {REFUND_RELEASE_BUSINESS_DAYS} business days after all holds clear",
          "Direct deposit to Prairie State CU x4417"]])

    # ---- lease (dates as YYYY/MM/DD) ------------------------------------------------------
    summary["lease/lease_terms.csv"] = write_csv(
        OUT / "lease" / "lease_terms.csv",
        ["term_id", "lease_ref", "landlord", "premises", "tenant", "start_date", "end_date", "monthly_rent",
         "rent_due_day", "grace_period_days", "late_fee", "security_deposit", "utilities_included", "payment_method"],
        [["LT-01", "GPM-2026-0817", "Greenway Property Management", f"{STUDENT['address']} (2BR, shared)",
          STUDENT["name"], "2026/08/01", "2027/07/31", f"{RENT:.2f}", str(RENT_DUE_DAY), str(RENT_GRACE_DAYS),
          f"{RENT_LATE_FEE:.2f}", f"{RENT:.2f}", "Water, trash", "Resident portal (ACH)"]])
    rent_rows = []
    for n, m in enumerate(range(8, 13), start=1):
        due = date(2026, m, RENT_DUE_DAY)
        paid = due <= TODAY
        rent_rows.append([f"RS-{n:02d}", due.strftime("%Y-%m"), due.strftime("%Y/%m/%d"), f"{RENT:.2f}",
                          "PAID" if paid else "UPCOMING", due.strftime("%Y/%m/%d") if paid else ""])
    summary["lease/rent_schedule.csv"] = write_csv(
        OUT / "lease" / "rent_schedule.csv",
        ["schedule_id", "period", "due_date", "amount_due", "status", "paid_on"], rent_rows)

    # ---- shifts (dates as M/D/YY, 12-hour times) ------------------------------------------
    shift_rows, shift_ids = [], []
    for i, s in enumerate(shifts, start=1):
        sid = f"SHF-{i:03d}"
        shift_ids.append((sid, s))
        shift_rows.append([sid, fmt_short(s.day), s.start, s.end, f"{s.hours:.1f}" if s.status != "CALLED_OFF" else "0.0",
                           s.status, s.note])
    summary["shifts/shifts.csv"] = write_csv(
        OUT / "shifts" / "shifts.csv", ["shift_id", "shift_date", "start_time", "end_time", "hours", "status", "note"],
        shift_rows)
    summary["shifts/job.csv"] = write_csv(
        OUT / "shifts" / "job.csv",
        ["job_id", "employer", "position", "hourly_rate", "pay_frequency", "pay_rule", "withholding_pct", "deposit_to"],
        [["JOB-01", "State University Dining Services", "Barista, Bean There Cafe (Union)", f"{HOURLY_RATE:.2f}",
          "Semi-monthly", "1st-15th paid on the 18th; 16th-end paid on the 3rd; weekend pay dates move to the Friday before",
          f"{WITHHOLDING_PCT}", "Prairie State CU x4417"]])
    pay_rows, pay_ids = [], {}
    for i, (start, end, pay_day) in enumerate(periods, start=1):
        pid = f"PAY-{i:02d}"
        pay_ids[pay_day] = pid
        if pay_day <= TODAY:
            hours = sum((s.hours for s in shifts if start <= s.day <= end and s.status == "WORKED"), Decimal("0"))
            g, w, n = net_pay(hours)
            pay_rows.append([pid, fmt_short(start), fmt_short(end), fmt_short(pay_day), f"{hours:.1f}", f"{g:.2f}",
                             f"{w:.2f}", f"{n:.2f}", "PAID"])
        else:
            pay_rows.append([pid, fmt_short(start), fmt_short(end), fmt_short(pay_day), "", "", "", "", "UPCOMING"])
    summary["shifts/pay_periods.csv"] = write_csv(
        OUT / "shifts" / "pay_periods.csv",
        ["pay_period_id", "period_start", "period_end", "pay_date", "hours", "gross_pay", "withholding", "net_pay",
         "status"], pay_rows)

    # ---- PDFs (display only) --------------------------------------------------------------
    write_pdf(OUT / "aid" / "award_letter.pdf", [
        "# State University - Office of Student Financial Aid",
        "2026-2027 Financial Aid Award Letter", "",
        f"Student: {STUDENT['name']}    ID: {STUDENT['student_id']}    Class: {STUDENT['year']}",
        "Date: September 10, 2026", "",
        "# Your awards",
        *[f"  {a[3]:<36} {a[4]}   offered {money(Decimal(a[5])):>11}   accepted {money(Decimal(a[6])):>11}   {a[7]}"
          for a in awards],
        "",
        f"  Direct Subsidized Loan amounts are gross; a {SUB_LOAN_FEE_PCT}% origination fee is deducted at disbursement.",
        "",
        "# Action required: verification",
        "  Your FAFSA was selected for verification. Please submit:",
        "    - 2026-27 Verification Worksheet (Dependent)",
        "  Your Federal Pell Grant cannot be disbursed, and no credit-balance refund can be",
        "  issued, until verification is complete.",
        "", "This letter is a display copy. The award records are the official source.",
    ])
    write_pdf(OUT / "lease" / "lease_agreement.pdf", [
        "# Residential Lease Agreement (summary copy)",
        "Greenway Property Management    Lease ref: GPM-2026-0817", "",
        f"Tenant: {STUDENT['name']}",
        f"Premises: {STUDENT['address']} (2-bedroom, shared)",
        "Term: August 1, 2026 through July 31, 2027", "",
        "# Rent",
        f"  Monthly rent: {money(RENT)}, due on day {RENT_DUE_DAY} of each month.",
        f"  Grace period: {RENT_GRACE_DAYS} days. Late fee: {money(RENT_LATE_FEE)} if unpaid after the grace period.",
        "  Payment: resident portal (ACH).", "",
        "# Deposit and utilities",
        f"  Security deposit: {money(RENT)} (paid July 2026).",
        "  Included: water, trash. Tenant pays: electric, internet (shared with roommate).",
        "", "This document is a display copy. The lease records are the official source.",
    ])

    # ---- story 5 inputs (data summaries; the projection itself is engine.py) ---------------
    var_window = (SEMESTER_START, TODAY)
    n_days = (var_window[1] - var_window[0]).days + 1
    chk_var = -sum((t.amount for t in chk_txns if t.kind == "chk_var" and var_window[0] <= t.day <= var_window[1]),
                   Decimal("0"))
    card_var = -sum((t.amount for t in card_txns if t.kind == "card_var" and var_window[0] <= t.day <= var_window[1]),
                    Decimal("0"))
    chk_rate, card_rate = D(chk_var / n_days), D(card_var / n_days)
    next_card_payment = stmts[-1]["balance"]  # Oct 12 statement, autopay Nov 9
    refund_day = add_business_days(REFUND_FORM_SUBMITTED, REFUND_RELEASE_BUSINESS_DAYS)

    # ---- history checks -------------------------------------------------------------------
    problems = []
    fees = ids.get("overdraft_fee", [])
    if len(fees) != 1 or fees[0][1].day.month != 10 or fees[0][1].day.day > 3:
        problems.append(f"expected exactly one overdraft fee in early October, got {[(f[0], f[1].day) for f in fees]}")
    negatives = [(tid, t.day, bal) for tid, t, bal in
                 [(f"CHK-{i:04d}", t, b) for i, (t, b) in enumerate(chk_rows, start=1)]
                 if bal < 0 and not (date(2026, 10, 1) <= t.day <= date(2026, 10, 1))]
    if negatives:
        problems.append(f"checking negative outside Oct 1: {negatives[:3]}")
    if refund_amt != D("1850.00"):
        problems.append(f"refund is {refund_amt}, expected 1850.00")

    # ---- answer key -----------------------------------------------------------------------
    nov_pay = [p for p in periods if p[2] == date(2026, 11, 18)][0]
    nov_hours = sum((s.hours for s in shifts if nov_pay[0] <= s.day <= nov_pay[1]), Decimal("0"))
    oct_pay = [p for p in periods if p[2] == date(2026, 10, 16)][0]
    # A normal pay period: Oct 1-15's regular shifts, leaving out the two fall-break extras.
    oct_regular = [(sid, s) for sid, s in shift_ids
                   if oct_pay[0] <= s.day <= oct_pay[1] and s.status == "WORKED" and s.day not in EXTRA_SHIFTS]
    oct_hours = sum((s.hours for _, s in oct_regular), Decimal("0"))
    oct_extra_hours = sum((s.hours for s in shifts if s.day in EXTRA_SHIFTS and oct_pay[0] <= s.day <= oct_pay[1]),
                          Decimal("0"))
    oct1 = [(tid, t, bal) for kind in ("rent", "overdraft_fee", "paycheck") for tid, t, bal in ids[kind]
            if date(2026, 10, 1) <= t.day <= date(2026, 10, 2)]
    sep30_bal = [bal for tid, t, bal in [(f"CHK-{i:04d}", t, b) for i, (t, b) in enumerate(chk_rows, 1)]
                 if t.day <= date(2026, 9, 30)][-1]
    oct_rent = [r for r in oct1 if r[1].kind == "rent"][0]
    oct_fee = [r for r in oct1 if r[1].kind == "overdraft_fee"][0]
    oct_pay_row = [r for r in oct1 if r[1].kind == "paycheck"][0]
    answer_key = {
        "generated_by": "generate_maya_data.py",
        "seed": SEED,
        "demo_today": TODAY.isoformat(),
        "semester": [SEMESTER_START.isoformat(), SEMESTER_END.isoformat()],
        "stories": [
            {
                "id": 1, "title": "Aid refund held by a verification hold",
                "finding": f"Maya's {money(refund_amt)} Fall refund is held because her Pell Grant cannot disburse until "
                           "she submits the 2026-27 Verification Worksheet, and the bursar's FV hold blocks refunds.",
                "key_numbers": {"refund_amount": f"{refund_amt:.2f}", "pell_held": f"{PELL_FA26:.2f}",
                                "fall_charges": f"{fa_charges:.2f}", "aid_disbursed": f"{loan_net + STATE_GRANT_FA26:.2f}",
                                "hold_since": "2026-09-10",
                                "release_rule_business_days": REFUND_RELEASE_BUSINESS_DAYS},
                "evidence": [
                    {"source": "bursar", "table": "refunds", "row_ids": ["RFD-01"]},
                    {"source": "bursar", "table": "holds", "row_ids": ["HLD-01"]},
                    {"source": "bursar", "table": "ledger",
                     "row_ids": [led_ids[("FA26", c)] for c in ("TUIT", "SSVC", "HLTH", "TECH", "TRAN", "DSUB", "SOGR", "PELL")]},
                    {"source": "aid", "table": "disbursements", "row_ids": ["DSB-03"]},
                    {"source": "aid", "table": "requirements", "row_ids": ["REQ-01"]},
                ],
            },
            {
                "id": 2, "title": "Paying for two music subscriptions",
                "finding": f"Maya pays for two music services every month: Spotify {money(SPOTIFY)} on checking and "
                           f"Apple Music {money(APPLE_MUSIC)} on her credit card.",
                "key_numbers": {"spotify_monthly": f"{SPOTIFY:.2f}", "spotify_day": SPOTIFY_DAY,
                                "apple_music_monthly": f"{APPLE_MUSIC:.2f}", "apple_music_day": APPLE_MUSIC_DAY,
                                "combined_monthly": f"{SPOTIFY + APPLE_MUSIC:.2f}"},
                "evidence": [
                    {"source": "checking", "table": "transactions", "row_ids": [tid for tid, _, _ in ids["spotify"]]},
                    {"source": "card", "table": "transactions", "row_ids": [cid for cid, _ in card_ids["apple_music"]]},
                ],
            },
            {
                "id": 3, "title": "Overdraft fee because rent is due before payday",
                "finding": f"On Oct 1 the {money(RENT)} rent payment overdrew checking (balance {money(sep30_bal)} the night before), "
                           f"triggering a {money(OVERDRAFT_FEE)} Courtesy Pay fee one day before the Oct 2 paycheck arrived.",
                "key_numbers": {"balance_sep_30": f"{sep30_bal:.2f}", "rent": f"{RENT:.2f}",
                                "balance_after_rent": f"{oct_rent[2]:.2f}", "overdraft_fee": f"{OVERDRAFT_FEE:.2f}",
                                "paycheck_oct_2": f"{oct_pay_row[1].amount:.2f}", "rent_due_day": RENT_DUE_DAY,
                                "scheduled_payday": "3rd (Oct 3 is a Saturday, so paid Fri Oct 2)"},
                "evidence": [
                    {"source": "checking", "table": "transactions", "row_ids": [oct_rent[0], oct_fee[0], oct_pay_row[0]]},
                    {"source": "checking", "table": "account", "row_ids": ["ACCT-CHK-01"]},
                    {"source": "lease", "table": "lease_terms", "row_ids": ["LT-01"]},
                    {"source": "shifts", "table": "job", "row_ids": ["JOB-01"]},
                    {"source": "shifts", "table": "pay_periods", "row_ids": [pay_ids[date(2026, 10, 2)]]},
                ],
            },
            {
                "id": 4, "title": "Payment-plan installment lands in a short-paycheck week",
                "finding": f"The {money(PLAN_INSTALLMENT)} payment-plan installment is due Fri Nov 20, the same week as the "
                           f"Wed Nov 18 paycheck, which covers only {nov_hours:.0f} scheduled hours (vs {oct_hours:.0f} in a normal "
                           "pay period on her regular schedule) because of the cafe renovation.",
                "key_numbers": {"installment": f"{PLAN_INSTALLMENT:.2f}", "installment_due": "2026-11-20",
                                "paycheck_date": "2026-11-18", "nov_1_15_scheduled_hours": f"{nov_hours:.1f}",
                                "normal_period_hours": f"{oct_hours:.1f}",
                                "normal_period_basis": f"Oct 1-15 (PAY-04) regular shifts; PAY-04's {oct_hours + oct_extra_hours:.0f} "
                                                       f"paid hours include {oct_extra_hours:.0f} hours of extra fall-break shifts",
                                "hourly_rate": f"{HOURLY_RATE:.2f}",
                                "withholding_pct": f"{WITHHOLDING_PCT}"},
                "evidence": [
                    {"source": "bursar", "table": "payment_plan", "row_ids": ["PPI-04"]},
                    {"source": "shifts", "table": "pay_periods", "row_ids": [pay_ids[date(2026, 11, 18)], pay_ids[date(2026, 10, 16)]]},
                    {"source": "shifts", "table": "shifts",
                     "row_ids": [sid for sid, s in shift_ids if nov_pay[0] <= s.day <= nov_pay[1]]
                                + [sid for sid, _ in oct_regular]},
                    {"source": "shifts", "table": "job", "row_ids": ["JOB-01"]},
                ],
            },
            {
                "id": 5, "title": "The $400 Thanksgiving flight needs the refund AND one cancelled subscription",
                "finding": "Booking the $400 flight by Nov 10 keeps checking at or above $0 through Dec 18 only if the $1,850 "
                           "refund is released and Spotify is cancelled; with either one alone, checking goes below $0.",
                "key_numbers": {"flight_cost": f"{FLIGHT_COST:.2f}", "book_by": FLIGHT_BOOK_BY.isoformat(),
                                "start_balance_oct_26": f"{end_balance:.2f}", "refund": f"{refund_amt:.2f}",
                                "refund_date_if_released": refund_day.isoformat(),
                                "spotify_savings_through_dec_18": f"{SPOTIFY * 2:.2f}",
                                "apple_music_savings_through_dec_18": "0.00",
                                "scenarios": STORY5_EXPECTED["scenarios"]},
                "why_spotify_not_apple_music": "Spotify charges checking on Nov 14 and Dec 14. Apple Music's next charge (Nov 22) "
                                               "is on the card cycle that closes Dec 12 and is paid Jan 7, after the semester, "
                                               "so cancelling Apple Music does not help checking before Dec 18.",
                "projection_method": STORY5_METHOD,
                "projection_inputs": {"variable_spend_window": [var_window[0].isoformat(), var_window[1].isoformat()],
                                      "checking_variable_per_day": f"{chk_rate:.2f}",
                                      "card_variable_per_day": f"{card_rate:.2f}",
                                      "card_open_cycle_spend_oct_13_26": f"{open_cycle_spend:.2f}",
                                      "card_autopay_nov_9": f"{next_card_payment:.2f}",
                                      "card_statement_nov_12_projected":
                                          STORY5_EXPECTED["card_statement_nov_12_projected"]},
                "evidence": [
                    {"source": "checking", "table": "account", "row_ids": ["ACCT-CHK-01"]},
                    {"source": "checking", "table": "transactions", "row_ids": [tid for tid, _, _ in ids["spotify"]]},
                    {"source": "bursar", "table": "refunds", "row_ids": ["RFD-01"]},
                    {"source": "bursar", "table": "payment_plan", "row_ids": ["PPI-04"]},
                    {"source": "lease", "table": "rent_schedule", "row_ids": ["RS-04", "RS-05"]},
                    {"source": "card", "table": "statements", "row_ids": [stmt_ids[date(2026, 10, 12)]]},
                    {"source": "card", "table": "transactions", "row_ids": [cid for cid, _ in card_ids["apple_music"]]},
                    {"source": "shifts", "table": "pay_periods",
                     "row_ids": [pay_ids[p[2]] for p in periods if TODAY < p[2] <= SEMESTER_END]},
                    {"source": "shifts", "table": "shifts",
                     "row_ids": [sid for sid, s in shift_ids if s.status == "SCHEDULED"]},
                ],
            },
        ],
    }
    (OUT / "answer_key.json").write_text(json.dumps(answer_key, indent=2), encoding="utf-8")

    print("\nTables:")
    for k, v in summary.items():
        print(f"  {k}: {v} rows")
    if problems:
        print("\nHISTORY CHECK FAILED:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("\nHistory checks passed. Story 5 is checked by the engine: pytest tests/test_engine.py")


if __name__ == "__main__":
    main()
