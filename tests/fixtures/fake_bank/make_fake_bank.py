"""FAKE bank exports for the importer tests. NOT REAL DATA: a made-up student ("Sam"), made-up merchants, seeded.

    .venv/Scripts/python tests/fixtures/fake_bank/make_fake_bank.py

Writes the same transactions (Aug 1 - Oct 24, 2026) in three common export layouts:
  fake_bank_a_amount.csv      Date,Description,Amount            MM/DD/YYYY, one signed amount (debits negative), no balance
  fake_bank_b_debit_credit.csv Posting Date,Description,Debit,Credit,Balance   YYYY-MM-DD, "$1,050.00" style, balance
  fake_bank_c_parens.csv      Date,Payee,Amount,Running Balance   DD-MM-YYYY, negatives in parentheses, balance
"""
import csv
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
START, END = date(2026, 8, 1), date(2026, 10, 24)
OPENING = Decimal("1200.00")


def transactions():
    rng = random.Random(4242)
    out = []
    d = date(2026, 8, 7)                                   # paycheck every other Friday
    while d <= END:
        out.append((d, "CAMPUS BOOKSTORE PAYROLL DIRECT DEP", Decimal("612.40")))
        d += timedelta(days=14)
    for m in (8, 9, 10):
        out.append((date(2026, m, 1), "MAPLE COURT APTS RENT", Decimal("-1050.00")))
        out.append((date(2026, m, 12), "NETFLIX.COM", Decimal("-15.49")))
        out.append((date(2026, m, 20), "METRO WIRELESS BILL", Decimal("-45.00")))
    out.append((date(2026, 9, 3), "BEST BUY #1123", Decimal("-249.99")))
    d = START
    while d <= END:
        if d.weekday() == 5:
            out.append((d, f"FRESH MARKET #{rng.randint(10, 99)}", -Decimal(str(round(rng.uniform(28, 74), 2)))))
        if rng.random() < 0.22:
            out.append((d, rng.choice(["CAMPUS PIZZA", "BEAN BAR COFFEE", "TACO SPOT"]),
                        -Decimal(str(round(rng.uniform(6, 19), 2)))))
        if rng.random() < 0.06:
            out.append((d, "CITY TRANSIT FARE", Decimal("-2.75")))
        d += timedelta(days=1)
    out.sort(key=lambda t: (t[0], t[1]))
    return out


def money(x):
    return f"{x:,.2f}"


def main():
    rows, bal = [], OPENING
    for d, desc, amt in transactions():
        bal += amt
        rows.append((d, desc, amt, bal))
    with open(HERE / "fake_bank_a_amount.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Description", "Amount"])
        for d, desc, amt, _ in rows:
            w.writerow([d.strftime("%m/%d/%Y"), desc, f"{amt:.2f}"])
    with open(HERE / "fake_bank_b_debit_credit.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["Posting Date", "Description", "Debit", "Credit", "Balance"])
        for d, desc, amt, b in reversed(rows):              # newest first, like many bank exports
            w.writerow([d.isoformat(), desc, f"${money(-amt)}" if amt < 0 else "", f"${money(amt)}" if amt > 0 else "",
                        f"${money(b)}"])
    with open(HERE / "fake_bank_c_parens.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Payee", "Amount", "Running Balance"])
        for d, desc, amt, b in rows:
            w.writerow([d.strftime("%d-%m-%Y"), desc, f"({money(-amt)})" if amt < 0 else money(amt), money(b)])
    print(f"{len(rows)} fake transactions; closing balance {money(rows[-1][3])}")


if __name__ == "__main__":
    main()
