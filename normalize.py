"""Normalize: typed records from every source, on top of data_access.

    import normalize
    ds = normalize.load()                 # Dataset, cached per backend
    ds.checking_txns[0].amount            # Decimal, money out NEGATIVE
    ds.row("CHK-0042")                    # any record by its row ID

Every source's date format is parsed to datetime.date, and every amount is signed from Maya's cash
point of view: money she pays is NEGATIVE, money she receives is POSITIVE (card purchases, bursar
charges, rent, installments and statement balances all become negative). Every record keeps its
source, table and row ID, and the Evidence of the named query that returned it (ds.evidence).

Merchants are normalized with one keyword table (MERCHANT_RULES), so "KROGER #0412" (checking)
and "Kroger 0412 Midtown" (card) are both "Kroger". Classification is rule-based, never the LLM:
  1. the merchant rule's fixed category, if it has one (income, rent, card_payment, fee, subscription);
  2. else an outflow with the same merchant and amount in 3+ different months -> recurring_bill;
  3. else an outflow of $100 or more -> one_off;
  4. else an outflow -> variable; an inflow -> income.
"""
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache

import config
import data_access as da

CATEGORIES = ("income", "rent", "recurring_bill", "subscription", "card_payment", "fee", "one_off", "variable")
ONE_OFF_THRESHOLD = Decimal("100.00")
RECURRING_MIN_MONTHS = 3

# ---------------------------------------------------------------------------------------
# Student-friendly spending categories (shared by Ask PocketMoney and the Budget tab). The ONE rules table.
#   (direction, match, key, category): direction "out" (money out) or "in"; match is "category" (the
#   classification above), "keyword" (substring of the raw description), "purpose" (MERCHANT_RULES), or
#   "card" (the card's own category column). The first matching rule wins. Card payments are "Transfer":
#   money moving between Maya's own accounts, never spending.
# ---------------------------------------------------------------------------------------
SPENDING_OUT = ("Rent", "Groceries", "Eating out", "Meal plan", "Subscriptions", "Transportation", "Shopping",
                "Entertainment", "School", "Bills & utilities", "Fees", "Other")
SPENDING_IN = ("Paycheck", "Financial aid", "Refund", "Gifts & deposits")
# Budgets: fixed costs she can't trim month to month vs flexible ones she can budget.
FIXED = ("Rent", "Subscriptions", "Bills & utilities", "Fees", "School")
FLEXIBLE = ("Groceries", "Eating out", "Meal plan", "Shopping", "Entertainment", "Transportation", "Other")
assert set(FIXED) | set(FLEXIBLE) == set(SPENDING_OUT) and not set(FIXED) & set(FLEXIBLE)
TRANSFER = "Transfer"
SPENDING_RULES = [
    ("out", "category", "card_payment", TRANSFER),
    ("in", "category", "card_payment", TRANSFER),
    ("out", "category", "rent", "Rent"),
    ("out", "category", "fee", "Fees"),
    ("out", "category", "subscription", "Subscriptions"),
    ("out", "keyword", "MEAL PLAN", "Meal plan"),
    ("out", "keyword", "DINING DOLLARS", "Meal plan"),
    ("out", "keyword", "TICKETMASTER", "Entertainment"),
    ("out", "keyword", "CINEMA", "Entertainment"),
    ("out", "keyword", "STEAM GAMES", "Entertainment"),
    ("out", "keyword", "NETFLIX", "Subscriptions"),
    ("out", "keyword", "LYFT", "Transportation"),
    ("out", "keyword", "TUITION", "School"),
    ("out", "purpose", "groceries", "Groceries"),
    ("out", "purpose", "eating out", "Eating out"),
    ("out", "purpose", "coffee", "Eating out"),
    ("out", "purpose", "music streaming", "Subscriptions"),
    ("out", "purpose", "transportation", "Transportation"),
    ("out", "purpose", "shopping", "Shopping"),
    ("out", "purpose", "pharmacy", "Shopping"),
    ("out", "purpose", "repairs", "Shopping"),
    ("out", "purpose", "books", "School"),
    ("out", "purpose", "tuition", "School"),
    ("out", "card", "Restaurants", "Eating out"),
    ("out", "card", "Groceries", "Groceries"),
    ("out", "card", "Merchandise", "Shopping"),
    ("out", "card", "Transportation", "Transportation"),
    ("out", "card", "Travel", "Transportation"),
    ("out", "card", "Digital Services", "Subscriptions"),
    ("out", "card", "Entertainment", "Entertainment"),
    ("out", "card", "Education", "School"),
    ("out", "card", "Utilities", "Bills & utilities"),
    ("out", "category", "recurring_bill", "Bills & utilities"),     # e.g. the monthly Venmo utility share
    ("in", "purpose", "wages", "Paycheck"),
    ("in", "keyword", "FIN AID", "Financial aid"),
    ("in", "keyword", "DISBURSEMENT", "Financial aid"),
    ("in", "keyword", "REFUND", "Refund"),
]


