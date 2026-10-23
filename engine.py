"""Money engine: deterministic projection, affordability, leaks and story findings (rules 2, 10, 11).

    import engine
    p = engine.project()                                         # the "nothing changes" scenario
    p.lowest.value, p.lowest_date.value, p.end_balance.value
    s = engine.Scenario(refund_released=True, cancel_subscriptions=("Spotify",))
    engine.project(s)                                            # what-if: recompute, no LLM
    a = engine.can_afford("400.00", "2026-11-10")                # yes / no / yes_if + the smallest fix set
    engine.find_leaks(), engine.refund_status(), engine.cash_crunches()

Every number is a Computed record (id "C#", label, value, unit, how, inputs). inputs are source row
IDs (CHK-0042, STM-004, ...) and other Computed ids, so EXPLAIN can cite [C#] and the UI can trace
any number to its rows. Computed values are signed for balances and money flows (money out
negative); values whose label says cost, charge, saves or amount owed are positive magnitudes.

Projection rule (CLAUDE.md rule 11), checking account, day by day from the day after DEMO_TODAY
through SEMESTER_END, starting from the checking account's current balance:
  - rent from the rent schedule, on the due date;
  - paychecks for upcoming pay periods: (worked + scheduled + scenario extra hours) x hourly rate,
    less withholding, on the pay date (pay-date rule from the job record);
  - payment-plan installments, on the due date or the next business day;
  - card autopay: each scheduled statement on its due date (next business day), then each projected
    statement = actual card purchases so far in the open cycle + card variable rate x remaining
    cycle days + card subscription charges in the cycle + scenario card purchases;
  - detected monthly items on checking (subscriptions, recurring bills) on their day of the month;
  - the held refund, if the scenario releases it: form submit date + N business days;
  - variable spending: per account, the semester-to-date daily average of variable purchases
    (non-recurring, under $100), rounded to the cent; one-offs ($100+) are not projected;
  - scenario purchases on their date (checking) or in their card cycle (card).
"""
import itertools
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

import config
import normalize

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
NO_HOURS = Decimal("0.0")


def D(x):
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


def fmt_money(x):
    x = D(x)
    return f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}"


def fmt_date(d):
    return f"{d.strftime('%a %b')} {d.day}, {d.year}"


