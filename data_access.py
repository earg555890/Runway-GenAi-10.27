"""Data-access layer: named queries over Maya's eight sources, on Zetaris or local CSVs.

The PLAN step picks a query by NAME with parameters; it never writes SQL.

    import data_access as da
    da.catalog()                                   # names, descriptions, params (for the PLAN prompt)
    r = da.run("checking_transactions", start_date="2026-10-01", end_date="2026-10-02")
    r.rows                                         # list of dicts, values exactly as stored (raw strings)
    r.evidence                                     # query, sources, tables, sql, params, row_ids, backend, duration

Backend: config.DATA_BACKEND ("zetaris" or "local"), or backend= per call. Zetaris results are cached
on disk (config.ZETARIS_CACHE) keyed by query name + parameters, so the demo never waits twice;
a cached answer reports backend "zetaris-cached". Sources stay separate (rule 4): each source is its
own Lightning database and its own folder of CSVs. Rows are returned as stored; normalizing dates
and signs is a separate step.
"""
import csv
import hashlib
import json
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

import config

SOURCE_DATABASES = {
    "checking": "RUNWAY_CHECKING",
    "card": "RUNWAY_CARD",
    "aid": "RUNWAY_AID",
    "bursar": "RUNWAY_BURSAR",
    "lease": "RUNWAY_LEASE",
    "shifts": "RUNWAY_SHIFTS",
    "opportunities": "RUNWAY_OPPORTUNITIES",    # source 7: the university's aid opportunities (+ her profile)
    "meal_plan": "RUNWAY_MEALPLAN",             # source 8: the campus meal plan
}


# ---------------------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------------------
@dataclass
class Param:
    name: str
    type: str                      # "date" (YYYY-MM-DD) or "choice"
    description: str
    choices: tuple = ()


@dataclass
class NamedQuery:
    name: str
    description: str               # one line; the PLAN model reads this
    tables: list                   # [(source, table)]
    sql: str                       # Lightning SQL template; {param} placeholders
    local: object                  # function(params) -> list of row dicts
    local_desc: str                # what the local implementation does, for the evidence record
    id_column: str                 # column holding the row ID
    params: list = field(default_factory=list)


@dataclass
class Evidence:
    query: str
    sources: list
    tables: list
    sql: str
    params: dict
    row_ids: list
    backend: str                   # "zetaris", "zetaris-cached" or "local"
    duration_s: float
    original_duration_s: float | None = None   # for zetaris-cached: how long the real query took

    def to_dict(self):
        return asdict(self)


@dataclass
class QueryResult:
    columns: list
    rows: list                     # list of dicts, raw values
    evidence: Evidence


class QueryError(ValueError):
    pass


# ---------------------------------------------------------------------------------------
# Local CSV helpers (no pandas needed; files are small)
# ---------------------------------------------------------------------------------------
_csv_cache = {}


def _load(source, table):
    path = config.DATA_DIR / source / f"{table}.csv"
    key = (str(path), path.stat().st_mtime)
    if key not in _csv_cache:
        with open(path, newline="", encoding="utf-8") as f:
            _csv_cache[key] = list(csv.DictReader(f))
    return [dict(r) for r in _csv_cache[key]]


def _iso(s):
    return date.fromisoformat(s)


def _mdy(s):            # card: MM/DD/YYYY
    return datetime.strptime(s, "%m/%d/%Y").date()


def _mdyy(s):           # shifts: M/D/YY
    return datetime.strptime(s, "%m/%d/%y").date()


def _between(rows, col, parse, p):
    lo, hi = _iso(p["start_date"]), _iso(p["end_date"])
    return [r for r in rows if lo <= parse(r[col]) <= hi]


def _sorted(rows, id_col):
    return sorted(rows, key=lambda r: r[id_col])


def _all(source, table, id_col):
    return lambda p: _sorted(_load(source, table), id_col)