def spending_category(t):
    """Student-friendly category for a raw txn dict (or Txn): the first matching SPENDING_RULES row; else
    "Other" for money out and "Gifts & deposits" for money in."""
    get = t.get if isinstance(t, dict) else lambda k: getattr(t, k)
    direction = "out" if get("amount") < 0 else "in"
    text = _squash(get("description"))
    for d, match, key, category in SPENDING_RULES:
        if d != direction:
            continue
        if ((match == "category" and get("category") == key) or (match == "purpose" and get("purpose") == key)
                or (match == "keyword" and _squash(key) in text) or (match == "card" and get("card_category") == key)):
            return category
    return "Other" if direction == "out" else "Gifts & deposits"

# ---------------------------------------------------------------------------------------
# Merchant rules: the ONE place merchant keywords live.
#   (keyword, canonical merchant, fixed category or None, purpose or None, projected_from or None)
# keyword: case-insensitive substring of the raw description (spaces/punctuation collapsed).
# purpose: what the merchant is for; two subscriptions with the same purpose are duplicates.
# projected_from: the table the engine projects this item from (so it is not also projected
#   from its transaction history).
# The first matching rule wins.
# ---------------------------------------------------------------------------------------
MERCHANT_RULES = [
    ("GREENWAY PROPERTY", "Greenway Property Mgmt (rent)", "rent", "housing", "lease/rent_schedule"),
    ("PAYROLL DIR DEP", "State Univ payroll", "income", "wages", "shifts/pay_periods"),
    ("MOBILE DEPOSIT", "Mobile check deposit", "income", None, None),
    ("CARD PYMT AUTOPAY", "Horizon card autopay", "card_payment", None, "card/statements"),
    ("PAYMENT THANK YOU", "Horizon card autopay", "card_payment", None, "card/statements"),
    ("COURTESY PAY FEE", "Overdraft fee (Courtesy Pay)", "fee", None, None),
    ("PAYPLAN", "StateU payment plan", None, "tuition", "bursar/payment_plan"),
    ("VENMO PAYMENT", "Venmo", None, None, None),
    ("SPOTIFY", "Spotify", "subscription", "music streaming", None),
    ("APPLE COM BILL", "Apple Music", "subscription", "music streaming", None),   # the $10.99/month Apple bill
    ("KROGER", "Kroger", None, "groceries", None),
    ("BEAN THERE CAFE", "Bean There Cafe", None, "coffee", None),
    ("CHIPOTLE", "Chipotle", None, "eating out", None),
    ("JIMMY JOHNS", "Jimmy John's", None, "eating out", None),
    ("POTBELLY", "Potbelly", None, "eating out", None),
    ("DOORDASH", "DoorDash", None, "eating out", None),
    ("WALGREENS", "Walgreens", None, "pharmacy", None),
    ("UBER", "Uber", None, "transportation", None),
    ("TARGET", "Target", None, "shopping", None),
    ("AMAZON", "Amazon", None, "shopping", None),
    ("BURLINGTON", "Burlington", None, "shopping", None),
    ("UBREAKIFIX", "uBreakiFix", None, "repairs", None),
    ("BOOKSTORE", "StateU Bookstore", None, "books", None),
]


def _squash(s):
    return re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()


