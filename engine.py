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
import calendar
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
    budget: tuple = ()                         # ((flexible category, Decimal monthly amount), ...)
    approved: tuple = ()                       # opportunity ids "if approved" (what-if only; never certain money)
    meal_moves: int = 0                        # dining-dollar meals a week moved to swipes (negative: the other way)
    dining_dollars_added: Decimal = Decimal("0")   # dining dollars bought from checking tomorrow

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
        if self.refund_submit_date is not None and self.refund_submit_date < today:      # today = "sent today"
            raise ValueError("refund_submit_date can't be before DEMO_TODAY")
        for cat, amount in self.budget:
            if cat not in normalize.FLEXIBLE:
                raise ValueError(f"budget category {cat!r} is not a flexible category {normalize.FLEXIBLE}")
            if Decimal(amount) < 0:
                raise ValueError("budget amounts can't be negative")

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
        if self.budget:
            parts.append("budget " + ", ".join(f"{c} {fmt_money(a)}/month" for c, a in self.budget))
        parts += [f"if approved: {o}" for o in self.approved]
        if self.meal_moves:
            parts.append(f"{self.meal_moves} dining-dollar meal(s) a week moved to swipes")
        if self.dining_dollars_added:
            parts.append(f"{fmt_money(self.dining_dollars_added)} dining dollars added")
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
                                 p.get("label", "purchase")) for p in d.get("purchases", ())),
        budget=tuple((c, D(a)) for c, a in (d.get("budget") or {}).items()))


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