def _recurring_local(p):
    """Same merchant + same amount in 3+ different months, per account, tagged with the source."""
    out = []
    chk = _load("checking", "transactions")
    groups = {}
    for r in chk:
        if float(r["amount"]) < 0:
            groups.setdefault((r["description"], r["amount"]), set()).add(r["posted_date"][:7])
    keys = {k for k, months in groups.items() if len(months) >= 3}
    out += [{"source": "checking", "row_id": r["txn_id"], "txn_date": r["posted_date"], "merchant": r["description"],
             "amount": r["amount"]} for r in chk if (r["description"], r["amount"]) in keys]
    card = _load("card", "transactions")
    groups = {}
    for r in card:
        if float(r["amount"]) > 0:
            groups.setdefault((r["merchant"], r["amount"]), set()).add(r["trans_date"][6:10] + r["trans_date"][:2])
    keys = {k for k, months in groups.items() if len(months) >= 3}
    out += [{"source": "card", "row_id": r["trans_id"], "txn_date": r["trans_date"], "merchant": r["merchant"],
             "amount": r["amount"]} for r in card if (r["merchant"], r["amount"]) in keys]
    return sorted(out, key=lambda r: (r["source"], r["row_id"]))


DATE_RANGE = [Param("start_date", "date", "first day, YYYY-MM-DD"), Param("end_date", "date", "last day, YYYY-MM-DD")]
CHK, CRD, AID, BUR, LSE, SHF = (SOURCE_DATABASES[s] for s in ("checking", "card", "aid", "bursar", "lease", "shifts"))
OPP, MEAL = SOURCE_DATABASES["opportunities"], SOURCE_DATABASES["meal_plan"]


def _day_of(stamp):     # meal plan: "YYYY-MM-DD HH:MM"
    return _iso(stamp[:10])