def merchant_rule(description):
    """(canonical merchant, fixed category, purpose, projected_from) for a raw description."""
    text = _squash(description)
    for keyword, name, category, purpose, projected_from in MERCHANT_RULES:
        if _squash(keyword) in text:
            return name, category, purpose, projected_from
    return description.strip(), None, None, None


# ---------------------------------------------------------------------------------------
# Parsing: each source's date format, and money
# ---------------------------------------------------------------------------------------
def parse_date(s, fmt):
    """fmt: iso (checking), mdy (card MM/DD/YYYY), ymd8 (aid YYYYMMDD), banner (bursar DD-MON-YYYY),
    slash (lease YYYY/MM/DD), short (shifts M/D/YY). Empty -> None."""
    s = (s or "").strip()
    if not s:
        return None
    pattern = {"iso": "%Y-%m-%d", "mdy": "%m/%d/%Y", "ymd8": "%Y%m%d", "banner": "%d-%b-%Y",
               "slash": "%Y/%m/%d", "short": "%m/%d/%y"}[fmt]
    return datetime.strptime(s.title() if fmt == "banner" else s, pattern).date()


def money(s):
    """Decimal from a stored amount string ("" -> None)."""
    s = (s or "").strip()
    return Decimal(s) if s else None


# ---------------------------------------------------------------------------------------
# Typed records. Amounts: money out NEGATIVE, money in POSITIVE (Maya's cash point of view).
# ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Record:
    source: str
    table: str
    row_id: str


@dataclass(frozen=True)
class Txn(Record):
    account: str                 # "checking" or "card"
    date: date                   # posted date (checking) / transaction date (card)
    description: str             # raw, as stored
    merchant: str                # canonical (MERCHANT_RULES)
    category: str                # one of CATEGORIES
    purpose: str | None
    projected_from: str | None
    amount: Decimal
    running_balance: Decimal | None = None   # checking only
    post_date: date | None = None            # card only
    card_category: str | None = None         # card only: the issuer's own category column
    spending_category: str | None = None     # student-friendly (SPENDING_RULES); "Transfer" = not spending


@dataclass(frozen=True)
class CheckingAccount(Record):
    current_balance: Decimal
    as_of: date
    opening_balance: Decimal
    overdraft_fee: Decimal       # negative
    overdraft_rule: str


@dataclass(frozen=True)
class Statement(Record):
    cycle_start: date
    closing: date
    due: date
    amount: Decimal              # statement balance, negative (paid from checking)
    status: str                  # PAID / AUTOPAY SCHEDULED


@dataclass(frozen=True)
class Disbursement(Record):
    award_line: str
    scheduled: date
    gross: Decimal
    fee: Decimal                 # origination fee, negative
    net: Decimal
    status: str                  # DISBURSED / HELD / SCHEDULED
    hold_reason: str


@dataclass(frozen=True)
class Requirement(Record):
    code: str
    description: str
    requested: date | None
    received: date | None
    status: str
    effect: str


@dataclass(frozen=True)
class LedgerEntry(Record):
    term: str
    date: date
    code: str
    description: str
    amount: Decimal              # charge negative, aid/payment positive
    memo: bool                   # memo/anticipated entry, not posted money


@dataclass(frozen=True)
class Hold(Record):
    code: str
    description: str
    from_date: date | None
    to_date: date | None
    originator: str
    blocks: str
    status: str


@dataclass(frozen=True)
class Refund(Record):
    term: str
    amount: Decimal              # positive: money to Maya
    basis: str
    status: str
    reason: str
    release_rule: str
    release_business_days: int | None
    method: str


@dataclass(frozen=True)
class Installment(Record):
    term: str
    number: str
    due: date
    amount: Decimal              # negative
    status: str                  # PAID / DUE
    paid_on: date | None
    method: str


@dataclass(frozen=True)
class RentDue(Record):
    period: str
    due: date
    amount: Decimal              # negative
    status: str                  # PAID / UPCOMING
    paid_on: date | None


@dataclass(frozen=True)
class LeaseTerms(Record):
    start: date
    end: date
    monthly_rent: Decimal        # negative
    rent_due_day: int
    grace_days: int
    late_fee: Decimal            # negative
    deposit: Decimal             # negative
    utilities_included: str