def card_cycles(ds, scenario, card_rate, ledger, recurring, card_daily=None):
    """Known scheduled statements, then projected cycles until a cycle starts after SEMESTER_END. card_daily(d):
    the budgeted card spending on day d (a budget is active), instead of the card rate."""
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
        projected = (sum((card_daily(d) for d in days(proj_from, closing)), ZERO) if card_daily and n_days
                     else card_rate.value * n_days)
        total = actual_sum + projected - sum((r.amount for r, _ in subs), ZERO) + sum((p.cost for p in buys), ZERO)
        pay = next_business_day(due)
        parts = []
        if actual:
            parts.append(f"{fmt_money(actual_sum)} of card purchases already made since {fmt_date(start)}")
        parts.append((f"{fmt_money(projected)} of budgeted card spending" if card_daily else
                      f"{n_days} days x {fmt_money(card_rate.value)}/day of card variable spending")
                     + f" ({fmt_date(proj_from)} to {fmt_date(closing)})" if n_days else "no days left to project")
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
    rates = budget_rates(scenario, ds, ledger) if scenario.budget else None

    def spend(account, d):                       # everyday spending on day d: the budget, else the average
        return rates[(account, d.year, d.month)].value if rates else (chk_rate if account == "checking"
                                                                      else card_rate).value
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
    cycles = card_cycles(ds, scenario, card_rate, ledger, recurring, (lambda d: spend("card", d)) if rates else None)
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
    for d, amount, label, computed in approved_events(scenario, ds, ledger):
        add(d, amount, "aid_if_approved", label, computed)
    if scenario.dining_dollars_added:
        add(today + timedelta(days=1), -scenario.dining_dollars_added, "meal_plan", "dining dollars added",
            ledger.add("dining dollars bought from checking", D(scenario.dining_dollars_added), "USD",
                       "What-if: dining dollars added to the meal plan, paid from checking tomorrow.", []))
    if scenario.meal_moves or scenario.dining_dollars_added:
        meal = meal_plan_status(scenario, ds, Ledger())
        if meal and meal.c["cost"].value and meal.runs_out:
            add(meal.runs_out, -meal.c["cost"].value, "meal_plan", "meals paid from checking", meal.c["cost"])
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
        bal = bal - spend("checking", d) + sum((e.amount for e in by_day.get(d, [])), ZERO)
        daily.append((d, bal))
        if low is None or bal < low:
            low, low_day = bal, d
        if first_neg is None and bal < 0:
            first_neg = d

    n_days = (end - today).days
    if rates:
        used = [c for (acct, *_), c in rates.items() if acct == "checking"]
        var_total = ledger.add(f"checking budgeted spending {today + timedelta(days=1)} to {end}",
                               D(sum((spend("checking", d) for d in days(today + timedelta(days=1), end)), ZERO)),
                               "USD", "Each day's budgeted checking spending, added up.", used)
        basis = [start, *used, var_total, *(e.computed for e in events)]
        spending_words = "the budget's everyday spending"
    else:
        var_total = ledger.add(f"checking variable spending {today + timedelta(days=1)} to {end}",
                               D(chk_rate.value * n_days), "USD",
                               f"{n_days} days x {fmt_money(chk_rate.value)}/day.", [chk_rate])
        basis = [start, chk_rate, var_total, *(e.computed for e in events)]
        spending_words = f"{fmt_money(chk_rate.value)}/day variable spending"
    sc = scenario.describe()
    lowest = ledger.add(f"lowest checking balance through {end} ({sc})", D(low), "USD",
                        f"Day-by-day checking balance from {fmt_money(start.value)} on {fmt_date(today)}, applying "
                        f"{len(events)} scheduled items and {spending_words}; "
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


@dataclass
class Reason:
    date: date                   # the key day: first day below $0, else the lowest day
    event: Event | None          # biggest scheduled outflow in the 7 days up to that day
    balance_before: Decimal | None   # end-of-day balance the day before the event


def main_reason(p):
    """What drives the projection's key moment: the biggest scheduled outflow in the week up to the first
    day below $0 (or, if money lasts, the lowest day). A lookup over the projection; no new math."""
    d = p.first_below_zero.value or p.lowest_date.value
    window = [e for e in p.events if e.amount < 0 and d - timedelta(days=6) <= e.date <= d]
    ev = min(window, key=lambda e: (e.amount, e.date), default=None)
    if ev is None:
        return Reason(d, None, None)
    prev = ev.date - timedelta(days=1)
    return Reason(d, ev, p.start_balance.value if prev <= config.DEMO_TODAY else p.balance_on(prev))


def latest_shift_paid_before(deadline, ds=None, ledger=None):
    """The latest day after DEMO_TODAY whose shift pay arrives before `deadline` (e.g. the run-out date), by the
    pay-date rule. Returns (shift-date Computed, pay-date Computed), or None if no such day exists."""
    ds = _ds(ds)
    ledger = ledger if ledger is not None else Ledger()
    d = deadline - timedelta(days=1)
    while d > config.DEMO_TODAY:
        period = next((p for p in ds.pay_periods if p.start <= d <= p.end), None)
        start, stop, pay = (period.start, period.end, period.pay_date) if period else pay_period_for(d)
        if pay < deadline:
            why = (f"A shift on {fmt_date(d)} is in the {fmt_date(start)} to {fmt_date(stop)} pay period, paid "
                   f"{fmt_date(pay)}, before {fmt_date(deadline)}. Any later shift is paid after that date.")
            inputs = [*([period.row_id] if period else []), ds.job.row_id]
            shift_c = ledger.add(f"latest shift paid before {deadline}", d, "date", why, inputs)
            pay_c = ledger.add(f"pay date for a shift on {d}", pay, "date",
                               f"Pay-date rule: the {fmt_date(start)} to {fmt_date(stop)} period is paid "
                               f"{fmt_date(pay)}.", inputs)
            return shift_c, pay_c
        d -= timedelta(days=1)
    return None


def extra_shift_pay(shift, ds=None, scenario=None, ledger=None):
    """How much one extra shift adds to its paycheck, and when that paycheck arrives (0 if after SEMESTER_END)."""
    scenario, ds = scenario or Scenario(), _ds(ds)
    ledger = ledger if ledger is not None else Ledger()
    without = replace(scenario, extra_shifts=tuple(s for s in scenario.extra_shifts if s != shift))
    start, stop, pay = pay_period_for(shift.date)
    period = next((p for p in ds.pay_periods if p.start <= shift.date <= p.end), None)
    if period:
        pay = period.pay_date
    before = {pc.start: pc for pc in paychecks(ds, without, Ledger())}
    after = next((pc for pc in paychecks(ds, without.plus(extra_shifts=(shift,)), Ledger())
                  if pc.start <= shift.date <= pc.end), None)
    if after is None:
        return pay, ledger.add(f"extra shift {shift.date} ({shift.hours} hours): added pay by {config.SEMESTER_END}",
                               ZERO, "USD", f"A shift on {fmt_date(shift.date)} is paid {fmt_date(pay)}, after the "
                               f"semester ends, so it adds nothing before {fmt_date(config.SEMESTER_END)}.",
                               [ds.job.row_id])
    old = before.get(after.start)
    added = after.net.value - (old.net.value if old else ZERO)
    return pay, ledger.add(f"extra shift {shift.date} ({shift.hours} hours): added pay", D(added), "USD",
                           f"The {fmt_date(after.pay_date)} paycheck goes from "
                           f"{fmt_money(old.net.value if old else ZERO)} ({old.hours if old else 0} hours) to "
                           f"{fmt_money(after.net.value)} ({after.hours} hours) after withholding.",
                           [*(after.net.inputs), ds.job.row_id])


def compare(base, current, ledger):
    """Change from the base projection to the current one (what-if deltas). Both must use `ledger`."""
    out = {}
    for key, unit in (("runway_weeks", "weeks"), ("lowest", "USD"), ("end_balance", "USD")):
        b, c = getattr(base, key), getattr(current, key)
        out[key] = ledger.add(f"change in {c.label.split(' (')[0]} vs nothing changes", c.value - b.value, unit,
                              f"{c.value} ({current.scenario.describe()}) minus {b.value} (nothing changes).", [c, b])
    return out


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


def subscription_timing(sub, ds, scenario=None):
    """[(charge date, date it reaches checking or None)] for the upcoming charges through one month
    after SEMESTER_END. A card charge reaches checking when its cycle's statement is paid."""
    scenario, end = scenario or Scenario(), config.SEMESTER_END
    if sub.account == "checking":
        hits = [(d, d) for d in sub.next_charges]
    else:
        cyc = card_cycles(ds, scenario, variable_rate(ds, "card", Ledger()), Ledger(), [sub])
        hits = []
        for d in sub.next_charges:
            c = next((c for c in cyc if c.start <= d <= c.closing), None)
            hits.append((d, c.pay_date if c else None))
    return [(d, pay) for d, pay in hits if d <= end + timedelta(days=31)]


def subscription_savings(sub, ds, ledger, scenario=None):
    """What cancelling now saves checking by SEMESTER_END, given when each charge actually hits checking."""
    end = config.SEMESTER_END
    hits = subscription_timing(sub, ds, scenario)
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
        short = D(-inst.amount) - pc.net.value
        if short > 0:
            c["shortfall"] = ledger.add("how much more the installment is than that paycheck", short, "USD",
                                        f"{fmt_money(-inst.amount)} installment - {fmt_money(pc.net.value)} paycheck.",
                                        [c["installment"], c["paycheck_net"]])
        rows = {("bursar", "payment_plan"): [inst.row_id],
                ("shifts", "pay_periods"): [pc.period_id, normal_period.row_id],
                ("shifts", "shifts"): [*pc.shift_ids, *(s.row_id for s in normal_rows)],
                ("shifts", "job"): [ds.job.row_id]}
        out.append(Finding(f"{fmt_money(-inst.amount)} installment due {fmt_date(inst.due)} in the same week as a "
                           f"short paycheck ({pc.hours} hours vs {normal_hours})", c, rows))
    return out


# ---------------------------------------------------------------------------------------
# Lookups for Ask Runway's data questions (spending, transactions, bills, work, balances, money ideas).
# Each returns Computed records that cite the rows they were read from.
# ---------------------------------------------------------------------------------------
SPENT_HOW = "Money out only; card payments are transfers between your own accounts, not spending."


def _txns(ds, account):
    return ds.checking_txns + ds.card_txns if account in (None, "both") else ds.txns(account)


def _range(start, end):
    """(start, end) dates; history questions can't look past DEMO_TODAY."""
    return _date(start), min(_date(end), config.DEMO_TODAY)


@dataclass
class Spending:
    start: date
    end: date
    group_by: str
    account: str
    groups: list                 # [(name, Computed spent (positive), count)] biggest first
    total: Computed
    count: int


def spending_summary(start, end, group_by="category", account="both", ds=None, ledger=None):
    """What was spent between start and end (inclusive, up to DEMO_TODAY), grouped by spending category or
    merchant. Totals are positive amounts spent; card payments (transfers) are not spending."""
    ds, ledger = _ds(ds), ledger if ledger is not None else Ledger()
    start, end = _range(start, end)
    where = {"both": "checking and card", "checking": "checking", "card": "the credit card"}[account]
    rows = [t for t in _txns(ds, account) if start <= t.date <= end and t.amount < 0
            and t.spending_category != normalize.TRANSFER]
    by = {}
    for t in rows:
        by.setdefault(t.spending_category if group_by == "category" else t.merchant, []).append(t)
    groups = []
    for name, ts in sorted(by.items(), key=lambda kv: sum(t.amount for t in kv[1])):
        spent = D(-sum(t.amount for t in ts))
        groups.append((name, ledger.add(f"spent on {name} {start} to {end} ({where})", spent, "USD",
                                        f"{len(ts)} purchase(s) in {name} from {fmt_date(start)} to {fmt_date(end)} "
                                        f"({where}). {SPENT_HOW}",
                                        [t.row_id for t in sorted(ts, key=lambda t: t.date, reverse=True)]), len(ts)))
    total = ledger.add(f"total spent {start} to {end} ({where})", D(-sum(t.amount for t in rows)), "USD",
                       f"Sum of {len(rows)} purchases from {fmt_date(start)} to {fmt_date(end)} ({where}), in "
                       f"{len(groups)} {'categories' if group_by == 'category' else 'merchants'}. {SPENT_HOW}",
                       [c for _, c, _ in groups])
    return Spending(start, end, group_by, account, groups, total, len(rows))


@dataclass
class Matches:
    query: str
    start: date
    end: date
    rows: list                   # Txn, newest first
    count: Computed
    spent: Computed | None       # money out, positive
    received: Computed | None    # money in
    last: Computed | None        # date of the newest match


def find_transactions(query, start=None, end=None, account="both", min_amount=None, max_amount=None, ds=None,
                      ledger=None):
    """Transactions whose merchant, description or spending category contains `query` (case-insensitive),
    between start and end (default: all history up to DEMO_TODAY), with an absolute amount between min_amount
    and max_amount."""
    ds, ledger = _ds(ds), ledger if ledger is not None else Ledger()
    start = _date(start) if start else min(t.date for t in _txns(ds, "both"))
    end = min(_date(end), config.DEMO_TODAY) if end else config.DEMO_TODAY
    q = (query or "").strip().lower()
    rows = [t for t in _txns(ds, account) if start <= t.date <= end
            and (not q or q in t.merchant.lower() or q in t.description.lower()
                 or q in (t.spending_category or "").lower())
            and (min_amount is None or abs(t.amount) >= D(min_amount))
            and (max_amount is None or abs(t.amount) <= D(max_amount))]
    rows.sort(key=lambda t: (t.date, t.row_id), reverse=True)
    what = f'"{query}"' if q else "all transactions"
    count = ledger.add(f"number of transactions matching {what} {start} to {end}", len(rows), "count",
                       f"Transactions from {fmt_date(start)} to {fmt_date(end)} whose merchant, description or "
                       f"category contains {what}.", [t.row_id for t in rows])
    out_rows = [t for t in rows if t.amount < 0 and t.spending_category != normalize.TRANSFER]
    in_rows = [t for t in rows if t.amount > 0 and t.spending_category != normalize.TRANSFER]
    spent = ledger.add(f"spent on {what} {start} to {end}", D(-sum(t.amount for t in out_rows)), "USD",
                       f"Sum of {len(out_rows)} matching purchases. {SPENT_HOW}",
                       [t.row_id for t in out_rows]) if out_rows else None
    received = ledger.add(f"received from {what} {start} to {end}", D(sum(t.amount for t in in_rows)), "USD",
                          f"Sum of {len(in_rows)} matching deposits.", [t.row_id for t in in_rows]) if in_rows else None
    last = ledger.add(f"most recent {what} transaction", rows[0].date, "date",
                      f"{rows[0].merchant} {fmt_money(rows[0].amount)} on {fmt_date(rows[0].date)}.",
                      [rows[0].row_id]) if rows else None
    return Matches(query, start, end, rows, count, spent, received, last)


BILL_KINDS = ("rent", "card_autopay", "installment", "subscription", "recurring_bill")


@dataclass
class Bills:
    start: date
    end: date
    events: list                 # Event, in date order
    total: Computed
    balance_after: Computed      # end-of-day balance on `end`


def upcoming_bills(start, end, scenario=None, ds=None, ledger=None):
    """Scheduled money out of checking between start and end, from the projection."""
    ds, ledger = _ds(ds), ledger if ledger is not None else Ledger()
    start = max(_date(start), config.DEMO_TODAY + timedelta(days=1))
    end = min(_date(end), config.SEMESTER_END)
    p = project(scenario, ds, ledger)
    events = [e for e in p.events if e.kind in BILL_KINDS and start <= e.date <= end]
    total = ledger.add(f"scheduled bills {start} to {end}", D(-sum((e.amount for e in events), ZERO)), "USD",
                       f"{len(events)} scheduled payment(s) out of checking from {fmt_date(start)} to {fmt_date(end)}"
                       + (": " + ", ".join(f"{e.label} {fmt_money(-e.amount)} on {fmt_date(e.date)}" for e in events)
                          if events else "") + ".", [e.computed for e in events])
    bal = ledger.add(f"checking balance at the end of {end}", p.balance_on(end), "USD",
                     f"Projected end-of-day checking balance on {fmt_date(end)}.",
                     [p.start_balance, *(e.computed for e in events)])
    return Bills(start, end, events, total, bal)


@dataclass
class Work:
    start: date
    end: date
    worked_hours: Computed
    scheduled_hours: Computed
    periods: list                # [(PayPeriod or Paycheck, Computed net pay, Computed pay date)] by pay date
    pay_total: Computed
    called_off: list             # Shift


def work_summary(start, end, scenario=None, ds=None, ledger=None):
    """Hours worked (past) and scheduled (future) between start and end, and the paychecks paid in that window:
    paid ones from pay_periods, upcoming ones from the paycheck rule."""
    ds, ledger = _ds(ds), ledger if ledger is not None else Ledger()
    start, end = _date(start), min(_date(end), config.SEMESTER_END)
    shifts = [s for s in ds.shifts if start <= s.date <= end]
    worked = [s for s in shifts if s.status == "WORKED"]
    sched = [s for s in shifts if s.status == "SCHEDULED"]
    worked_c = ledger.add(f"hours worked {start} to {end}", sum((s.hours for s in worked), NO_HOURS), "hours",
                          f"{len(worked)} worked shift(s) from {fmt_date(start)} to {fmt_date(end)}.",
                          [s.row_id for s in worked])
    sched_c = ledger.add(f"hours scheduled {start} to {end}", sum((s.hours for s in sched), NO_HOURS), "hours",
                         f"{len(sched)} scheduled shift(s) from {fmt_date(start)} to {fmt_date(end)}.",
                         [s.row_id for s in sched])
    periods = []
    for p in ds.pay_periods:
        if start <= p.pay_date <= end and p.status == "PAID":
            periods.append((p, ledger.add(f"paycheck {p.pay_date} net", p.net, "USD",
                                          f"{p.hours} hours, {fmt_money(p.gross)} gross, {fmt_money(p.net)} net, "
                                          f"paid {fmt_date(p.pay_date)}.", [p.row_id]),
                            ledger.add(f"pay date {p.pay_date}", p.pay_date, "date", "Pay period record.",
                                       [p.row_id])))
    for pc in paychecks(ds, scenario or Scenario(), ledger):
        if start <= pc.pay_date <= end:
            periods.append((pc, pc.net, ledger.add(f"pay date {pc.pay_date}", pc.pay_date, "date",
                                                   f"Pay-date rule: {fmt_date(pc.start)} to {fmt_date(pc.end)} is "
                                                   f"paid {fmt_date(pc.pay_date)}.",
                                                   [ds.job.row_id, *([pc.period_id] if pc.period_id else [])])))
    periods.sort(key=lambda x: x[2].value)
    total = ledger.add(f"pay from {start} to {end}", D(sum((n.value for _, n, _ in periods), ZERO)), "USD",
                       f"{len(periods)} paycheck(s) paid from {fmt_date(start)} to {fmt_date(end)}, after withholding.",
                       [n for _, n, _ in periods])
    return Work(start, end, worked_c, sched_c, periods, total, [s for s in shifts if s.status == "CALLED_OFF"])


@dataclass
class DayBalance:
    day: date
    balance: Computed
    events: list                 # Event (future) or Txn (past) on that day


def balance_on(day, scenario=None, ds=None, ledger=None):
    """Checking balance at the end of `day`: the bank's running balance for past days, the projection after
    DEMO_TODAY. With that day's events."""
    ds, ledger = _ds(ds), ledger if ledger is not None else Ledger()
    day = _date(day)
    if day > config.SEMESTER_END:
        raise ValueError(f"{day} is after the semester ends")
    if day <= config.DEMO_TODAY:
        rows = [t for t in ds.checking_txns if t.date <= day]
        last = max(rows, key=lambda t: (t.date, t.row_id)) if rows else None
        bal = ledger.add(f"checking balance at the end of {day}",
                         last.running_balance if last else ds.checking_account.opening_balance, "USD",
                         f"The bank's running balance after the last transaction on or before {fmt_date(day)}.",
                         [last.row_id] if last else [ds.checking_account.row_id])
        return DayBalance(day, bal, [t for t in ds.checking_txns if t.date == day])
    p = project(scenario, ds, ledger)
    evs = [e for e in p.events if e.date == day]
    bal = ledger.add(f"checking balance at the end of {day}", p.balance_on(day), "USD",
                     f"Projected end-of-day balance on {fmt_date(day)}"
                     + (": " + ", ".join(f"{e.label} {fmt_money(e.amount)}" for e in evs) if evs else
                        " (everyday spending only that day)") + ".",
                     [p.start_balance, p.checking_rate, *(e.computed for e in evs)])
    return DayBalance(day, bal, evs)


@dataclass
class Today:
    checking: Computed
    next_card_payment: Event | None
    refund: Computed | None      # held refund amount
    refund_release: Computed | None
    next_paycheck: Event | None
    next_paycheck_date: Computed | None


def accounts_today(scenario=None, ds=None, ledger=None):
    """Balances and what's pending as of DEMO_TODAY: checking, the next card payment, the held refund and when
    it would arrive, the next paycheck."""
    scenario, ds = scenario or Scenario(), _ds(ds)
    ledger = ledger if ledger is not None else Ledger()
    p = project(scenario, ds, ledger)
    card = next((e for e in p.events if e.kind == "card_autopay"), None)
    r = _held_refund(ds)
    refund = rel = None
    if r and not scenario.refund_released:
        refund = ledger.add("held refund", D(r.amount), "USD", f"Refund {r.status.lower()}: {r.reason}.",
                            [r.row_id])
        rel = ledger.add("refund arrival if the form is sent tomorrow", refund_release_date(ds, scenario), "date",
                         f"Released {r.release_business_days} business days after the form arrives.", [r.row_id])
    pc = next((e for e in p.events if e.kind == "paycheck"), None)
    pcd = ledger.add("next pay date", pc.date, "date", "Pay-date rule of the job.", [pc.computed, ds.job.row_id])         if pc else None
    return Today(p.start_balance, card, refund, rel, pc, pcd)


@dataclass
class Idea:
    kind: str                    # "refund", "shift", "cancel"
    name: str                    # plain words: "send the verification form", "cancel Spotify"
    amount: Computed             # money in (or kept) before the deadline
    arrives: Computed            # when the money arrives (or the first charge it avoids)
    detail: Computed | None = None   # the latest shift date, for shifts


def money_ideas(scenario=None, ds=None, ledger=None, shift_hours="4"):
    """Ways to get money before the run-out date (or the semester end, if the money lasts), ranked by when the
    money actually arrives: the held refund, an extra shift that is paid in time, cancellations that save
    before then. Returns (ideas, deadline Computed, projection)."""
    scenario, ds = scenario or Scenario(), _ds(ds)
    ledger = ledger if ledger is not None else Ledger()
    p = project(scenario, ds, ledger)
    deadline = p.first_below_zero.value or config.SEMESTER_END
    dl = ledger.add("deadline for the money", deadline, "date",
                    "The first day checking is projected below $0." if p.first_below_zero.value else
                    "The semester end (the money lasts until then).", [p.first_below_zero])
    ideas = []
    r = _held_refund(ds)
    if r and not scenario.refund_released:
        rel = refund_release_date(ds, scenario)
        if rel <= config.SEMESTER_END:
            ideas.append(Idea("refund", "send the verification form",
                              ledger.add("refund released by sending the form", D(r.amount), "USD",
                                         "Held until the missing verification form arrives.", [r.row_id]),
                              ledger.add("refund arrival date", rel, "date",
                                         f"Form sent {fmt_date(scenario.submit_date)}; released "
                                         f"{r.release_business_days} business days later.", [r.row_id])))
    if p.first_below_zero.value:
        latest = latest_shift_paid_before(deadline, ds, ledger)
        if latest:
            shift_c, pay_c = latest
            _, pay = extra_shift_pay(ExtraShift(shift_c.value, D(shift_hours)), ds, scenario, ledger)
            if pay.value > 0:
                ideas.append(Idea("shift", f"an extra {shift_hours}-hour shift", pay, pay_c, shift_c))
    for sub in subscriptions(ds):
        if sub.merchant in scenario.cancel_subscriptions:
            continue
        hits = [(d, pay) for d, pay in subscription_timing(sub, ds, scenario) if pay and pay < deadline]
        if hits:
            ideas.append(Idea("cancel", f"cancel {sub.merchant}",
                              ledger.add(f"cancel {sub.merchant}: savings before {deadline}",
                                         D(-sub.amount * len(hits)), "USD",
                                         f"{len(hits)} {sub.merchant} charge(s) would reach checking before "
                                         f"{fmt_date(deadline)}.", [t.row_id for t in sub.rows]),
                              ledger.add(f"first {sub.merchant} charge avoided", hits[0][1], "date",
                                         f"{sub.merchant} charges {sub.account} on day {sub.day}.",
                                         [t.row_id for t in sub.rows])))
    ideas.sort(key=lambda i: (i.arrives.value, -i.amount.value))
    return ideas, dl, p


# ---------------------------------------------------------------------------------------
# What needs the student's attention (the check-in): built from the findings above, no new money math
# beyond ranking. Later sources (aid, meal plan) add their own kinds to the same list.
# ---------------------------------------------------------------------------------------
@dataclass
class Attention:
    kind: str                    # "refund", "rent", "run_out", "subscriptions", "tight_week"
    due: Computed                # the date it needs doing by (or the day it happens)
    stake: Computed              # dollars at stake (positive)
    urgency: Computed            # dollars at stake per day of warning: sooner and bigger rank higher
    facts: dict                  # name -> Computed: the numbers its sentence states
    fix: tuple = ()              # what marking it done turns on: ("refund",) or ("cancel", "Spotify")
    row_ids: list = field(default_factory=list)


def _attention(kind, due, stake, facts, ledger, fix=(), row_ids=()):
    days_left = max((due.value - config.DEMO_TODAY).days, 1)
    urgency = ledger.add(f"urgency of {kind}", D(stake.value / days_left), "USD",
                         f"{fmt_money(stake.value)} at stake / {days_left} day(s) until {fmt_date(due.value)}.",
                         [stake, due])
    return Attention(kind, due, stake, urgency, facts, tuple(fix), list(dict.fromkeys(row_ids)))


def attention_items(scenario=None, ds=None, ledger=None):
    """What needs the student's attention, most urgent first (dollars at stake per day until it's due; the
    sooner date breaks ties): the held refund and its missing form, the next rent when rent before payday
    has caused an overdraft fee, the run-out date and the payment that causes it, duplicate subscriptions, and
    a tight week. Anything the scenario already fixes (form sent, subscription cancelled) drops out."""
    scenario, ds = scenario or Scenario(), _ds(ds)
    ledger = ledger if ledger is not None else Ledger()
    p = project(scenario, ds, ledger)
    out = []

    f = refund_status(scenario, ds, ledger) if not scenario.refund_released else None
    if f:
        c = f.computed
        due = ledger.add("send the verification form by", scenario.submit_date, "date",
                         "The day the form is sent (tomorrow unless the student picked another day).",
                         [c["release_date"]])
        out.append(_attention("refund", due, c["refund_amount"],
                              {"refund": c["refund_amount"], "arrives": c["release_date"]}, ledger, ("refund",),
                              [r for ids in f.row_ids.values() for r in ids]))

    leaks = find_leaks(scenario, ds, ledger)
    rent_fee = next((lk for lk in leaks if lk.kind == "fee" and any(x.label == "rent due day" for x in lk.computed)),
                    None)
    rent = next((e for e in p.events if e.kind == "rent"), None)
    if rent_fee and rent:
        fee = next(x for x in rent_fee.computed if x.label.startswith("fee "))
        left = ledger.add(f"checking balance at the end of {rent.date} (rent day)", p.balance_on(rent.date), "USD",
                          f"Projected end-of-day balance on {fmt_date(rent.date)}, after rent.", [p.lowest, rent.computed])
        due = ledger.add("rent due date", rent.date, "date", f"Rent due {fmt_date(rent.date)}.", [rent.computed])
        stake = ledger.add("rent amount", D(-rent.amount), "USD", f"Rent {fmt_money(-rent.amount)}.", [rent.computed])
        out.append(_attention("rent", due, stake, {"rent": stake, "left": left, "fee": fee}, ledger,
                              row_ids=rent_fee.row_ids))

    if p.first_below_zero.value:
        r = main_reason(p)
        facts = {"runs_out": p.first_below_zero}
        if r.event:
            facts["payment"] = ledger.add(f"{r.event.label} amount", D(-r.event.amount), "USD",
                                          f"{r.event.label} on {fmt_date(r.event.date)}.", [r.event.computed])
            facts["after"] = ledger.add(f"checking balance at the end of {r.event.date} (after that payment)",
                                        p.balance_on(r.event.date), "USD",
                                        f"Projected end-of-day balance on {fmt_date(r.event.date)}.",
                                        [p.lowest, r.event.computed])
        depth = ledger.add("how far below zero it goes", D(-p.lowest.value), "USD",
                           f"Lowest projected balance {fmt_money(p.lowest.value)} on {fmt_date(p.lowest_date.value)}.",
                           [p.lowest])
        out.append(_attention("run_out", p.first_below_zero, depth, facts, ledger))

    for lk in leaks:
        if lk.kind != "duplicate_subscriptions" or lk.savings.value <= 0:
            continue
        pick = next(x for x in lk.computed if x.label.startswith("which"))
        sub = next(s for s in subscriptions(ds) if s.merchant == pick.value)
        nxt = next((d for d, pay in subscription_timing(sub, ds, scenario) if d > config.DEMO_TODAY), None)
        if not nxt:
            continue
        combined = next(x for x in lk.computed if x.label.startswith("combined"))
        due = ledger.add(f"next {sub.merchant} charge", nxt, "date",
                         f"{sub.merchant} charges {sub.account} on day {sub.day}; cancel before then.",
                         [t.row_id for t in sub.rows])
        monthly = [x for x in lk.computed if x.label.endswith("monthly cost")]
        count = ledger.add("number of duplicate subscriptions", len(monthly), "count",
                           ", ".join(x.label.removesuffix(" monthly cost") for x in monthly) + ".", monthly)
        out.append(_attention("subscriptions", due, lk.savings,
                              {"monthly": combined, "saves": lk.savings, "pick": pick, "count": count},
                              ledger, ("cancel", sub.merchant), lk.row_ids))

    for fi in cash_crunches(scenario, ds, ledger)[:1]:
        c = fi.computed
        if "shortfall" in c:
            out.append(_attention("tight_week", c["installment_due"], c["shortfall"], dict(c), ledger,
                                  row_ids=[r for ids in fi.row_ids.values() for r in ids]))

    # an emergency grant she qualifies for, while there's a gap it could close in time (never counted as money)
    run_out = p.first_below_zero.value
    grant = next((x for x in eligible_opportunities(None, scenario, ds, ledger)
                  if x.opp.type == "emergency_grant" and x.status == "eligible" and x.opp.row_id not in scenario.approved),
                 None)
    if grant and run_out and grant.before_run_out:
        apply_by = grant.apply_on
        while opportunity_arrival(grant.opp, apply_by + timedelta(days=1))[1] < run_out:
            apply_by += timedelta(days=1)
        due = ledger.add("apply for the emergency grant by", apply_by, "date",
                         f"The last day to apply so that, if approved, it arrives before {fmt_date(run_out)}.",
                         [grant.arrives, p.first_below_zero])
        days_c = ledger.add("emergency grant decision time", grant.opp.decision_business_days, "days",
                            f"{grant.opp.name}: decided in about {grant.opp.decision_business_days} business days.",
                            [grant.opp.row_id])
        out.append(_attention("grant", due, grant.amount, {"amount": grant.amount, "arrives": grant.arrives,
                                                           "decision_days": days_c, "runs_out": p.first_below_zero},
                              ledger, row_ids=[grant.opp.row_id, ds.profile.row_id]))

    # the meal plan: dining dollars that run out before the semester ends
    meal = meal_plan_status(scenario, ds, ledger)
    if meal and meal.runs_out:
        out.append(_attention("meal_plan", meal.c["dd_runs_out"], meal.c["cost"],
                              {**meal.c, "tip_dd_end": meal.tip["dd_end"], "tip_sw_end": meal.tip["sw_end"]}, ledger,
                              row_ids=[ds.meal_plan.row_id]))

    out.sort(key=lambda a: (-a.urgency.value, a.due.value))
    return out


# ---------------------------------------------------------------------------------------
# Budgets: spending by category, money left after fixed bills, and a suggested budget
# ---------------------------------------------------------------------------------------
AVG_START = date(2026, 8, 1)             # the budget average covers Aug 1 to DEMO_TODAY (Aug-Oct)


def month_span(month):
    """(first day, last day) of a month given as "2026-11", a date, or (year, month)."""
    if isinstance(month, str):
        y, m = (int(x) for x in month.split("-")[:2])
    elif isinstance(month, date):
        y, m = month.year, month.month
    else:
        y, m = month
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


@dataclass
class CategoryTotal:
    name: str
    kind: str                    # "fixed" or "flexible"
    spent: Computed              # positive dollars
    txns: list                   # Txn, newest first


@dataclass
class CategorySpending:
    start: date
    end: date
    account: str
    categories: list             # CategoryTotal, biggest first
    total: Computed
    count: int

    def get(self, name):
        return next((c for c in self.categories if c.name == name), None)


def spending_by_category(start, end, account="both", ds=None, ledger=None):
    """Money out per spending category between start and end (up to DEMO_TODAY), card payments (transfers)
    left out; each category with the transactions behind it."""
    ds, ledger = _ds(ds), ledger if ledger is not None else Ledger()
    start, end = _date(start), min(_date(end), config.DEMO_TODAY)
    where = {"both": "checking and card", "checking": "checking", "card": "the credit card"}[account]
    rows = [t for t in _txns(ds, account) if start <= t.date <= end and t.amount < 0
            and t.spending_category != normalize.TRANSFER]
    by = {}
    for t in rows:
        by.setdefault(t.spending_category, []).append(t)
    cats = []
    for name, ts in sorted(by.items(), key=lambda kv: (sum(t.amount for t in kv[1]), kv[0])):
        ts = sorted(ts, key=lambda t: (t.date, t.row_id), reverse=True)
        spent = ledger.add(f"spent on {name} {start} to {end} ({where})", D(-sum(t.amount for t in ts)), "USD",
                           f"{len(ts)} purchase(s) in {name} from {fmt_date(start)} to {fmt_date(end)} ({where}). "
                           f"{SPENT_HOW}", [t.row_id for t in ts])
        cats.append(CategoryTotal(name, "fixed" if name in normalize.FIXED else "flexible", spent, ts))
    total = ledger.add(f"total spent {start} to {end} ({where})", D(sum((c.spent.value for c in cats), ZERO)), "USD",
                       f"Sum of {len(rows)} purchases in {len(cats)} categories. {SPENT_HOW}",
                       [c.spent for c in cats])
    return CategorySpending(start, end, account, cats, total, len(rows))


@dataclass
class MoneyToBudget:
    start: date
    end: date                    # the month, cut at SEMESTER_END
    start_balance: Computed      # projected checking balance going into the 1st
    money_in: Computed
    fixed: Computed
    amount: Computed             # start balance + money in - fixed (negative: the bills are bigger than her money)
    lines: list                  # [(label, date, signed Decimal, Computed)]


def money_to_budget(month, scenario=None, ds=None, ledger=None):
    """Money she can spend on everything flexible in `month`: her projected checking balance going into the 1st,
    plus money in (paychecks, the refund if released), minus fixed bills (rent, tuition installments,
    subscriptions on either account, recurring bills) and bills already owed that are paid that month (a card
    statement that has already closed), all from the projection. A card bill still being built from future
    spending is not counted: that spending is what the budget is for."""
    scenario, ds = scenario or Scenario(), _ds(ds)
    ledger = ledger if ledger is not None else Ledger()
    start, end = month_span(month)
    end = min(end, config.SEMESTER_END)
    p = project(replace(scenario, budget=()), ds, ledger)
    lines = [(e.label, e.date, e.amount, e.computed) for e in p.events if start <= e.date <= end
             and e.kind in ("paycheck", "refund", "rent", "installment", "subscription", "recurring_bill")]
    lines += [(f"card bill (statement closed {c.closing})", c.pay_date, -c.amount.value, c.amount) for c in p.cycles
              if c.statement_id and start <= c.pay_date <= end]                # already owed: the statement closed
    for r in recurring_items(ds):                      # card subscriptions: charged in the month, paid later
        if r.account == "card" and r.merchant not in scenario.cancel_subscriptions:
            for d in r.next_charges:
                if start <= d <= end:
                    lines.append((f"{r.merchant} {d}", d, r.amount, ledger.add(
                        f"{r.merchant} card charge {d}", D(-r.amount), "USD",
                        f"{r.merchant} charges the card {fmt_money(-r.amount)} monthly on day {r.day}.",
                        [t.row_id for t in r.rows])))
    lines.sort(key=lambda x: x[1])
    span = f"{fmt_date(start)} to {fmt_date(end)}"
    before = start - timedelta(days=1)
    start_bal = ledger.add(f"checking balance going into {fmt_date(start)}",
                           p.balance_on(before) if before > config.DEMO_TODAY else p.start_balance.value, "USD",
                           f"Projected end-of-day checking balance on {fmt_date(before)}."
                           if before > config.DEMO_TODAY else "Checking balance today.", [p.lowest])
    ins, outs = [x for x in lines if x[2] > 0], [x for x in lines if x[2] < 0]
    money_in = ledger.add(f"money in, {span}", D(sum((x[2] for x in ins), ZERO)), "USD",
                          " + ".join(f"{x[0]} {fmt_money(x[2])}" for x in ins) or "None.", [x[3] for x in ins])
    fixed = ledger.add(f"fixed bills, {span}", D(-sum((x[2] for x in outs), ZERO)), "USD",
                       " + ".join(f"{x[0]} {fmt_money(-x[2])}" for x in outs) or "None.", [x[3] for x in outs])
    amount = ledger.add(f"money to budget, {span}", start_bal.value + money_in.value - fixed.value, "USD",
                        f"Checking going into the month {fmt_money(start_bal.value)} + money in "
                        f"{fmt_money(money_in.value)} - fixed and already-owed bills {fmt_money(fixed.value)}.",
                        [start_bal, money_in, fixed])
    return MoneyToBudget(start, end, start_bal, money_in, fixed, amount, lines)


@dataclass
class BudgetLine:
    category: str
    average: Computed            # her average for a month this long (positive)
    suggested: Computed          # whole dollars


@dataclass
class Suggestion:
    start: date
    end: date
    lines: list                  # BudgetLine, flexible categories with spending, biggest first
    average_total: Computed
    available: MoneyToBudget
    total: Computed
    fits: bool                   # False: nothing is left after fixed bills, so no budget can fit

    def amounts(self):
        return {x.category: x.suggested.value for x in self.lines}


def suggest_budget(month, scenario=None, ds=None, ledger=None):
    """A budget for each flexible category: her Aug 1 to today daily average of everyday purchases ($100+
    one-offs left out, like the forecast), times the days in the month, rounded to whole dollars; scaled down (each
    category by the same share, rounded down) if the total is more than money_to_budget. If nothing is left after
    fixed bills, every amount is $0 and fits is False."""
    ds, ledger = _ds(ds), ledger if ledger is not None else Ledger()
    start, end = month_span(month)
    avail = money_to_budget(month, scenario, ds, ledger)
    past = spending_by_category(AVG_START, config.DEMO_TODAY, "both", ds, ledger)
    n = (config.DEMO_TODAY - AVG_START).days + 1
    month_days = (end - start).days + 1
    avgs = []
    for c in past.categories:
        everyday = [t for t in c.txns if t.category != "one_off"]
        if c.kind != "flexible" or not everyday:
            continue
        spent = D(-sum((t.amount for t in everyday), ZERO))
        skipped = len(c.txns) - len(everyday)
        avg = ledger.add(f"{c.name}: average for a {month_days}-day month",
                         D((spent / n * month_days).quantize(Decimal("1"), rounding=ROUND_HALF_UP)), "USD",
                         f"{fmt_money(spent)} of everyday {c.name} purchases from {fmt_date(AVG_START)} to "
                         f"{fmt_date(config.DEMO_TODAY)} ({n} days)"
                         + (f", leaving out {skipped} one-off purchase{'s' if skipped != 1 else ''} of $100 or more"
                            if skipped else "")
                         + f"; / {n} x {month_days} days, rounded to whole dollars.", [t.row_id for t in everyday])
        avgs.append((c.name, avg))
    avg_total = ledger.add("average flexible spending for the month", D(sum((a.value for _, a in avgs), ZERO)),
                           "USD", " + ".join(f"{name} {fmt_money(a.value)}" for name, a in avgs) + ".",
                           [a for _, a in avgs])
    room = avail.amount.value
    fits = room > 0
    scale = Decimal(1) if room >= avg_total.value else (room / avg_total.value if fits else Decimal(0))
    lines = []
    for name, a in avgs:
        v = a.value if scale == 1 else (a.value * scale).quantize(Decimal("1"), rounding=ROUND_DOWN)
        how = (f"Your average, {fmt_money(a.value)}." if scale == 1 else
               f"Your average {fmt_money(a.value)} x {scale:.4f} (to fit {fmt_money(room)}), rounded down."
               if fits else "Nothing is left after fixed bills, so $0.")
        lines.append(BudgetLine(name, a, ledger.add(f"suggested budget: {name}", D(v), "USD", how,
                                                    [a, avail.amount])))
    total = ledger.add("suggested budget total", D(sum((x.suggested.value for x in lines), ZERO)), "USD",
                       " + ".join(f"{x.category} {fmt_money(x.suggested.value)}" for x in lines) + ".",
                       [x.suggested for x in lines])
    return Suggestion(start, end, lines, avg_total, avail, total, fits)


# ---------------------------------------------------------------------------------------
# Budget in the forecast: each flexible category's monthly budget, spread evenly over the month's days and split
# between checking and the card the way she has split that category so far.
# ---------------------------------------------------------------------------------------
def budget_shares(ds, ledger, categories):
    """{category: (checking share, card share)} from Aug 1 to today; a category with no history is checking."""
    past = spending_by_category(AVG_START, config.DEMO_TODAY, "both", ds, Ledger())
    out = {}
    for cat in categories:
        c = past.get(cat)
        everyday = [t for t in c.txns if t.category != "one_off"] if c else []
        chk = -sum((t.amount for t in everyday if t.account == "checking"), ZERO)
        total = -sum((t.amount for t in everyday), ZERO)
        share = (chk / total) if total else Decimal(1)
        out[cat] = ledger.add(f"{cat}: share paid from checking", share, "percent",
                              (f"{fmt_money(chk)} of {fmt_money(total)} everyday {cat} spending from {fmt_date(AVG_START)} to "
                               f"{fmt_date(config.DEMO_TODAY)} was on checking; the rest on the card.") if total else
                              f"No {cat} spending yet, so the budget is assumed to come from checking.",
                              [t.row_id for t in everyday])
    return out


def budget_rates(scenario, ds, ledger):
    """{(account, year, month): Computed dollars per day} for every month the projection touches (card cycles run
    past the semester end, so two months more): each category's monthly budget x its account share / the days in
    that month, added up, rounded to the cent."""
    shares = budget_shares(ds, ledger, [c for c, _ in scenario.budget])
    out = {}
    d = config.DEMO_TODAY + timedelta(days=1)
    while d <= add_months(config.SEMESTER_END, 2):
        first, last = month_span(d)
        n = (last - first).days + 1
        for account in ("checking", "card"):
            parts = [(c, D(a), shares[c].value if account == "checking" else 1 - shares[c].value)
                     for c, a in scenario.budget]
            out[(account, d.year, d.month)] = ledger.add(
                f"{account} budgeted spending per day, {d:%Y-%m}",
                D(sum((a * sh for _, a, sh in parts), ZERO) / n), "USD",
                " + ".join(f"{c} {fmt_money(a)} x {sh:.3f}" for c, a, sh in parts) + f", / {n} days in {d:%B}.",
                [shares[c] for c, _ in scenario.budget])
        d = last + timedelta(days=1)
    return out


@dataclass
class BudgetEffect:
    without: Projection
    with_budget: Projection
    days_longer: Computed        # days the money lasts longer (negative: shorter); value None if neither runs out
    lowest_change: Computed      # lowest point with the budget minus without
    end_change: Computed


def budget_effect(scenario, ds=None, ledger=None):
    """The forecast with the scenario's budget vs the same scenario without it. When the money no longer runs out,
    "lasts" counts to the day after the semester ends."""
    ds, ledger = _ds(ds), ledger if ledger is not None else Ledger()
    without = project(replace(scenario, budget=()), ds, ledger)
    with_b = project(scenario, ds, ledger)
    after_end = config.SEMESTER_END + timedelta(days=1)

    def lasts(p):
        return p.first_below_zero.value or after_end

    a, b = lasts(without), lasts(with_b)
    longer = None if a == b == after_end else (b - a).days
    days_c = ledger.add("days the money lasts longer with the budget", longer, "days",
                        f"Runs out {fmt_date(b) if b != after_end else 'never this semester'} with the budget vs "
                        f"{fmt_date(a) if a != after_end else 'never this semester'} without"
                        + (f": {longer} days." if longer is not None else "."),
                        [with_b.first_below_zero, without.first_below_zero])
    low = ledger.add("change in the lowest point with the budget", with_b.lowest.value - without.lowest.value, "USD",
                     f"{fmt_money(with_b.lowest.value)} with the budget - {fmt_money(without.lowest.value)} without.",
                     [with_b.lowest, without.lowest])
    end = ledger.add("change in the end-of-semester balance with the budget",
                     with_b.end_balance.value - without.end_balance.value, "USD",
                     f"{fmt_money(with_b.end_balance.value)} with the budget - {fmt_money(without.end_balance.value)} "
                     "without.", [with_b.end_balance, without.end_balance])
    return BudgetEffect(without, with_b, days_c, low, end)


def budget_left(available, amounts, ledger):
    """Money to budget minus what the budget assigns (negative: assigned more than there is)."""
    assigned = D(sum((D(v) for v in amounts.values()), ZERO))
    return ledger.add("left to assign", available.value - assigned, "USD",
                      f"Money to budget {fmt_money(available.value)} - budgeted {fmt_money(assigned)} ("
                      + ", ".join(f"{c} {fmt_money(v)}" for c, v in amounts.items() if v) + ").", [available])


@dataclass
class Progress:
    category: str
    budget: Decimal
    spent: Computed
    left: Computed               # budget - spent (negative: over)
    expected: Computed           # the budget's share for the days gone so far
    pace: str                    # "on pace", "spending fast", "over"


def budget_progress(amounts, month=None, ds=None, ledger=None):
    """Spent so far this month (to DEMO_TODAY) per budgeted category vs its budget, and the pace: on pace if
    spending is within the budget's share of the days gone, spending fast if above it, over if past the budget."""
    ds, ledger = _ds(ds), ledger if ledger is not None else Ledger()
    start, end = month_span(month or config.DEMO_TODAY)
    today = min(config.DEMO_TODAY, end)
    gone, n = (today - start).days + 1, (end - start).days + 1
    sp = spending_by_category(start, today, "both", ds, ledger)
    out = []
    for cat, amount in amounts.items():
        b = D(amount)
        c = sp.get(cat)
        spent = c.spent if c else ledger.add(f"spent on {cat} {start} to {today}", ZERO, "USD", "No purchases.", [])
        left = ledger.add(f"{cat}: budget left", b - spent.value, "USD",
                          f"Budget {fmt_money(b)} - spent {fmt_money(spent.value)}.", [spent])
        expected = ledger.add(f"{cat}: budget for the days so far", D(b * gone / n), "USD",
                              f"{fmt_money(b)} x {gone} of {n} days.", [])
        pace = "over" if spent.value > b else "spending fast" if spent.value > expected.value else "on pace"
        out.append(Progress(cat, b, spent, left, expected, pace))
    return out


BUDGET_GROUPS = {"food": ("Groceries", "Eating out", "Meal plan")}


@dataclass
class BudgetStatus:
    month: tuple                 # (first day, last day)
    categories: tuple            # the flexible categories asked about (all budgeted ones when none named)
    rows: list                   # Progress per category
    budget: Computed | None      # totals over `categories` (None: no budget set)
    spent: Computed | None
    left: Computed | None
    pace: str | None
    effect: BudgetEffect | None  # the forecast with the budget vs without
    suggestion: Suggestion | None    # when no budget is set: what Runway would suggest for next month
    refund_released: bool = False


def budget_status(amounts, month=None, category=None, scenario=None, ds=None, ledger=None):
    """Spent, budget, left and pace this month for one category, a group ("food") or the whole budget, and what
    the budget does to the forecast. With no budget set: the suggested budget for next month instead."""
    scenario, ds = scenario or Scenario(), _ds(ds)
    ledger = ledger if ledger is not None else Ledger()
    span = month_span(month or config.DEMO_TODAY)
    cats = BUDGET_GROUPS.get((category or "").lower(), (category,) if category else tuple(normalize.FLEXIBLE))
    amounts = {c: D(v) for c, v in (amounts or {}).items() if D(v) > 0}
    if not amounts:
        nxt = add_months(span[0])
        return BudgetStatus(span, cats, [], None, None, None, None, None,
                            suggest_budget(nxt, replace(scenario, budget=()), ds, ledger), scenario.refund_released)
    rows = [r for r in budget_progress({c: amounts.get(c, ZERO) for c in cats if c in amounts or category},
                                       span[0], ds, ledger)]
    name = category or "the whole budget"
    b = ledger.add(f"budget for {name}", D(sum((r.budget for r in rows), ZERO)), "USD",
                   " + ".join(f"{r.category} {fmt_money(r.budget)}" for r in rows) + ".", [])
    spent = ledger.add(f"spent on {name} so far this month", D(sum((r.spent.value for r in rows), ZERO)), "USD",
                       " + ".join(f"{r.category} {fmt_money(r.spent.value)}" for r in rows) + ".",
                       [r.spent for r in rows])
    left = ledger.add(f"left in the budget for {name}", b.value - spent.value, "USD",
                      f"{fmt_money(b.value)} - {fmt_money(spent.value)} spent.", [b, spent])
    expected = sum((r.expected.value for r in rows), ZERO)
    pace = "over" if spent.value > b.value else "spending fast" if spent.value > expected else "on pace"
    effect = budget_effect(replace(scenario, budget=tuple((c, D(v)) for c, v in amounts.items())), ds, ledger)
    return BudgetStatus(span, cats, rows, b, spent, left, pace, effect, None, scenario.refund_released)


# ---------------------------------------------------------------------------------------
# Source 7: aid opportunities. Rule-based eligibility from her profile, and when the money would actually arrive.
# Opportunities are never certain money: they are only ever "if approved" what-ifs (Scenario.approved), never in
# the base forecast or can_afford's fix search.
# ---------------------------------------------------------------------------------------
ENROLLMENT_RANK = {"less than half-time": 0, "half-time": 1, "half-time or more": 1, "full-time": 2}


@dataclass
class OpportunityCheck:
    opp: object                  # normalize.Opportunity
    status: str                  # "eligible", "almost" (one requirement missing), "not_eligible"
    missing: list                # plain words: "a 3.50 GPA (yours is 3.40)"
    amount: Computed | None      # dollars (the award, or "up to"); None for work-study
    apply_on: date
    decided: date | None
    arrives: Computed | None     # when the money (or the first paycheck) would arrive, if approved
    this_semester: Computed | None   # what it adds to checking by SEMESTER_END (0 when it pays after)
    before_run_out: bool         # arrives before the run-out date (or the money doesn't run out)
    deadline_passed: bool


def _unmet(o, prof):
    """What she is missing for opportunity o, in plain words ([] = eligible)."""
    out = []
    if o.class_years and prof.class_year not in o.class_years:
        out.append(f"to be a {' or '.join(o.class_years)} (you're a {prof.class_year})")
    if ENROLLMENT_RANK.get(prof.enrollment, 0) < ENROLLMENT_RANK.get(o.enrollment, 0):
        out.append(f"{o.enrollment} enrollment (you're {prof.enrollment})")
    if o.min_gpa is not None and prof.gpa < o.min_gpa:
        out.append(f"a {o.min_gpa} GPA (yours is {prof.gpa})")
    if (o.pell_required or o.need_based) and not prof.pell_eligible:
        out.append("Pell eligibility" if o.pell_required else "financial need (Pell eligibility)")
    if o.fafsa_required and not prof.fafsa_on_file:
        out.append("a FAFSA on file")
    if o.majors and prof.major not in o.majors:
        out.append(f"a major in {' or '.join(o.majors)} (yours is {prof.major})")
    if o.residency not in ("any", "") and o.residency != prof.residency:
        out.append(f"{o.residency} residency")
    return out


def opportunity_arrival(o, apply_on):
    """(decided, arrives) if she applies on apply_on and it's approved: after the decision (+ payout days), after
    the deadline (+ payout days), on a fixed date, or (work-study) the first paycheck for a job starting the Monday
    after she's hired, by the campus pay-date rule."""
    if o.payout_rule == "after_decision":
        decided = add_business_days(apply_on, o.decision_business_days)
        return decided, add_business_days(decided, o.payout_business_days)
    if o.payout_rule == "after_deadline":
        return o.deadline, add_business_days(o.deadline, o.payout_business_days)
    if o.payout_rule == "fixed_date":
        return None, o.payout_date
    if o.payout_rule == "payroll":
        decided = add_business_days(apply_on, o.decision_business_days)
        start = decided + timedelta(days=(7 - decided.weekday()) % 7 or 7)
        return decided, pay_period_for(start)[2]
    raise ValueError(f"unknown payout rule {o.payout_rule!r}")


def eligible_opportunities(apply_on=None, scenario=None, ds=None, ledger=None):
    """Every opportunity with her eligibility (and what's missing), the amount, and when the money would arrive if
    she applies on apply_on (default tomorrow) and is approved: before the run-out date? before Dec 18?"""
    scenario, ds = scenario or Scenario(), _ds(ds)
    ledger = ledger if ledger is not None else Ledger()
    apply_on = _date(apply_on) if apply_on else config.DEMO_TODAY + timedelta(days=1)
    prof = ds.profile
    if not prof:
        return []
    run_out = project(replace(scenario, approved=()), ds, Ledger()).first_below_zero.value
    out = []
    for o in ds.opportunities:
        missing = _unmet(o, prof)
        status = "eligible" if not missing else "almost" if len(missing) == 1 else "not_eligible"
        passed = bool(o.deadline and apply_on > o.deadline)
        decided, arrives = opportunity_arrival(o, apply_on)
        money_ = o.amount or o.max_amount
        amount = ledger.add(f"{o.name}: amount", D(money_), "USD",
                            ("Up to " if o.max_amount and not o.amount else "") + f"{fmt_money(money_)} ({o.row_id}).",
                            [o.row_id]) if money_ else None
        how = {"after_decision": f"Applied {fmt_date(apply_on)}, decided in {o.decision_business_days} business days "
                                 f"({fmt_date(decided) if decided else ''}), paid by {o.payout_method} "
                                 f"{o.payout_business_days} business day(s) later",
               "after_deadline": f"Reviewed after the deadline {fmt_date(o.deadline) if o.deadline else ''}, paid "
                                 f"{o.payout_business_days} business days later",
               "fixed_date": f"Paid on {fmt_date(o.payout_date) if o.payout_date else ''} ({o.payout_method})",
               "payroll": f"Applied {fmt_date(apply_on)}, hired in {o.decision_business_days} business days "
                          f"({fmt_date(decided) if decided else ''}), starts the next Monday; first paycheck by the "
                          "campus pay-date rule"}[o.payout_rule]
        arr = ledger.add(f"{o.name}: money arrives if approved", arrives, "date", how + f": {fmt_date(arrives)}.",
                         [o.row_id, prof.row_id])
        in_time = arrives <= config.SEMESTER_END
        semester = ledger.add(f"{o.name}: adds to checking by {config.SEMESTER_END}",
                              D(money_) if (money_ and in_time) else ZERO, "USD",
                              (f"Arrives {fmt_date(arrives)}, " + ("before" if in_time else "after") +
                               f" the semester ends ({fmt_date(config.SEMESTER_END)})."), [arr]) if money_ else None
        out.append(OpportunityCheck(o, status, missing, amount, apply_on, decided, arr, semester,
                                    run_out is None or arrives < run_out, passed))
    return out


def approved_events(scenario, ds, ledger):
    """The "if approved" what-ifs: each approved opportunity's money on the day it would arrive (applying tomorrow)."""
    out = []
    for opp_id in scenario.approved:
        o = next((x for x in ds.opportunities if x.row_id == opp_id), None)
        money_ = (o.amount or o.max_amount) if o else None
        if not money_:
            continue
        _, arrives = opportunity_arrival(o, config.DEMO_TODAY + timedelta(days=1))
        out.append((arrives, D(money_), f"{o.name} (if approved)",
                    ledger.add(f"{o.name} if approved ({arrives})", D(money_), "USD",
                               f"What-if: {o.name} is approved; {fmt_money(money_)} arrives {fmt_date(arrives)}. Not "
                               "guaranteed money.", [o.row_id])))
    return out


# ---------------------------------------------------------------------------------------
# Source 8: the meal plan. Swipes and dining dollars, their pace, and what (if anything) checking has to pay.
# ---------------------------------------------------------------------------------------
@dataclass
class MealStatus:
    c: dict                      # name -> Computed (see meal_plan_status)
    runs_out: date | None        # dining dollars run out (None: they last)
    swipes_last: bool
    tip: dict                    # the "move 2 dining-dollar meals a week to swipes" effect: name -> Computed
    tip_works: bool


def _meal_projection(dd_left, dd_pace, sw_left, sw_pace, avg, days_left):
    """(runs_out day number or None, dining dollars left at the end, swipes left at the end, cost to checking)."""
    k = 1
    while k <= days_left and dd_left - dd_pace * k >= 0:
        k += 1
    runs_out = k if k <= days_left else None
    dd_end = dd_left - dd_pace * days_left
    sw_end = Decimal(sw_left) - sw_pace * days_left
    short_meals = (-dd_end) / avg if dd_end < 0 and avg else Decimal(0)
    cost = max(Decimal(0), short_meals - max(sw_end, Decimal(0))) * avg
    return runs_out, dd_end, sw_end, cost


def meal_plan_status(scenario=None, ds=None, ledger=None):
    """Dining dollars and swipes: used so far, left, pace per day and per week (Aug 24 to today), when the dining
    dollars run out, swipes left on Dec 18, and what checking pays: dining-dollar meals still to come after they run
    out, beyond the spare swipes, at the average meal price ($0 when the swipes cover it). What-ifs: move N
    dining-dollar meals a week to swipes (Scenario.meal_moves), add dining dollars (Scenario.dining_dollars_added).
    The tip: move 2 dining-dollar meals a week to swipes."""
    scenario, ds = scenario or Scenario(), _ds(ds)
    ledger = ledger if ledger is not None else Ledger()
    plan = ds.meal_plan
    if not plan:
        return None
    start, today, end = plan.start, config.DEMO_TODAY, min(plan.end, config.SEMESTER_END)
    n, days_left = (today - start).days + 1, (end - today).days
    meals = [m for m in ds.meals if start <= m.date <= today]
    dd_meals = [m for m in meals if m.tender == "DINING_DOLLARS"]
    ids = [m.row_id for m in meals]
    c = {}
    c["dd_total"] = ledger.add("dining dollars on the plan", D(plan.dining_dollars + scenario.dining_dollars_added),
                               "USD", f"{plan.name}: {fmt_money(plan.dining_dollars)}"
                               + (f" + {fmt_money(scenario.dining_dollars_added)} added (what-if)"
                                  if scenario.dining_dollars_added else "") + ".", [plan.row_id])
    used = sum((m.dining_dollars for m in dd_meals), ZERO)
    c["dd_used"] = ledger.add("dining dollars used so far", D(used), "USD",
                              f"{len(dd_meals)} dining-dollar purchases from {fmt_date(start)} to {fmt_date(today)}.",
                              [m.row_id for m in dd_meals])
    c["dd_left"] = ledger.add("dining dollars left", c["dd_total"].value - c["dd_used"].value, "USD",
                              "On the plan minus used so far.", [c["dd_total"], c["dd_used"]])
    sw_used = sum(m.swipes for m in meals)
    c["swipes_total"] = ledger.add("swipes on the plan", plan.swipes, "count", f"{plan.name}.", [plan.row_id])
    c["swipes_used"] = ledger.add("swipes used so far", sw_used, "count",
                                  f"Swipes from {fmt_date(start)} to {fmt_date(today)}.",
                                  [m.row_id for m in meals if m.swipes])
    c["swipes_left"] = ledger.add("swipes left", plan.swipes - sw_used, "count", "On the plan minus used so far.",
                                  [c["swipes_total"], c["swipes_used"]])
    avg = used / len(dd_meals) if dd_meals else ZERO
    c["avg_meal"] = ledger.add("average dining-dollar meal", D(avg), "USD",
                               f"{fmt_money(used)} / {len(dd_meals)} purchases.", [c["dd_used"]])
    moves = Decimal(scenario.meal_moves)
    dd_pace = max(used / n - moves * avg / 7, Decimal(0))              # moving meals can't make either pace negative
    sw_pace = max(Decimal(sw_used) / n + moves / 7, Decimal(0))
    c["dd_week"] = ledger.add("dining dollars per week", D(dd_pace * 7), "USD",
                              f"{fmt_money(used)} over {n} days x 7"
                              + (f", with {scenario.meal_moves} meal(s) a week moved to swipes" if moves else "") + ".",
                              [c["dd_used"]])
    c["swipes_week"] = ledger.add("swipes per week", (sw_pace * 7).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
                                  "count", f"{sw_used} swipes over {n} days x 7"
                                  + (f", plus {scenario.meal_moves} moved from dining dollars" if moves else "") + ".",
                                  [c["swipes_used"]])
    k, dd_end, sw_end, cost = _meal_projection(c["dd_left"].value, dd_pace, c["swipes_left"].value, sw_pace, avg,
                                               days_left)
    runs_out = today + timedelta(days=k) if k else None
    c["dd_runs_out"] = ledger.add("dining dollars run out", runs_out, "date",
                                  (f"{fmt_money(c['dd_left'].value)} left at {fmt_money(D(dd_pace))}/day: the first day "
                                   f"the balance would go below $0 is {fmt_date(runs_out)}.") if runs_out else
                                  f"They last through {fmt_date(end)}.", [c["dd_left"], c["dd_week"]])
    c["swipes_end"] = ledger.add(f"swipes left on {end}", (sw_end).quantize(CENT, rounding=ROUND_HALF_UP), "count",
                                 f"{c['swipes_left'].value} left - {D(sw_pace)}/day x {days_left} days.",
                                 [c["swipes_left"], c["swipes_week"]])
    c["cost"] = ledger.add("meals paid from checking this semester", D(cost), "USD",
                           "Dining-dollar meals still to come after they run out, beyond the spare swipes, at the "
                           f"average meal price {fmt_money(D(avg))}" + (" - the swipes cover them." if not cost else "."),
                           [c["dd_runs_out"], c["swipes_end"], c["avg_meal"]])
    tip_dd = max(used / n - (moves + 2) * avg / 7, Decimal(0))
    tip_sw = max(Decimal(sw_used) / n + (moves + 2) / 7, Decimal(0))
    tk, tip_dd_end, tip_sw_end, tip_cost = _meal_projection(c["dd_left"].value, tip_dd, c["swipes_left"].value, tip_sw,
                                                            avg, days_left)
    tip = {"dd_end": ledger.add("dining dollars left on Dec 18 with 2 meals a week on swipes", D(tip_dd_end), "USD",
                                f"{fmt_money(c['dd_left'].value)} - {fmt_money(D(tip_dd))}/day x {days_left} days.",
                                [c["dd_left"], c["avg_meal"]]),
           "sw_end": ledger.add("swipes left on Dec 18 with 2 meals a week on swipes",
                                tip_sw_end.quantize(CENT, rounding=ROUND_HALF_UP), "count",
                                f"{c['swipes_left'].value} - {D(tip_sw)}/day x {days_left} days.", [c["swipes_left"]]),
           "cost": ledger.add("meals paid from checking with 2 meals a week on swipes", D(tip_cost), "USD",
                              "Same rule with the new paces.", [c["avg_meal"]])}
    return MealStatus(c, runs_out, sw_end >= 0, tip, tip_dd_end >= 0 and tip_sw_end >= 0 and not tip_cost)