# ---------------------------------------------------------------------------------------
# The registry: the smallest set that retrieves every proof row in answer_key.json
# ---------------------------------------------------------------------------------------
QUERIES = [
    NamedQuery(
        "checking_account", "Checking account details: bank, current balance as of today, overdraft fee and rule.",
        [("checking", "account")], f"SELECT * FROM {CHK}.account ORDER BY account_id",
        _all("checking", "account", "account_id"), "all rows of checking/account.csv", "account_id"),
    NamedQuery(
        "checking_transactions", "Checking transactions posted between two dates, with the running balance after each.",
        [("checking", "transactions")],
        f"SELECT * FROM {CHK}.transactions WHERE to_date(posted_date, 'yyyy-MM-dd') "
        "BETWEEN DATE '{start_date}' AND DATE '{end_date}' ORDER BY txn_id",
        lambda p: _sorted(_between(_load("checking", "transactions"), "posted_date", _iso, p), "txn_id"),
        "checking/transactions.csv where posted_date between {start_date} and {end_date}", "txn_id", DATE_RANGE),
    NamedQuery(
        "card_transactions", "Credit card purchases and payments made between two dates.",
        [("card", "transactions")],
        f"SELECT * FROM {CRD}.transactions WHERE to_date(trans_date, 'MM/dd/yyyy') "
        "BETWEEN DATE '{start_date}' AND DATE '{end_date}' ORDER BY trans_id",
        lambda p: _sorted(_between(_load("card", "transactions"), "trans_date", _mdy, p), "trans_id"),
        "card/transactions.csv where trans_date between {start_date} and {end_date}", "trans_id", DATE_RANGE),
    NamedQuery(
        "card_statements", "Credit card statements: closing date, due date, statement balance, autopay status.",
        [("card", "statements")], f"SELECT * FROM {CRD}.statements ORDER BY statement_id",
        _all("card", "statements", "statement_id"), "all rows of card/statements.csv", "statement_id"),
    NamedQuery(
        "federated_recurring_charges",
        "FEDERATED across checking AND credit card in one query: charges with the same merchant and amount in "
        "3+ different months (subscriptions, rent, bills), each row tagged with its source.",
        [("checking", "transactions"), ("card", "transactions")],
        "SELECT 'checking' AS source, c.txn_id AS row_id, c.posted_date AS txn_date, c.description AS merchant, "
        "c.amount AS amount "
        f"FROM {CHK}.transactions c JOIN (SELECT description, amount FROM {CHK}.transactions "
        "WHERE CAST(amount AS DECIMAL(12,2)) < 0 GROUP BY description, amount "
        "HAVING COUNT(DISTINCT substr(posted_date, 1, 7)) >= 3) rc "
        "ON c.description = rc.description AND c.amount = rc.amount "
        "UNION ALL "
        "SELECT 'card' AS source, t.trans_id AS row_id, t.trans_date AS txn_date, t.merchant AS merchant, "
        "t.amount AS amount "
        f"FROM {CRD}.transactions t JOIN (SELECT merchant, amount FROM {CRD}.transactions "
        "WHERE CAST(amount AS DECIMAL(12,2)) > 0 GROUP BY merchant, amount "
        "HAVING COUNT(DISTINCT concat(substr(trans_date, 7, 4), substr(trans_date, 1, 2))) >= 3) rt "
        "ON t.merchant = rt.merchant AND t.amount = rt.amount "
        "ORDER BY source, row_id",
        _recurring_local,
        "checking/transactions.csv (debits) and card/transactions.csv (purchases): same merchant and amount "
        "in 3+ distinct months, tagged by source", "row_id"),
    NamedQuery(
        "aid_disbursements", "Financial aid disbursement schedule: each award's scheduled date, net amount and status "
        "(disbursed, held, scheduled) with the hold reason.",
        [("aid", "disbursements")], f"SELECT * FROM {AID}.disbursements ORDER BY disb_id",
        _all("aid", "disbursements", "disb_id"), "all rows of aid/disbursements.csv", "disb_id"),
    NamedQuery(
        "aid_requirements", "Documents the financial aid office has requested, whether received, and what they block.",
        [("aid", "requirements")], f"SELECT * FROM {AID}.requirements ORDER BY req_id",
        _all("aid", "requirements", "req_id"), "all rows of aid/requirements.csv", "req_id"),
    NamedQuery(
        "bursar_ledger", "Student account ledger for one term: charges (positive) and payments/aid (negative), "
        "including anticipated aid.",
        [("bursar", "ledger")],
        f"SELECT * FROM {BUR}.ledger WHERE TERM_CODE = '{{term}}' ORDER BY LEDGER_ID",
        lambda p: _sorted([r for r in _load("bursar", "ledger") if r["TERM_CODE"] == p["term"]], "LEDGER_ID"),
        "bursar/ledger.csv where TERM_CODE = {term}", "LEDGER_ID",
        [Param("term", "choice", "term code: SU26 = Summer 2026, FA26 = Fall 2026", ("SU26", "FA26"))]),
    NamedQuery(
        "bursar_active_holds", "Active holds on the student account and what they block (aid, refunds, registration).",
        [("bursar", "holds")], f"SELECT * FROM {BUR}.holds WHERE STATUS = 'ACTIVE' ORDER BY HOLD_ID",
        lambda p: _sorted([r for r in _load("bursar", "holds") if r["STATUS"] == "ACTIVE"], "HOLD_ID"),
        "bursar/holds.csv where STATUS = ACTIVE", "HOLD_ID"),
    NamedQuery(
        "bursar_refunds", "Credit-balance refunds: amount, status (e.g. held), reason and release rule.",
        [("bursar", "refunds")], f"SELECT * FROM {BUR}.refunds ORDER BY REFUND_ID",
        _all("bursar", "refunds", "REFUND_ID"), "all rows of bursar/refunds.csv", "REFUND_ID"),
    NamedQuery(
        "bursar_payment_plan", "Payment-plan installments: due date, amount, paid or due.",
        [("bursar", "payment_plan")], f"SELECT * FROM {BUR}.payment_plan ORDER BY INSTALLMENT_ID",
        _all("bursar", "payment_plan", "INSTALLMENT_ID"), "all rows of bursar/payment_plan.csv", "INSTALLMENT_ID"),
    NamedQuery(
        "lease_terms", "Lease terms: monthly rent, due day, grace period, late fee, deposit, utilities.",
        [("lease", "lease_terms")], f"SELECT * FROM {LSE}.lease_terms ORDER BY term_id",
        _all("lease", "lease_terms", "term_id"), "all rows of lease/lease_terms.csv", "term_id"),
    NamedQuery(
        "rent_schedule", "Monthly rent schedule for the semester: due dates, amounts, paid or upcoming.",
        [("lease", "rent_schedule")], f"SELECT * FROM {LSE}.rent_schedule ORDER BY schedule_id",
        _all("lease", "rent_schedule", "schedule_id"), "all rows of lease/rent_schedule.csv", "schedule_id"),
    NamedQuery(
        "job_info", "Campus job: hourly rate, pay frequency and pay-date rule, tax withholding.",
        [("shifts", "job")], f"SELECT * FROM {SHF}.job ORDER BY job_id",
        _all("shifts", "job", "job_id"), "all rows of shifts/job.csv", "job_id"),
    NamedQuery(
        "pay_periods", "Pay periods and pay dates: hours, gross and net pay for paid periods; upcoming pay dates.",
        [("shifts", "pay_periods")], f"SELECT * FROM {SHF}.pay_periods ORDER BY pay_period_id",
        _all("shifts", "pay_periods", "pay_period_id"), "all rows of shifts/pay_periods.csv", "pay_period_id"),
    NamedQuery(
        "shifts", "Work shifts between two dates: worked, called off, or scheduled, with hours and notes.",
        [("shifts", "shifts")],
        f"SELECT * FROM {SHF}.shifts WHERE to_date(shift_date, 'M/d/yy') "
        "BETWEEN DATE '{start_date}' AND DATE '{end_date}' ORDER BY shift_id",
        lambda p: _sorted(_between(_load("shifts", "shifts"), "shift_date", _mdyy, p), "shift_id"),
        "shifts/shifts.csv where shift_date between {start_date} and {end_date}", "shift_id", DATE_RANGE),
    NamedQuery(
        "aid_opportunities", "The university's grants, scholarships and work-study: amounts, deadlines, decision "
        "time, when and how money is paid, and who is eligible.",
        [("opportunities", "opportunities")], f"SELECT * FROM {OPP}.opportunities ORDER BY opp_id",
        _all("opportunities", "opportunities", "opp_id"), "all rows of opportunities/opportunities.csv", "opp_id"),
    NamedQuery(
        "opportunity_requirements", "What each aid opportunity's application needs.",
        [("opportunities", "application_requirements")],
        f"SELECT * FROM {OPP}.application_requirements ORDER BY areq_id",
        _all("opportunities", "application_requirements", "areq_id"),
        "all rows of opportunities/application_requirements.csv", "areq_id"),
    NamedQuery(
        "student_profile", "The student's profile used for aid eligibility: class year, enrollment, GPA, Pell, "
        "FAFSA, major, residency.",
        [("opportunities", "student_profile")], f"SELECT * FROM {OPP}.student_profile ORDER BY profile_id",
        _all("opportunities", "student_profile", "profile_id"), "all rows of opportunities/student_profile.csv",
        "profile_id"),
    NamedQuery(
        "meal_plan", "The meal plan: swipes and dining dollars for the semester, and its dates.",
        [("meal_plan", "plan")], f"SELECT * FROM {MEAL}.plan ORDER BY plan_id",
        _all("meal_plan", "plan", "plan_id"), "all rows of meal_plan/plan.csv", "plan_id"),
    NamedQuery(
        "meal_transactions", "Meal plan use between two dates: swipes and dining-dollar purchases, with place.",
        [("meal_plan", "transactions")],
        f"SELECT * FROM {MEAL}.transactions WHERE to_date(substr(timestamp, 1, 10), 'yyyy-MM-dd') "
        "BETWEEN DATE '{start_date}' AND DATE '{end_date}' ORDER BY meal_id",
        lambda p: _sorted(_between(_load("meal_plan", "transactions"), "timestamp", _day_of, p), "meal_id"),
        "meal_plan/transactions.csv where the timestamp's date is between {start_date} and {end_date}", "meal_id",
        DATE_RANGE),
]
REGISTRY = {q.name: q for q in QUERIES}