@dataclass(frozen=True)
class Job(Record):
    employer: str
    hourly_rate: Decimal
    pay_frequency: str
    pay_rule: str
    withholding_pct: Decimal


@dataclass(frozen=True)
class PayPeriod(Record):
    start: date
    end: date
    pay_date: date
    hours: Decimal | None        # paid periods only
    gross: Decimal | None
    withholding: Decimal | None  # negative
    net: Decimal | None
    status: str                  # PAID / UPCOMING


@dataclass(frozen=True)
class Shift(Record):
    date: date
    start_time: str
    end_time: str
    hours: Decimal
    status: str                  # WORKED / CALLED_OFF / SCHEDULED
    note: str

    @property
    def is_extra(self):
        return self.note.lower().startswith("extra shift")


@dataclass(frozen=True)
class Opportunity(Record):
    name: str
    type: str                    # emergency_grant / scholarship / work_study
    amount: Decimal | None       # a fixed award
    max_amount: Decimal | None   # "up to"
    hourly_rate: Decimal | None  # work-study
    hours_per_week: Decimal | None
    deadline: date | None        # None: rolling
    decision_business_days: int
    payout_rule: str             # after_decision / after_deadline / fixed_date / payroll
    payout_business_days: int
    payout_date: date | None
    payout_method: str
    class_years: tuple           # () = any
    enrollment: str              # "full-time" or "half-time or more"
    min_gpa: Decimal | None
    need_based: bool
    pell_required: bool
    fafsa_required: bool
    majors: tuple                # () = any
    residency: str               # "any" or "in-state"
    description: str


@dataclass(frozen=True)
class OppRequirement(Record):
    opp_id: str
    item: str
    details: str


@dataclass(frozen=True)
class StudentProfile(Record):
    class_year: str
    enrollment: str
    credits: int
    gpa: Decimal
    pell_eligible: bool
    fafsa_on_file: bool
    major: str
    residency: str
    as_of: date


@dataclass(frozen=True)
class MealPlan(Record):
    name: str
    swipes: int
    dining_dollars: Decimal
    start: date
    end: date
    rollover: bool


@dataclass(frozen=True)
class Meal(Record):
    date: date
    time: str
    place: str
    tender: str                  # SWIPE / DINING_DOLLARS
    dining_dollars: Decimal      # 0 for a swipe
    swipes: int


@dataclass
class Dataset:
    backend: str
    checking_account: CheckingAccount
    checking_txns: list
    card_txns: list
    statements: list
    disbursements: list
    requirements: list
    ledger: list
    holds: list                  # active holds
    refunds: list
    installments: list
    rent_schedule: list
    lease: LeaseTerms
    job: Job
    pay_periods: list
    shifts: list
    evidence: list = field(default_factory=list)   # data_access Evidence, one per query run
    _by_id: dict = field(default_factory=dict, repr=False)
    opportunities: list = field(default_factory=list)          # source 7
    opp_requirements: list = field(default_factory=list)
    profile: StudentProfile | None = None
    meal_plan: MealPlan | None = None                          # source 8
    meals: list = field(default_factory=list)

    def row(self, row_id):
        return self._by_id[row_id]

    def txns(self, account=None):
        if account == "checking":
            return self.checking_txns
        if account == "card":
            return self.card_txns
        return self.checking_txns + self.card_txns


# ---------------------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------------------
def history_range():
    """Transaction query window: from the start of the month before the semester to the end of its year."""
    first = config.SEMESTER_START.replace(day=1) - timedelta(days=1)
    return {"start_date": first.replace(day=1).isoformat(), "end_date": f"{config.SEMESTER_END.year}-12-31"}


def _txn(source, table, row_id, account, day, description, amount, **extra):
    name, category, purpose, projected_from = merchant_rule(description)
    return dict(source=source, table=table, row_id=row_id, account=account, date=day, description=description,
                merchant=name, category=category, purpose=purpose, projected_from=projected_from, amount=amount,
                **extra)