def days(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def next_business_day(d):
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def prev_business_day(d):
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def add_business_days(d, n):
    """n business days after d (Mon-Fri; holidays are not modeled)."""
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def add_months(d, n=1):
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    last = ((date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


def pay_period_for(d):
    """Pay-date rule (job record): 1st-15th paid on the 18th; 16th-end paid on the 3rd of next month;
    a pay date on a weekend moves to the Friday before. Returns (period_start, period_end, pay_date)."""
    if d.day <= 15:
        return d.replace(day=1), d.replace(day=15), prev_business_day(d.replace(day=18))
    nxt = add_months(d.replace(day=1))
    return d.replace(day=16), nxt - timedelta(days=1), prev_business_day(nxt.replace(day=3))


def _date(x):
    return x if isinstance(x, date) else date.fromisoformat(str(x))


# ---------------------------------------------------------------------------------------
# Computed records
# ---------------------------------------------------------------------------------------
@dataclass
class Computed:
    id: str
    label: str
    value: object                # Decimal (USD, hours, weeks), date, int, bool, str or None
    unit: str                    # "USD", "date", "days", "weeks", "hours", "count", "percent", "flag", "text"
    how: str                     # plain English
    inputs: list                 # row IDs and Computed ids

    def to_dict(self):
        v = self.value
        return {"id": self.id, "label": self.label, "unit": self.unit, "how": self.how, "inputs": list(self.inputs),
                "value": v.isoformat() if isinstance(v, date) else (str(v) if isinstance(v, Decimal) else v)}


class Ledger:
    """Hands out Computed ids (C1, C2, ...) and keeps every record for the EXPLAIN step."""

    def __init__(self):
        self.items = []

    def add(self, label, value, unit, how, inputs=()):
        ids = [i.id if isinstance(i, Computed) else i for i in inputs]
        c = Computed(f"C{len(self.items) + 1}", label, value, unit, how, list(dict.fromkeys(ids)))
        self.items.append(c)
        return c

    def get(self, cid):
        return self.items[int(cid[1:]) - 1]

    def to_list(self):
        return [c.to_dict() for c in self.items]


# ---------------------------------------------------------------------------------------
# Scenario (the what-if panel's input). Defaults = "nothing changes".
# ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ExtraShift:
    date: date
    hours: Decimal


@dataclass(frozen=True)
class Purchase:
    cost: Decimal                # positive: what it costs
    date: date
    account: str = "checking"    # "checking" (debit) or "card"
    label: str = "purchase"


@dataclass(frozen=True)
class Scenario:
    refund_released: bool = False
    refund_submit_date: date | None = None     # when the missing form is submitted; None = day after DEMO_TODAY
    cancel_subscriptions: tuple = ()           # canonical merchant names, e.g. ("Spotify",)
    extra_shifts: tuple = ()                   # ExtraShift
    purchases: tuple = ()                      # Purchase

    def __post_init__(self):
        today = config.DEMO_TODAY
        for p in self.purchases:
            if p.account not in ("checking", "card"):
                raise ValueError(f"purchase account must be 'checking' or 'card', got {p.account!r}")
            if not today < p.date <= config.SEMESTER_END:
                raise ValueError(f"purchase date {p.date} must be after {today} and on or before {config.SEMESTER_END}")
            if p.cost <= 0:
                raise ValueError("purchase cost must be positive")
        for s in self.extra_shifts:
            if not today < s.date <= config.SEMESTER_END or s.hours <= 0:
                raise ValueError(f"extra shift must be after {today}, within the semester, with hours > 0")
        if self.refund_submit_date is not None and self.refund_submit_date <= today:
            raise ValueError("refund_submit_date must be after DEMO_TODAY")

    @property
    def submit_date(self):
        return self.refund_submit_date or config.DEMO_TODAY + timedelta(days=1)

    def plus(self, **changes):
        """A copy with changes; tuple fields are appended to, not replaced."""
        merged = {}
        for k, v in changes.items():
            cur = getattr(self, k)
            merged[k] = tuple(dict.fromkeys(cur + tuple(v))) if isinstance(cur, tuple) else v
        return replace(self, **merged)

    def describe(self):
        parts = []
        if self.refund_released:
            parts.append(f"refund released (form submitted {self.submit_date})")
        parts += [f"cancel {m}" for m in self.cancel_subscriptions]
        parts += [f"extra shift {s.date} {s.hours}h" for s in self.extra_shifts]
        parts += [f"{p.label} {fmt_money(p.cost)} on {p.date} ({p.account})" for p in self.purchases]
        return "; ".join(parts) or "nothing changes"


def scenario_from_dict(d):
    """Scenario from plain JSON-ish values (what the PLAN step or the UI sends)."""
    d = dict(d or {})
    return Scenario(
        refund_released=bool(d.get("refund_released", False)),
        refund_submit_date=_date(d["refund_submit_date"]) if d.get("refund_submit_date") else None,
        cancel_subscriptions=tuple(d.get("cancel_subscriptions", ())),
        extra_shifts=tuple(ExtraShift(_date(s["date"]), Decimal(str(s["hours"]))) for s in d.get("extra_shifts", ())),
        purchases=tuple(Purchase(Decimal(str(p["cost"])), _date(p["date"]), p.get("account", "checking"),
                                 p.get("label", "purchase")) for p in d.get("purchases", ())))


# ---------------------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------------------
def _ds(ds):
    return ds or normalize.load()


def variable_rate(ds, account, ledger):
    """Semester-to-date daily average of variable purchases on one account, rounded to the cent."""
    start, today = config.SEMESTER_START, config.DEMO_TODAY
    rows = [t for t in ds.txns(account) if t.category == "variable" and t.amount < 0 and start <= t.date <= today]
    total = -sum((t.amount for t in rows), ZERO)
    n = (today - start).days + 1
    total_c = ledger.add(f"{account} variable spending, {start} to {today}", D(total), "USD",
                         f"Sum of {len(rows)} variable purchases (non-recurring, under $100) on {account} "
                         f"from {fmt_date(start)} to {fmt_date(today)}.", [t.row_id for t in rows])
    return ledger.add(f"{account} variable spending per day", D(total / n), "USD",
                      f"{fmt_money(total)} over {n} days ({start} to {today}), rounded to the cent.", [total_c])


@dataclass
class Recurring:
    account: str
    merchant: str
    category: str
    purpose: str | None
    amount: Decimal              # negative
    day: int
    rows: list                   # Txn history
    next_charges: list           # upcoming charge dates after DEMO_TODAY (to SEMESTER_END + 90 days)


def recurring_items(ds):
    """Detected monthly items (subscriptions, recurring bills) not projected from another table."""
    groups = {}
    for t in ds.txns():
        if t.category in ("subscription", "recurring_bill") and t.amount < 0 and not t.projected_from:
            groups.setdefault((t.account, t.merchant), []).append(t)
    out = []
    horizon = config.SEMESTER_END + timedelta(days=90)
    for (account, merchant), rows in sorted(groups.items()):
        rows.sort(key=lambda t: t.date)
        if len({(t.date.year, t.date.month) for t in rows}) < 2:
            continue                                    # one charge is not a monthly pattern
        last = rows[-1]
        charges, n = [], 1
        while (d := add_months(last.date, n)) <= horizon:
            if d > config.DEMO_TODAY:
                charges.append(d)
            n += 1
        out.append(Recurring(account, merchant, last.category, last.purpose, last.amount, last.date.day, rows, charges))
    return out


def subscriptions(ds=None):
    return [r for r in recurring_items(_ds(ds)) if r.category == "subscription"]


@dataclass
class CardCycle:
    start: date
    closing: date
    due: date
    pay_date: date               # next business day on/after due
    statement_id: str | None     # known statement, or None if projected
    amount: Computed             # statement balance (positive: owed)


def card_cycles(ds, scenario, card_rate, ledger, recurring):
    """Known scheduled statements, then projected cycles until a cycle starts after SEMESTER_END."""
    today, end = config.DEMO_TODAY, config.SEMESTER_END
    cycles = []
    for s in ds.statements:
        if s.status != "PAID":
            pay = next_business_day(s.due)
            c = ledger.add(f"card statement closing {s.closing} (autopay {pay})", D(-s.amount), "USD",
                           f"Statement {s.row_id} balance, paid in full by autopay from checking on the due date "
                           f"{fmt_date(s.due)}, or the next business day ({fmt_date(pay)}).", [s.row_id])
            cycles.append(CardCycle(s.cycle_start, s.closing, s.due, pay, s.row_id, c))
    last = max(ds.statements, key=lambda s: s.closing)
    start, closing, due = last.closing + timedelta(days=1), add_months(last.closing), add_months(last.due)
    card_subs = [r for r in recurring if r.account == "card" and r.merchant not in scenario.cancel_subscriptions]
    while start <= end:
        actual = [t for t in ds.card_txns if start <= t.date <= today and t.category != "card_payment"]
        actual_sum = -sum((t.amount for t in actual), ZERO)
        proj_from = max(start, today + timedelta(days=1))
        n_days = max((closing - proj_from).days + 1, 0)
        subs = [(r, d) for r in card_subs for d in r.next_charges if proj_from <= d <= closing]
        buys = [p for p in scenario.purchases if p.account == "card" and start <= p.date <= closing]
        total = actual_sum + card_rate.value * n_days - sum((r.amount for r, _ in subs), ZERO) + \
            sum((p.cost for p in buys), ZERO)
        pay = next_business_day(due)
        parts = []
        if actual:
            parts.append(f"{fmt_money(actual_sum)} of card purchases already made since {fmt_date(start)}")
        parts.append(f"{n_days} days x {fmt_money(card_rate.value)}/day of card variable spending "
                     f"({fmt_date(proj_from)} to {fmt_date(closing)})" if n_days else "no days left to project")
        parts += [f"{r.merchant} {fmt_money(-r.amount)} on {fmt_date(d)}" for r, d in subs]
        parts += [f"{p.label} {fmt_money(p.cost)} on {fmt_date(p.date)}" for p in buys]
        c = ledger.add(f"projected card statement closing {closing} (autopay {pay})", D(total), "USD",
                       f"Cycle {fmt_date(start)} to {fmt_date(closing)}: " + " + ".join(parts) +
                       f". Paid by autopay from checking on {fmt_date(pay)}"
                       + (" (after the semester ends)." if pay > end else "."),
                       [*(t.row_id for t in actual), card_rate, last.row_id,
                        *(t.row_id for r, _ in subs for t in r.rows)])
        cycles.append(CardCycle(start, closing, due, pay, None, c))
        start, closing, due = closing + timedelta(days=1), add_months(closing), add_months(due)
    return cycles


def _normal_hours(ds):
    """Hours of regular (not extra) worked shifts in the most recent paid pay period."""
    paid = max((p for p in ds.pay_periods if p.status == "PAID"), key=lambda p: p.pay_date)
    rows = [s for s in ds.shifts if paid.start <= s.date <= paid.end and s.status == "WORKED" and not s.is_extra]
    return paid, rows, sum((s.hours for s in rows), NO_HOURS)


def net_pay(hours, job):
    gross = D(hours * job.hourly_rate)
    withholding = D(gross * job.withholding_pct / 100)
    return gross, withholding, gross - withholding


@dataclass
class Paycheck:
    pay_date: date
    period_id: str | None
    start: date
    end: date
    hours: Decimal
    shift_ids: list
    net: Computed


def paychecks(ds, scenario, ledger):
    """Upcoming paychecks paid after DEMO_TODAY and by SEMESTER_END."""
    today, end, job = config.DEMO_TODAY, config.SEMESTER_END, ds.job
    periods = {(p.start, p.end): p for p in ds.pay_periods}
    for s in scenario.extra_shifts:                        # an extra shift may open a period not in the table
        start, stop, _ = pay_period_for(s.date)
        periods.setdefault((start, stop), None)
    out = []
    for (start, stop), p in sorted(periods.items()):
        pay = p.pay_date if p else pay_period_for(start)[2]
        if not today < pay <= end:
            continue
        rows = [s for s in ds.shifts if start <= s.date <= stop and s.status in ("WORKED", "SCHEDULED")]
        extra = [s for s in scenario.extra_shifts if start <= s.date <= stop]
        hours = sum((s.hours for s in rows), NO_HOURS) + sum((s.hours for s in extra), NO_HOURS)
        gross, wh, net = net_pay(hours, job)
        extra_txt = f" + {sum((s.hours for s in extra), NO_HOURS)} extra scenario hours" if extra else ""
        c = ledger.add(f"paycheck {pay}" + (f" ({p.row_id})" if p else ""), net, "USD",
                       f"Pay period {fmt_date(start)} to {fmt_date(stop)}: {len(rows)} worked/scheduled shifts "
                       f"({sum((s.hours for s in rows), NO_HOURS)} hours){extra_txt} = {hours} hours x "
                       f"{fmt_money(job.hourly_rate)}/hour = {fmt_money(gross)} gross, less {job.withholding_pct}% "
                       f"withholding ({fmt_money(wh)}) = {fmt_money(net)} net, paid {fmt_date(pay)}.",
                       [*([p.row_id] if p else []), *(s.row_id for s in rows), job.row_id])
        out.append(Paycheck(pay, p.row_id if p else None, start, stop, hours, [s.row_id for s in rows], c))
    return out


def refund_release_date(ds, scenario):
    r = _held_refund(ds)
    return add_business_days(scenario.submit_date, r.release_business_days) if r else None


def _held_refund(ds):
    return next((r for r in ds.refunds if r.status == "HELD"), None)


# ---------------------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------------------
@dataclass
class Event:
    date: date
    amount: Decimal              # signed effect on checking
    kind: str                    # rent, paycheck, installment, card_autopay, subscription, recurring_bill, refund, purchase
    label: str
    computed: Computed


@dataclass
class Projection:
    scenario: Scenario
    start_balance: Computed
    checking_rate: Computed
    card_rate: Computed
    events: list
    daily: list                  # [(date, Decimal end-of-day balance)]
    cycles: list                 # CardCycle
    paychecks: list
    lowest: Computed
    lowest_date: Computed
    end_balance: Computed
    first_below_zero: Computed   # value None if never
    runway_weeks: Computed
    lasts_through_semester: bool
    ledger: Ledger
    key: list = field(default_factory=list)   # the headline Computed records

    def balance_on(self, d):
        return dict(self.daily)[_date(d)]

    def to_dict(self):
        return {"scenario": self.scenario.describe(),
                "daily": [(d.isoformat(), str(b)) for d, b in self.daily],
                "events": [{"date": e.date.isoformat(), "amount": str(e.amount), "kind": e.kind, "label": e.label,
                            "computed": e.computed.id} for e in self.events],
                "key": [c.id for c in self.key], "computed": self.ledger.to_list()}


def project(scenario=None, ds=None, ledger=None):
    """Daily checking projection from the day after DEMO_TODAY through SEMESTER_END."""
    scenario, ds = scenario or Scenario(), _ds(ds)
    ledger = ledger if ledger is not None else Ledger()
    today, end = config.DEMO_TODAY, config.SEMESTER_END
    acct = ds.checking_account
    start = ledger.add(f"checking balance on {today}", D(acct.current_balance), "USD",
                       f"Current balance of checking account {acct.row_id} as of {fmt_date(acct.as_of)}.",
                       [acct.row_id])
    chk_rate = variable_rate(ds, "checking", ledger)
    card_rate = variable_rate(ds, "card", ledger)
    recurring = recurring_items(ds)
    events = []

    def add(d, amount, kind, label, computed):
        if today < d <= end:
            events.append(Event(d, D(amount), kind, label, computed))

    for r in ds.rent_schedule:
        if r.status != "PAID" and today < r.due <= end:
            add(r.due, r.amount, "rent", f"rent {r.period}",
                ledger.add(f"rent due {r.due}", D(-r.amount), "USD",
                           f"Rent for {r.period} from the rent schedule ({r.row_id}), due {fmt_date(r.due)}.",
                           [r.row_id, ds.lease.row_id]))
    for pc in paychecks(ds, scenario, ledger):
        add(pc.pay_date, pc.net.value, "paycheck", pc.net.label, pc.net)
    for i in ds.installments:
        post = next_business_day(i.due)
        if i.status != "PAID" and today < post <= end:
            add(post, i.amount, "installment", f"payment-plan installment {i.number}",
                ledger.add(f"payment-plan installment {i.number} ({post})", D(-i.amount), "USD",
                           f"Installment {i.row_id} due {fmt_date(i.due)}, auto-debited from checking on the due "
                           f"date or the next business day ({fmt_date(post)}).", [i.row_id]))
    cycles = card_cycles(ds, scenario, card_rate, ledger, recurring)
    for c in cycles:
        add(c.pay_date, -c.amount.value, "card_autopay", c.amount.label, c.amount)
    for r in recurring:
        if r.account != "checking" or r.merchant in scenario.cancel_subscriptions:
            continue
        for d in r.next_charges:
            if d <= end:
                add(d, r.amount, r.category, f"{r.merchant} {d}",
                    ledger.add(f"{r.merchant} charge {d}", D(-r.amount), "USD",
                               f"{r.merchant} charges checking {fmt_money(-r.amount)} monthly on day {r.day} "
                               f"(last {len(r.rows)} charges); next charge {fmt_date(d)}.",
                               [t.row_id for t in r.rows]))
    refund = _held_refund(ds)
    if scenario.refund_released and refund:
        rel = refund_release_date(ds, scenario)
        add(rel, refund.amount, "refund", "aid refund released",
            ledger.add(f"refund deposit {rel}", D(refund.amount), "USD",
                       f"Refund {refund.row_id} ({fmt_money(refund.amount)}) is released {refund.release_business_days} "
                       f"business days after the hold clears; assuming the missing form is submitted "
                       f"{fmt_date(scenario.submit_date)}, it arrives {fmt_date(rel)}.", [refund.row_id]))
    for p in scenario.purchases:
        if p.account == "checking":
            add(p.date, -p.cost, "purchase", p.label,
                ledger.add(f"{p.label} on {p.date} (checking)", D(p.cost), "USD",
                           f"Scenario: {p.label} costing {fmt_money(p.cost)} paid by debit card on {fmt_date(p.date)}.", []))
    events.sort(key=lambda e: e.date)

    by_day = {}
    for e in events:
        by_day.setdefault(e.date, []).append(e)
    bal, daily, low, low_day, first_neg = start.value, [], None, None, None
    for d in days(today + timedelta(days=1), end):
        bal = bal - chk_rate.value + sum((e.amount for e in by_day.get(d, [])), ZERO)
        daily.append((d, bal))
        if low is None or bal < low:
            low, low_day = bal, d
        if first_neg is None and bal < 0:
            first_neg = d

    n_days = (end - today).days
    var_total = ledger.add(f"checking variable spending {today + timedelta(days=1)} to {end}",
                           D(chk_rate.value * n_days), "USD",
                           f"{n_days} days x {fmt_money(chk_rate.value)}/day.", [chk_rate])
    basis = [start, chk_rate, var_total, *(e.computed for e in events)]
    sc = scenario.describe()
    lowest = ledger.add(f"lowest checking balance through {end} ({sc})", D(low), "USD",
                        f"Day-by-day checking balance from {fmt_money(start.value)} on {fmt_date(today)}, applying "
                        f"{len(events)} scheduled items and {fmt_money(chk_rate.value)}/day variable spending; "
                        f"the lowest end-of-day balance is {fmt_money(low)} on {fmt_date(low_day)}.", basis)
    lowest_date = ledger.add(f"date of lowest checking balance ({sc})", low_day, "date",
                             f"First day the projected balance reaches its lowest point, {fmt_money(low)}.", [lowest])
    end_bal = ledger.add(f"checking balance on {end} ({sc})", D(bal), "USD",
                         f"Projected end-of-day checking balance on {fmt_date(end)}, the last day of the semester.",
                         basis)
    below = ledger.add(f"first date checking goes below $0 ({sc})", first_neg, "date",
                       f"First day the projected end-of-day balance is below $0: {fmt_date(first_neg)}."
                       if first_neg else f"The projected balance never goes below $0 through {fmt_date(end)}.", [lowest])
    if first_neg:
        span = (first_neg - today).days
        weeks = (Decimal(span) / 7).quantize(Decimal("0.1"), rounding=ROUND_DOWN)
        how = f"{span} days from {fmt_date(today)} until checking goes below $0 on {fmt_date(first_neg)}, / 7."
    else:
        span = (end - today).days
        weeks = (Decimal(span) / 7).quantize(Decimal("0.1"), rounding=ROUND_DOWN)
        how = (f"Money lasts through the end of the semester: {span} days from {fmt_date(today)} to "
               f"{fmt_date(end)}, / 7.")
    runway = ledger.add(f"runway in weeks ({sc})", weeks, "weeks", how, [below])
    return Projection(scenario, start, chk_rate, card_rate, events, daily, cycles,
                      [e for e in events if e.kind == "paycheck"], lowest, lowest_date, end_bal, below, runway,
                      first_neg is None, ledger, [start, lowest, lowest_date, end_bal, below, runway])


# ---------------------------------------------------------------------------------------
# Fixes and their timing-aware savings
# ---------------------------------------------------------------------------------------
@dataclass
class Fix:
    kind: str                    # "refund" or "cancel"
    name: str                    # "refund released" / merchant
    savings: Computed            # extra money in checking by SEMESTER_END (timing-aware)

    def apply(self, scenario):
        if self.kind == "refund":
            return replace(scenario, refund_released=True)
        return scenario.plus(cancel_subscriptions=(self.name,))


def subscription_savings(sub, ds, ledger, scenario=None):
    """What cancelling now saves checking by SEMESTER_END, given when each charge actually hits checking."""
    scenario, end = scenario or Scenario(), config.SEMESTER_END
    hits = []
    if sub.account == "checking":
        hits = [(d, d) for d in sub.next_charges]
    else:
        cyc = card_cycles(ds, scenario, variable_rate(ds, "card", Ledger()), Ledger(), [sub])
        for d in sub.next_charges:
            c = next((c for c in cyc if c.start <= d <= c.closing), None)
            hits.append((d, c.pay_date if c else None))
    hits = [(d, pay) for d, pay in hits if d <= end + timedelta(days=31)]
    saved = [(d, pay) for d, pay in hits if pay and pay <= end]
    amount = D(-sub.amount * len(saved))
    lines = []
    for d, pay in hits:
        if sub.account == "checking":
            lines.append(f"{fmt_date(d)} charge hits checking that day" + ("" if d <= end else ", after the semester"))
        else:
            lines.append(f"{fmt_date(d)} card charge is paid from checking on {fmt_date(pay)}"
                         + (" (before the semester ends)" if pay and pay <= end else " (after the semester ends)"))
    how = (f"{sub.merchant} charges {sub.account} {fmt_money(-sub.amount)} on day {sub.day} of each month. "
           + "; ".join(lines) + f". Charges that reach checking by {fmt_date(end)}: {len(saved)}, so cancelling now "
           f"saves checking {fmt_money(amount)} before the semester ends.")
    return ledger.add(f"cancel {sub.merchant}: savings for checking by {end}", amount, "USD", how,
                      [t.row_id for t in sub.rows])


def available_fixes(scenario, ds, ledger):
    """Every fix the student can still choose: release the held refund, cancel each active subscription."""
    fixes = []
    refund = _held_refund(ds)
    if refund and not scenario.refund_released:
        rel = refund_release_date(ds, scenario)
        amount = refund.amount if rel <= config.SEMESTER_END else ZERO
        holds = [h.row_id for h in ds.holds if "refund" in h.blocks.lower()]
        reqs = [r.row_id for r in ds.requirements if r.status != "SATISFIED"]
        fixes.append(Fix("refund", "refund released", ledger.add(
            f"release the held refund: added to checking by {config.SEMESTER_END}", D(amount), "USD",
            f"Refund {refund.row_id} ({fmt_money(refund.amount)}) is held; submitting the missing form on "
            f"{fmt_date(scenario.submit_date)} releases it {refund.release_business_days} business days later, "
            f"on {fmt_date(rel)}, by direct deposit to checking.", [refund.row_id, *holds, *reqs])))
    for sub in subscriptions(ds):
        if sub.merchant not in scenario.cancel_subscriptions:
            fixes.append(Fix("cancel", sub.merchant, subscription_savings(sub, ds, ledger, scenario)))
    return fixes


# ---------------------------------------------------------------------------------------
# Affordability
# ---------------------------------------------------------------------------------------
@dataclass
class Affordability:
    verdict: str                 # "yes", "no", "yes_if"
    purchase: Purchase
    without_fixes: Projection    # scenario + purchase
    fixes: list                  # the smallest set that works (yes_if), else []
    considered: list             # every available fix with its savings
    with_fixes: Projection | None
    alternatives: list           # other fix sets of the same size that also work
    verdict_computed: Computed
    ledger: Ledger

    def to_dict(self):
        return {"verdict": self.verdict, "fixes": [f.name for f in self.fixes],
                "considered": [{"fix": f.name, "savings": str(f.savings.value), "computed": f.savings.id}
                               for f in self.considered],
                "alternatives": [[f.name for f in s] for s in self.alternatives],
                "verdict_computed": self.verdict_computed.id, "computed": self.ledger.to_list()}


def can_afford(cost, on, account="checking", scenario=None, ds=None, label="purchase", buffer="0"):
    """Can checking stay at or above `buffer` through SEMESTER_END with this purchase?
    yes: as is. yes_if: with the smallest set of available fixes (refund release, subscription
    cancellations) that keeps it there. no: not even with every fix."""
    scenario, ds, ledger = scenario or Scenario(), _ds(ds), Ledger()
    buffer = D(buffer)
    purchase = Purchase(D(cost), _date(on), account, label)
    with_purchase = scenario.plus(purchases=(purchase,))
    base = project(with_purchase, ds, ledger)
    considered = available_fixes(scenario, ds, ledger)
    useful = [f for f in considered if f.savings.value > 0]
    desc = f"{label} {fmt_money(purchase.cost)} on {fmt_date(purchase.date)} ({account})"

    if base.lowest.value >= buffer:
        v = ledger.add(f"can afford {desc}", "yes", "text",
                       f"With the purchase, checking stays at or above {fmt_money(buffer)}: lowest "
                       f"{fmt_money(base.lowest.value)} on {fmt_date(base.lowest_date.value)}.", [base.lowest])
        return Affordability("yes", purchase, base, [], considered, None, [], v, ledger)

    working, scratch = [], Ledger()
    for size in range(1, len(useful) + 1):
        for combo in itertools.combinations(useful, size):
            s = with_purchase
            for f in combo:
                s = f.apply(s)
            low = project(s, ds, scratch).lowest.value
            if low >= buffer:
                working.append((low, combo))
        if working:
            break
    if not working:
        everything = with_purchase
        for f in useful:
            everything = f.apply(everything)
        best = project(everything, ds, ledger)
        v = ledger.add(f"can afford {desc}", "no", "text",
                       f"Without fixes the lowest balance is {fmt_money(base.lowest.value)}; even with every available "
                       f"fix ({', '.join(f.name for f in useful) or 'none'}) it is {fmt_money(best.lowest.value)} on "
                       f"{fmt_date(best.lowest_date.value)}, below {fmt_money(buffer)}.",
                       [base.lowest, best.lowest, *(f.savings for f in considered)])
        return Affordability("no", purchase, base, [], considered, best, [], v, ledger)

    working.sort(key=lambda w: w[0], reverse=True)          # most headroom first
    chosen = list(working[0][1])
    s = with_purchase
    for f in chosen:
        s = f.apply(s)
    result = project(s, ds, ledger)
    names = " and ".join(f.name for f in chosen)
    zero = [f for f in considered if f.savings.value <= 0]
    v = ledger.add(f"can afford {desc}", "yes_if", "text",
                   f"Without fixes the lowest balance is {fmt_money(base.lowest.value)} on "
                   f"{fmt_date(base.lowest_date.value)}. The smallest set of fixes that keeps checking at or above "
                   f"{fmt_money(buffer)} is: {names} (lowest {fmt_money(result.lowest.value)} on "
                   f"{fmt_date(result.lowest_date.value)})."
                   + (f" Not useful before the semester ends: {', '.join(f.name for f in zero)} (saves $0.00)."
                      if zero else ""),
                   [base.lowest, result.lowest, *(f.savings for f in considered)])
    return Affordability("yes_if", purchase, base, chosen, considered, result,
                         [list(c) for _, c in working[1:]], v, ledger)


# ---------------------------------------------------------------------------------------
# Leaks: duplicate-purpose subscriptions, fees
# ---------------------------------------------------------------------------------------
@dataclass
class Leak:
    kind: str                    # "duplicate_subscriptions" or "fee"
    title: str
    computed: list
    row_ids: list
    savings: Computed | None     # timing-aware, for checking by SEMESTER_END


def find_leaks(scenario=None, ds=None, ledger=None):
    scenario, ds = scenario or Scenario(), _ds(ds)
    ledger = ledger if ledger is not None else Ledger()
    leaks = []
    by_purpose = {}
    for sub in subscriptions(ds):
        if sub.merchant not in scenario.cancel_subscriptions and sub.purpose:
            by_purpose.setdefault(sub.purpose, []).append(sub)
    for purpose, subs in sorted(by_purpose.items()):
        if len(subs) < 2:
            continue
        monthly = [ledger.add(f"{s.merchant} monthly cost", D(-s.amount), "USD",
                              f"{s.merchant} charged {s.account} {fmt_money(-s.amount)} on day {s.day} of the month, "
                              f"{len(s.rows)} times ({', '.join(fmt_date(t.date) for t in s.rows)}).",
                              [t.row_id for t in s.rows]) for s in subs]
        combined = ledger.add(f"combined monthly cost of {purpose} subscriptions", D(sum(m.value for m in monthly)),
                              "USD", " + ".join(f"{s.merchant} {fmt_money(-s.amount)}" for s in subs) + ".", monthly)
        days_c = [ledger.add(f"{s.merchant} billing day", s.day, "count",
                             f"Day of the month of the latest {s.merchant} charge ({fmt_date(s.rows[-1].date)}).",
                             [s.rows[-1].row_id]) for s in subs]
        savings = [subscription_savings(s, ds, ledger, scenario) for s in subs]
        best = max(zip(savings, subs), key=lambda x: x[0].value)
        rec = ledger.add(f"which {purpose} subscription to cancel", best[1].merchant, "text",
                         f"Cancelling {best[1].merchant} saves checking {fmt_money(best[0].value)} by "
                         f"{fmt_date(config.SEMESTER_END)}; "
                         + "; ".join(f"{s.merchant} saves {fmt_money(c.value)}" for c, s in zip(savings, subs)
                                     if s is not best[1]) + ".", savings)
        leaks.append(Leak("duplicate_subscriptions",
                          f"Paying for {len(subs)} {purpose} subscriptions: " + ", ".join(s.merchant for s in subs),
                          [*monthly, combined, *days_c, *savings, rec],
                          [t.row_id for s in subs for t in s.rows], best[0]))

    chk = ds.checking_txns
    base = None
    for i, fee in enumerate(chk):
        if fee.category != "fee":
            continue
        cause = next((t for t in reversed(chk[:i]) if t.date == fee.date and t.amount < 0
                      and t.running_balance < 0 <= t.running_balance - t.amount), None)
        items, rows = [], [fee.row_id, ds.checking_account.row_id]
        fee_c = ledger.add(f"fee {fee.date}", D(-fee.amount), "USD",
                           f"{fee.merchant} on {fmt_date(fee.date)} ({fee.row_id}); the account's rule: "
                           f"{ds.checking_account.overdraft_rule}.", rows)
        items.append(fee_c)
        if cause:
            before = ledger.add(f"checking balance before {cause.merchant} on {cause.date}",
                                D(cause.running_balance - cause.amount), "USD",
                                f"Running balance after {cause.row_id} ({fmt_money(cause.running_balance)}) minus its "
                                f"amount ({fmt_money(cause.amount)}): the balance the night before.", [cause.row_id])
            amt = ledger.add(f"{cause.merchant} amount {cause.date}", D(-cause.amount), "USD",
                             f"{cause.row_id}: {cause.description}.", [cause.row_id])
            after = ledger.add(f"checking balance after {cause.merchant} on {cause.date}", D(cause.running_balance),
                               "USD", f"Running balance on {cause.row_id}, below $0, which triggered the fee.",
                               [cause.row_id])
            items += [before, amt, after]
            rows.insert(0, cause.row_id)
            if cause.category == "rent":
                items.append(ledger.add("rent due day", ds.lease.rent_due_day, "count",
                                        f"Lease {ds.lease.row_id}: rent is due on day {ds.lease.rent_due_day} of the month.",
                                        [ds.lease.row_id]))
                rows.append(ds.lease.row_id)
        pay = next((t for t in chk[i + 1:] if t.category == "income" and t.projected_from == "shifts/pay_periods"), None)
        if pay:
            period = next((p for p in ds.pay_periods if p.pay_date == pay.date), None)
            nominal = pay_period_for(period.end)[2] if period else None
            unshifted = (add_months(period.end.replace(day=1)).replace(day=3) if period and period.end.day > 15
                         else period.end.replace(day=18) if period else None)
            items.append(ledger.add(f"next paycheck after the fee ({pay.date})", D(pay.amount), "USD",
                                    f"{pay.row_id}: paycheck of {fmt_money(pay.amount)} arrived {fmt_date(pay.date)}, "
                                    f"{(pay.date - fee.date).days} day(s) after the fee"
                                    + (f"; its pay period {period.row_id} is paid on the {unshifted.day}"
                                       f"{'rd' if unshifted.day == 3 else 'th'} per the job's pay rule, and "
                                       f"{fmt_date(unshifted)} falls on a weekend, so it moved to the Friday before"
                                       if period and nominal != unshifted else "") + ".",
                                    [pay.row_id, *([period.row_id, ds.job.row_id] if period else [])]))
            rows += [pay.row_id, ds.job.row_id] + ([period.row_id] if period else [])
        if base is None:
            base = project(scenario, ds, Ledger())
        crossings = [d for (d, b), (_, prev) in zip(base.daily, [(None, base.start_balance.value)] + base.daily)
                     if b < 0 <= prev]
        future = ledger.add(f"overdraft fees avoidable by {config.SEMESTER_END} ({scenario.describe()})",
                            D(-fee.amount * len(crossings)), "USD",
                            f"The projection crosses below $0 on {len(crossings)} day(s)"
                            + (f" ({', '.join(fmt_date(d) for d in crossings)})" if crossings else "")
                            + f"; each crossing would trigger at least one {fmt_money(-fee.amount)} fee. "
                              "Staying above $0 avoids them.", [fee_c])
        items.append(future)
        title = f"{fmt_money(-fee.amount)} {fee.merchant} on {fmt_date(fee.date)}" + \
            (f": {cause.merchant} overdrew checking" if cause else "")
        leaks.append(Leak("fee", title, items, list(dict.fromkeys(rows)), future))
    return leaks


# ---------------------------------------------------------------------------------------
# Story findings: held refund, bills in short-paycheck weeks
# ---------------------------------------------------------------------------------------
@dataclass
class Finding:
    title: str
    computed: dict               # name -> Computed
    row_ids: dict                # (source, table) -> [row IDs]


def refund_status(scenario=None, ds=None, ledger=None):
    """Why the refund is held, how it is computed, and when it would arrive."""
    scenario, ds = scenario or Scenario(), _ds(ds)
    ledger = ledger if ledger is not None else Ledger()
    refund = _held_refund(ds)
    if not refund:
        return None
    term = [e for e in ds.ledger if e.term == refund.term]
    charges = [e for e in term if e.amount < 0 and not e.memo]
    paid_aid = [e for e in term if e.amount > 0 and not e.memo]
    anticipated = [e for e in term if e.amount > 0 and e.memo]
    holds = [h for h in ds.holds if "refund" in h.blocks.lower()]
    held = [d for d in ds.disbursements if d.status == "HELD"]
    reqs = [r for r in ds.requirements if r.status not in ("SATISFIED", "RECEIVED")]
    c = {}
    c["fall_charges"] = ledger.add(f"{refund.term} charges", D(-sum(e.amount for e in charges)), "USD",
                                   " + ".join(f"{e.description} {fmt_money(-e.amount)}" for e in charges) + ".",
                                   [e.row_id for e in charges])
    c["aid_disbursed"] = ledger.add(f"{refund.term} aid already paid to the account", D(sum(e.amount for e in paid_aid)),
                                    "USD", " + ".join(f"{e.description} {fmt_money(e.amount)}" for e in paid_aid) + ".",
                                    [e.row_id for e in paid_aid])
    c["pell_held"] = ledger.add("aid held (not disbursed)", D(sum(d.net for d in held)), "USD",
                                "; ".join(f"{d.row_id} {fmt_money(d.net)} status {d.status}: {d.hold_reason}" for d in held)
                                + ".", [*(d.row_id for d in held), *(e.row_id for e in anticipated)])
    computed_refund = D(sum(e.amount for e in paid_aid) + sum(e.amount for e in anticipated)
                        + sum(e.amount for e in charges))
    c["refund_amount"] = ledger.add(f"{refund.term} refund (credit balance)", D(refund.amount), "USD",
                                    f"Refund {refund.row_id}: {fmt_money(refund.amount)}, status {refund.status} "
                                    f"({refund.reason}). Check: aid paid {fmt_money(c['aid_disbursed'].value)} + "
                                    f"anticipated aid {fmt_money(sum(e.amount for e in anticipated))} - charges "
                                    f"{fmt_money(c['fall_charges'].value)} = {fmt_money(computed_refund)}.",
                                    [refund.row_id, c["fall_charges"], c["aid_disbursed"],
                                     *(e.row_id for e in anticipated)])
    if holds:
        h = min(holds, key=lambda h: h.from_date)
        c["hold_since"] = ledger.add(f"hold {h.code} active since", h.from_date, "date",
                                     f"Hold {h.row_id} ({h.description}) from {fmt_date(h.from_date)} blocks: {h.blocks}.",
                                     [h.row_id])
    c["release_rule_business_days"] = ledger.add("refund release rule (business days)", refund.release_business_days,
                                                 "days", f"{refund.row_id}: {refund.release_rule}.", [refund.row_id])
    rel = refund_release_date(ds, scenario)
    c["release_date"] = ledger.add("refund arrives if the form is submitted", rel, "date",
                                   f"Missing form submitted {fmt_date(scenario.submit_date)} + "
                                   f"{refund.release_business_days} business days = {fmt_date(rel)}.",
                                   [refund.row_id, *(r.row_id for r in reqs)])
    rows = {("bursar", "refunds"): [refund.row_id], ("bursar", "holds"): [h.row_id for h in holds],
            ("bursar", "ledger"): [e.row_id for e in charges + paid_aid + anticipated],
            ("aid", "disbursements"): [d.row_id for d in held], ("aid", "requirements"): [r.row_id for r in reqs]}
    return Finding(f"{fmt_money(refund.amount)} refund held: " + "; ".join(r.description for r in reqs), c, rows)


def cash_crunches(scenario=None, ds=None, ledger=None):
    """Upcoming payment-plan installments due in the same week (Mon-Sun) as a paycheck that covers
    fewer hours than a normal pay period."""
    scenario, ds = scenario or Scenario(), _ds(ds)
    ledger = ledger if ledger is not None else Ledger()
    normal_period, normal_rows, normal_hours = _normal_hours(ds)
    pcs = paychecks(ds, scenario, Ledger())
    out = []
    for inst in ds.installments:
        post = next_business_day(inst.due)
        if inst.status == "PAID" or not config.DEMO_TODAY < post <= config.SEMESTER_END:
            continue
        week = post - timedelta(days=post.weekday())
        pc = next((p for p in pcs if week <= p.pay_date <= week + timedelta(days=6)), None)
        if not pc or pc.hours >= normal_hours:
            continue
        sched = [ds.row(s) for s in pc.shift_ids]
        c = {}
        c["installment"] = ledger.add(f"payment-plan installment {inst.number}", D(-inst.amount), "USD",
                                      f"{inst.row_id}: {fmt_money(-inst.amount)} due {fmt_date(inst.due)}.", [inst.row_id])
        c["installment_due"] = ledger.add(f"installment {inst.number} due date", inst.due, "date",
                                          f"{inst.row_id} due date.", [inst.row_id])
        c["paycheck_date"] = ledger.add("paycheck in the same week", pc.pay_date, "date",
                                        f"Pay period {pc.period_id} ({fmt_date(pc.start)} to {fmt_date(pc.end)}) is "
                                        f"paid {fmt_date(pc.pay_date)}, the same week as the installment.",
                                        [pc.period_id])
        c["scheduled_hours"] = ledger.add(f"hours in pay period {pc.period_id}", pc.hours, "hours",
                                          f"{len(sched)} shifts: " + ", ".join(f"{fmt_date(s.date)} {s.hours}h"
                                                                               for s in sched) + ".",
                                          [pc.period_id, *pc.shift_ids])
        c["normal_period_hours"] = ledger.add("hours in a normal pay period", normal_hours, "hours",
                                              f"Regular shifts worked in the most recent paid period "
                                              f"{normal_period.row_id} ({fmt_date(normal_period.start)} to "
                                              f"{fmt_date(normal_period.end)}), leaving out extra shifts: "
                                              f"{len(normal_rows)} shifts.",
                                              [normal_period.row_id, *(s.row_id for s in normal_rows)])
        c["hourly_rate"] = ledger.add("hourly rate", ds.job.hourly_rate, "USD", f"Job {ds.job.row_id}.", [ds.job.row_id])
        c["withholding_pct"] = ledger.add("withholding", ds.job.withholding_pct, "percent", f"Job {ds.job.row_id}.",
                                          [ds.job.row_id])
        _, _, normal_net = net_pay(normal_hours, ds.job)
        c["paycheck_net"] = ledger.add(f"paycheck {pc.pay_date} net", pc.net.value, "USD", pc.net.how, pc.net.inputs)
        c["normal_net"] = ledger.add("net pay for a normal pay period", normal_net, "USD",
                                     f"{normal_hours} hours x {fmt_money(ds.job.hourly_rate)} less "
                                     f"{ds.job.withholding_pct}% withholding.",
                                     [c["normal_period_hours"], ds.job.row_id])
        rows = {("bursar", "payment_plan"): [inst.row_id],
                ("shifts", "pay_periods"): [pc.period_id, normal_period.row_id],
                ("shifts", "shifts"): [*pc.shift_ids, *(s.row_id for s in normal_rows)],
                ("shifts", "job"): [ds.job.row_id]}
        out.append(Finding(f"{fmt_money(-inst.amount)} installment due {fmt_date(inst.due)} in the same week as a "
                           f"short paycheck ({pc.hours} hours vs {normal_hours})", c, rows))
    return out