def catalog():
    """What the PLAN model sees: name, description and typed parameters for every named query."""
    return [{"name": q.name, "description": q.description,
             "params": [{"name": p.name, "type": p.type, "description": p.description,
                         **({"choices": list(p.choices)} if p.choices else {})} for p in q.params]}
            for q in QUERIES]


# ---------------------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------------------
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate(q, params):
    known = {p.name: p for p in q.params}
    unknown = set(params) - set(known)
    if unknown:
        raise QueryError(f"{q.name}: unknown parameter(s) {sorted(unknown)}")
    clean = {}
    for p in q.params:
        if p.name not in params:
            raise QueryError(f"{q.name}: missing parameter {p.name}")
        value = str(params[p.name])
        if p.type == "date":
            if not _DATE_RE.match(value):
                raise QueryError(f"{q.name}: {p.name} must be YYYY-MM-DD, got {value!r}")
            try:
                date.fromisoformat(value)
            except ValueError:
                raise QueryError(f"{q.name}: {p.name} is not a real date: {value!r}") from None
        elif p.type == "choice" and value not in p.choices:
            raise QueryError(f"{q.name}: {p.name} must be one of {list(p.choices)}, got {value!r}")
        clean[p.name] = value
    if "start_date" in clean and clean["start_date"] > clean["end_date"]:
        raise QueryError(f"{q.name}: start_date is after end_date")
    return clean