def classify(raw):
    """Fill in category for raw txn dicts that have no fixed category (rules 2-4 in the module doc)."""
    months = {}
    for t in raw:
        if t["amount"] < 0:
            months.setdefault((t["account"], t["merchant"], t["amount"]), set()).add((t["date"].year, t["date"].month))
    for t in raw:
        if t["category"]:
            continue
        if t["amount"] >= 0:
            t["category"] = "income"
        elif len(months[(t["account"], t["merchant"], t["amount"])]) >= RECURRING_MIN_MONTHS:
            t["category"] = "recurring_bill"
        elif -t["amount"] >= ONE_OFF_THRESHOLD:
            t["category"] = "one_off"
        else:
            t["category"] = "variable"
    for t in raw:
        t["spending_category"] = spending_category(t)
    return [Txn(**t) for t in raw]


def _business_days(rule_text):
    m = re.search(r"(\d+)\s+business days", rule_text)
    return int(m.group(1)) if m else None


def build(results, backend):
    """Dataset from {query name: QueryResult}. Separate from load() so tests can feed rows directly."""
    rows = {name: r.rows for name, r in results.items()}

    acct = rows["checking_account"][0]
    checking_account = CheckingAccount(
        "checking", "account", acct["account_id"], money(acct["current_balance"]), parse_date(acct["as_of"], "iso"),
        money(acct["opening_balance_2026_08_01"]), -money(acct["overdraft_fee"]), acct["overdraft_fee_rule"])

    chk = classify([_txn("checking", "transactions", r["txn_id"], "checking", parse_date(r["posted_date"], "iso"),
                         r["description"], money(r["amount"]), running_balance=money(r["running_balance"]))
                    for r in rows["checking_transactions"]])
    # card export: purchases positive, payments negative -> flip
    card = classify([_txn("card", "transactions", r["trans_id"], "card", parse_date(r["trans_date"], "mdy"),
                          r["merchant"], -money(r["amount"]), post_date=parse_date(r["post_date"], "mdy"),
                          card_category=r.get("category") or None)
                     for r in rows["card_transactions"]])

    statements = [Statement("card", "statements", r["statement_id"], parse_date(r["cycle_start"], "mdy"),
                            parse_date(r["closing_date"], "mdy"), parse_date(r["payment_due_date"], "mdy"),
                            -money(r["new_balance"]), r["status"]) for r in rows["card_statements"]]
    disbursements = [Disbursement("aid", "disbursements", r["disb_id"], r["awd_line_id"],
                                  parse_date(r["sched_disb_date"], "ymd8"), money(r["gross_amt"]),
                                  -money(r["orig_fee_amt"]), money(r["net_amt"]), r["disb_status"], r["hold_reason"])
                     for r in rows["aid_disbursements"]]
    requirements = [Requirement("aid", "requirements", r["req_id"], r["req_code"], r["req_desc"],
                                parse_date(r["requested_dt"], "ymd8"), parse_date(r["received_dt"], "ymd8"),
                                r["req_status"], r["effect"]) for r in rows["aid_requirements"]]
    ledger = [LedgerEntry("bursar", "ledger", r["LEDGER_ID"], r["TERM_CODE"], parse_date(r["ENTRY_DATE"], "banner"),
                          r["DETAIL_CODE"], r["DESCRIPTION"], -money(r["AMOUNT"]), r["MEMO_FLAG"] == "Y")
              for r in rows["bursar_ledger"]]
    holds = [Hold("bursar", "holds", r["HOLD_ID"], r["HOLD_CODE"], r["HOLD_DESC"], parse_date(r["FROM_DATE"], "banner"),
                  parse_date(r["TO_DATE"], "banner"), r["ORIGINATOR"], r["BLOCKS"], r["STATUS"])
             for r in rows["bursar_active_holds"]]
    refunds = [Refund("bursar", "refunds", r["REFUND_ID"], r["TERM_CODE"], money(r["REFUND_AMOUNT"]), r["BASIS"],
                      r["STATUS"], r["STATUS_REASON"], r["RELEASE_RULE"], _business_days(r["RELEASE_RULE"]), r["METHOD"])
               for r in rows["bursar_refunds"]]
    installments = [Installment("bursar", "payment_plan", r["INSTALLMENT_ID"], r["TERM_CODE"], r["INSTALLMENT"],
                                parse_date(r["DUE_DATE"], "banner"), -money(r["AMOUNT"]), r["STATUS"],
                                parse_date(r["PAID_DATE"], "banner"), r["METHOD"]) for r in rows["bursar_payment_plan"]]
    rent_schedule = [RentDue("lease", "rent_schedule", r["schedule_id"], r["period"], parse_date(r["due_date"], "slash"),
                             -money(r["amount_due"]), r["status"], parse_date(r["paid_on"], "slash"))
                     for r in rows["rent_schedule"]]
    lt = rows["lease_terms"][0]
    lease = LeaseTerms("lease", "lease_terms", lt["term_id"], parse_date(lt["start_date"], "slash"),
                       parse_date(lt["end_date"], "slash"), -money(lt["monthly_rent"]), int(lt["rent_due_day"]),
                       int(lt["grace_period_days"]), -money(lt["late_fee"]), -money(lt["security_deposit"]),
                       lt["utilities_included"])
    jr = rows["job_info"][0]
    job = Job("shifts", "job", jr["job_id"], jr["employer"], money(jr["hourly_rate"]), jr["pay_frequency"],
              jr["pay_rule"], Decimal(jr["withholding_pct"]))
    pay_periods = [PayPeriod("shifts", "pay_periods", r["pay_period_id"], parse_date(r["period_start"], "short"),
                             parse_date(r["period_end"], "short"), parse_date(r["pay_date"], "short"), money(r["hours"]),
                             money(r["gross_pay"]), -money(r["withholding"]) if r["withholding"] else None,
                             money(r["net_pay"]), r["status"]) for r in rows["pay_periods"]]
    shifts = [Shift("shifts", "shifts", r["shift_id"], parse_date(r["shift_date"], "short"), r["start_time"],
                    r["end_time"], money(r["hours"]), r["status"], r["note"]) for r in rows["shifts"]]

    ds = Dataset(backend, checking_account, chk, card, statements, disbursements, requirements, ledger, holds, refunds,
                 installments, rent_schedule, lease, job, pay_periods, shifts,
                 evidence=[r.evidence for r in results.values()])
    _build_new_sources(ds, rows)
    for rec in [checking_account, lease, job, *chk, *card, *statements, *disbursements, *requirements, *ledger, *holds,
                *refunds, *installments, *rent_schedule, *pay_periods, *shifts, *ds.opportunities,
                *ds.opp_requirements, *([ds.profile] if ds.profile else []), *([ds.meal_plan] if ds.meal_plan else []),
                *ds.meals]:
        ds._by_id[rec.row_id] = rec
    return ds


def _opt_money(s):
    return money(s) if s else None


def _list(s):
    return () if not s or s.lower() == "any" else tuple(x.strip() for x in s.split(";"))


def _build_new_sources(ds, rows):
    """Sources 7 (aid opportunities, her profile) and 8 (meal plan). Absent tables leave the fields empty."""
    ds.opportunities = [Opportunity(
        "opportunities", "opportunities", r["opp_id"], r["name"], r["type"], _opt_money(r["amount"]),
        _opt_money(r["max_amount"]), _opt_money(r["hourly_rate"]), _opt_money(r["hours_per_week"]),
        parse_date(r["deadline"], "mdy"), int(r["decision_business_days"] or 0), r["payout_rule"],
        int(r["payout_business_days"] or 0), parse_date(r["payout_date"], "mdy"), r["payout_method"],
        _list(r["class_years"]), r["enrollment"], _opt_money(r["min_gpa"]), r["need_based"] == "Y",
        r["pell_required"] == "Y", r["fafsa_required"] == "Y", _list(r["majors"]), r["residency"], r["description"])
        for r in rows.get("aid_opportunities", [])]
    ds.opp_requirements = [OppRequirement("opportunities", "application_requirements", r["areq_id"], r["opp_id"],
                                          r["item"], r["details"]) for r in rows.get("opportunity_requirements", [])]
    prof = rows.get("student_profile") or []
    if prof:
        r = prof[0]
        ds.profile = StudentProfile("opportunities", "student_profile", r["profile_id"], r["class_year"],
                                    r["enrollment"], int(r["credits"]), Decimal(r["gpa"]), r["pell_eligible"] == "Y",
                                    r["fafsa_on_file"] == "Y", r["major"], r["residency"], parse_date(r["as_of"], "mdy"))
    plan = rows.get("meal_plan") or []
    if plan:
        r = plan[0]
        ds.meal_plan = MealPlan("meal_plan", "plan", r["plan_id"], r["plan_name"], int(r["swipes"]),
                                money(r["dining_dollars"]), parse_date(r["start_date"], "iso"),
                                parse_date(r["end_date"], "iso"), r["rollover"] == "Y")
    ds.meals = [Meal("meal_plan", "transactions", r["meal_id"], parse_date(r["timestamp"][:10], "iso"),
                     r["timestamp"][11:], r["location"], r["tender"], money(r["dining_dollars"] or "0"),
                     int(r["swipes"] or 0)) for r in rows.get("meal_transactions", [])]