def _cache_path(name, params):
    key = hashlib.sha256(json.dumps([name, params], sort_keys=True).encode()).hexdigest()[:16]
    return config.ZETARIS_CACHE_DIR / f"{name}-{key}.json"


def is_cached(name, **params):
    """True if a Zetaris result for this query and these parameters is already in the disk cache."""
    return _cache_path(name, _validate(REGISTRY[name], params)).exists()


def clear_cache():
    shutil.rmtree(config.ZETARIS_CACHE_DIR, ignore_errors=True)


def _zetaris(q, sql):
    from zetaris_db import query_with_columns   # imported lazily: the local backend needs no Java
    columns, rows = query_with_columns(sql)
    # An empty CSV cell comes back as NULL; return "" so rows match the files exactly as stored.
    return columns, [{c: ("" if v is None else str(v)) for c, v in zip(columns, row)} for row in rows]


def run(name, backend=None, use_cache=None, **params):
    """Run a named query and return QueryResult(columns, rows, evidence)."""
    if name not in REGISTRY:
        raise QueryError(f"unknown query {name!r}; known: {sorted(REGISTRY)}")
    q = REGISTRY[name]
    backend = (backend or config.DATA_BACKEND).lower()
    use_cache = config.ZETARIS_CACHE if use_cache is None else use_cache
    clean = _validate(q, params)
    sql = q.sql.format(**clean)
    sources = sorted({s for s, _ in q.tables})
    tables = [f"{SOURCE_DATABASES[s]}.{t}" if backend == "zetaris" else f"{s}/{t}.csv" for s, t in q.tables]
    start = time.perf_counter()
    original = None

    if backend == "local":
        rows = q.local(clean)
        columns = list(rows[0].keys()) if rows else []
        ran, used = q.local_desc.format(**clean), "local"
    elif backend == "zetaris":
        path = _cache_path(name, clean)
        if use_cache and path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            columns, rows, original, used = cached["columns"], cached["rows"], cached["duration_s"], "zetaris-cached"
        else:
            columns, rows = _zetaris(q, sql)
            used = "zetaris"
            if use_cache:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"columns": columns, "rows": rows, "sql": sql,
                                            "duration_s": time.perf_counter() - start}), encoding="utf-8")
        ran = sql
    else:
        raise QueryError(f"unknown backend {backend!r}; use 'zetaris' or 'local'")

    id_col = next(c for c in columns if c.lower() == q.id_column.lower()) if rows else q.id_column
    evidence = Evidence(query=name, sources=sources, tables=tables, sql=ran, params=clean,
                        row_ids=[r[id_col] for r in rows], backend=used,
                        duration_s=round(time.perf_counter() - start, 3),
                        original_duration_s=None if original is None else round(original, 3))
    return QueryResult(columns, rows, evidence)