def queries():
    """(name, params) for every named query the engine needs. Also the list to warm the Zetaris cache with."""
    history = history_range()
    semester = {"start_date": config.SEMESTER_START.isoformat(), "end_date": config.SEMESTER_END.isoformat()}
    return [("checking_account", {}), ("checking_transactions", history), ("card_transactions", history),
            ("card_statements", {}), ("aid_disbursements", {}), ("aid_requirements", {}),
            ("bursar_ledger", {"term": "FA26"}), ("bursar_active_holds", {}), ("bursar_refunds", {}),
            ("bursar_payment_plan", {}), ("lease_terms", {}), ("rent_schedule", {}), ("job_info", {}),
            ("pay_periods", {}), ("shifts", semester),
            ("aid_opportunities", {}), ("opportunity_requirements", {}), ("student_profile", {}), ("meal_plan", {}),
            ("meal_transactions", {"start_date": config.SEMESTER_START.isoformat(),
                                   "end_date": config.DEMO_TODAY.isoformat()})]


@lru_cache(maxsize=4)
def load(backend=None):
    """Run every query in queries() and build the Dataset. Cached per backend for the process."""
    backend = (backend or config.DATA_BACKEND).lower()
    return build({name: da.run(name, backend=backend, **params) for name, params in queries()}, backend)


# ---------------------------------------------------------------------------------------
# My data mode: a Dataset from the student's own bank file only (no card, aid, bursar, lease, job, meal plan).
# Maya's merchant rules apply first; these generic keywords (ONLY for uploaded data, so Maya's numbers can't
# change) name common merchants. Classification stays rule-based (rule 12).
#   (keyword, fixed category or None, spending category)
# ---------------------------------------------------------------------------------------
MYDATA_RULES = [
    ("PAYROLL", "income", "Paycheck"), ("DIRECT DEP", "income", "Paycheck"), ("SALARY", "income", "Paycheck"),
    ("CREDIT CARD PAYMENT", "card_payment", TRANSFER), ("CARD PAYMENT", "card_payment", TRANSFER),
    ("TRANSFER TO", "card_payment", TRANSFER), ("TRANSFER FROM", "card_payment", TRANSFER),
    ("OVERDRAFT", "fee", "Fees"), ("NSF", "fee", "Fees"), ("SERVICE FEE", "fee", "Fees"), ("ATM FEE", "fee", "Fees"),
    ("NETFLIX", "subscription", "Subscriptions"), ("HULU", "subscription", "Subscriptions"),
    ("DISNEY PLUS", "subscription", "Subscriptions"), ("YOUTUBE PREMIUM", "subscription", "Subscriptions"),
    ("PRIME VIDEO", "subscription", "Subscriptions"),
    ("RENT", None, "Rent"), ("APTS", None, "Rent"), ("APARTMENTS", None, "Rent"), ("PROPERTY", None, "Rent"),
    ("WIRELESS", None, "Bills & utilities"), ("ELECTRIC", None, "Bills & utilities"),
    ("INTERNET", None, "Bills & utilities"), ("UTILIT", None, "Bills & utilities"), ("COMCAST", None, "Bills & utilities"),
    ("XFINITY", None, "Bills & utilities"), ("VERIZON", None, "Bills & utilities"), ("T MOBILE", None, "Bills & utilities"),
    ("GROCER", None, "Groceries"), ("MARKET", None, "Groceries"), ("ALDI", None, "Groceries"),
    ("SAFEWAY", None, "Groceries"), ("PUBLIX", None, "Groceries"), ("WHOLE FOODS", None, "Groceries"),
    ("TRADER JOE", None, "Groceries"), ("WALMART", None, "Groceries"),
    ("PIZZA", None, "Eating out"), ("COFFEE", None, "Eating out"), ("CAFE", None, "Eating out"),
    ("TACO", None, "Eating out"), ("BURGER", None, "Eating out"), ("STARBUCKS", None, "Eating out"),
    ("MCDONALD", None, "Eating out"), ("SUBWAY", None, "Eating out"), ("GRUBHUB", None, "Eating out"),
    ("TRANSIT", None, "Transportation"), ("SHELL", None, "Transportation"), ("EXXON", None, "Transportation"),
    ("CHEVRON", None, "Transportation"), ("PARKING", None, "Transportation"), ("LYFT", None, "Transportation"),
    ("BEST BUY", None, "Shopping"), ("WALGREENS", None, "Shopping"), ("CVS", None, "Shopping"),
    ("KROGER", None, "Groceries"), ("CHIPOTLE", None, "Eating out"), ("DOORDASH", None, "Eating out"),
    ("UBER EATS", None, "Eating out"), ("UBER", None, "Transportation"), ("TARGET", None, "Shopping"),
    ("AMAZON", None, "Shopping"), ("SPOTIFY", "subscription", "Subscriptions"), ("APPLE COM BILL", "subscription",
                                                                                 "Subscriptions"),
]


def mydata_merchant(description):
    """(merchant, fixed category, spending category or None) for an uploaded description, from the generic keywords
    only (Maya's merchant rules name her own merchants); the merchant drops store numbers and web suffixes
    ("FRESH MARKET #63" -> "Fresh Market", "NETFLIX.COM" -> "Netflix")."""
    text = _squash(re.sub(r"\.(com|net|org)\b", "", description, flags=re.I))
    spend = next(((cat, sc) for kw, cat, sc in MYDATA_RULES if _squash(kw) in text), None)
    words = [w for w in text.split() if not any(ch.isdigit() for ch in w)][:4]
    return " ".join(words).title() or description.strip(), spend[0] if spend else None, spend[1] if spend else None


def build_mydata(rows, meta, backend="local"):
    """Dataset from the uploaded transactions (rows of user_data/mydata/transactions.csv) and its meta: today's
    balance is the latest running balance, or the one she typed."""
    raw, spending = [], {}
    for r in rows:
        name, category, spend = mydata_merchant(r["description"])
        raw.append(dict(source="mydata", table="transactions", row_id=r["txn_id"], account="checking",
                        date=parse_date(r["posted_date"], "iso"), description=r["description"], merchant=name,
                        category=category, purpose=None, projected_from=None, amount=money(r["amount"]),
                        running_balance=money(r["running_balance"])))
        spending[r["txn_id"]] = spend
    txns = []
    for t in classify(raw):
        sc = spending.get(t.row_id)
        if sc and t.spending_category != TRANSFER and (t.amount < 0) == (sc not in SPENDING_IN):
            t = replace(t, spending_category=sc)
        txns.append(t)
    with_bal = [t for t in txns if t.running_balance is not None]
    balance = with_bal[-1].running_balance if with_bal else money(meta.get("balance_today") or "") or Decimal(0)
    last = max(t.date for t in txns)
    first = min(t.date for t in txns)
    opening = (with_bal[0].running_balance - with_bal[0].amount) if with_bal else balance - sum(t.amount for t in txns)
    acct = CheckingAccount("mydata", "account", "MY-ACCT", balance, last, opening, Decimal(0),
                           "From your bank file" if with_bal else "Balance you typed in")
    ds = Dataset(f"mydata-{backend}", acct, txns, [], [], [], [], [], [], [], [], [], None, None, [], [])
    ds._by_id[acct.row_id] = acct
    for t in txns:
        ds._by_id[t.row_id] = t
    ds.first_day = first
    return ds
