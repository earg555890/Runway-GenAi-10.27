"""Ask Runway: PLAN -> EXECUTE -> EXPLAIN -> CHECK -> ACTIONS (CLAUDE.md rules 2, 9, 10).

    for kind, payload in agent.run("How long will my money last?", scenario):
        kind: "stage" (a friendly progress message), "text" (an answer chunk), "restart" (discard the
        text so far: the answer is being rewritten), "answer" (the final Answer, always last)

- PLAN: one JSON call (PLAN model, thinking off) picks ONE engine tool and its arguments.
  Python validates them strictly (parse_plan); a failed or slow PLAN falls back to keywords.
- EXECUTE: deterministic engine calls. The Computed records the result depends on, plus the
  source rows behind them, become a small evidence pack: calculations C1..Cn, sources E1..En.
- EXPLAIN: one streamed call (EXPLAIN model, thinking on) writes the answer from the pack only.
- CHECK: every dollar amount and date in the answer must appear in the pack, and every [C#]/[E#]
  must exist. On failure EXPLAIN is retried once with the problems listed (rule 10); then the
  answer is shown with a warning. If EXPLAIN fails, a template answer is built from the pack.
- ACTIONS: drafts (an email to financial aid, a checklist) from templates. Never sent.

Answers are cached by (question, what-ifs) in config.ANSWER_CACHE_DIR; config.ANSWER_MODE picks
live / cached / replay.
"""
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import config
import engine
import llm_client
import normalize
import wording as w

PLAN_TIMEOUT_S = 120
EXPLAIN_TIMEOUT_S = 240
EXPLAIN_MAX_TOKENS = 8192        # the reasoning trace counts too; 4096 once left no room for the answer
FALLBACK_MAX_TOKENS = 16384      # Lightning reasons at length (~20K characters) before it answers
CALENDAR = ["Thanksgiving is Thu Nov 26, 2026."]
MAX_PACK_CALCS = 24
MAX_ROWS_PER_SOURCE = 8
STAGES = {"plan": "Understanding your question...", "execute": "Checking your accounts...",
          "math": "Doing the math...", "explain": "Writing your answer..."}
# The two flight questions side by side show timing: bought tomorrow it's "Not right now"; bought Nov 10,
# after the refund arrives, it's "Yes, if you do 2 things".
SUGGESTED = ["Can I afford a $400 flight home for Thanksgiving if I book it Nov 10?", "How long will my money last?",
             "Where is my money leaking?", "Can I afford a $400 flight home for Thanksgiving?"]
OFF_TOPIC = ("I can help with your money this semester: whether you can afford something, how long your money "
             "will last, where it's leaking, your refund, or what changes would help. Try asking one of those!")

TOOLS = {
    "can_afford": dict(
        does="Can the student afford one purchase? Answers yes / no / yes-if-you-make-these-changes.",
        args={"item": "short name of the thing, e.g. \"flight home\"", "cost": "dollars, a positive number",
              "date": "YYYY-MM-DD when the money is spent; ONLY if the student said when (resolve words like "
                      "\"next Friday\" with the calendar); leave it out otherwise",
              "account": "\"checking\" (debit, the default) or \"card\" (credit card)"}),
    "runway": dict(
        does="How long the money lasts, the lowest point, whether they are OK this semester (vague worries too).",
        args={}),
    "what_if": dict(
        does="What changes if the student makes changes: cancel subscriptions, add work shifts, send the "
             "verification form to financial aid.",
        args={"cancel_subscriptions": "list of subscription names", "extra_shifts": "list of {\"date\": "
              "\"YYYY-MM-DD\", \"hours\": number}", "send_verification_form": "true or false",
              "form_date": "YYYY-MM-DD when the form is sent (optional; default tomorrow)"}),
    "find_leaks": dict(does="Where money is leaking: duplicate subscriptions, fees.", args={}),
    "refund_status": dict(does="Why the financial aid refund is held, how much, and what releases it.", args={}),
    "cash_crunches": dict(does="Weeks where a bill lands right after a small paycheck.", args={}),
}
INTENTS = ("afford", "runway", "what_if", "leaks", "refund", "crunch", "off_topic")


# ---------------------------------------------------------------------------------------
# Types (plain data, so answers can be cached as JSON)
# ---------------------------------------------------------------------------------------
@dataclass
class Plan:
    intent: str
    tool: str | None
    args: dict                   # validated; dates ISO strings, money strings
    clarifying_question: str | None = None
    assumptions: list = field(default_factory=list)
    source: str = "llm"          # "llm" or "keywords" (fallback)


@dataclass
class Check:
    ok: bool
    problems: list
    amounts: int = 0
    dates: int = 0
    citations: int = 0


@dataclass
class Action:
    id: str
    kind: str                    # "email" or "checklist"
    title: str
    to: str = ""
    subject: str = ""
    body: str = ""
    items: list = field(default_factory=list)


@dataclass
class Answer:
    question: str
    text: str
    verdict: str | None          # yes / no / yes_if / covered / runs_out / None
    verdict_label: str | None
    plan: dict
    pack: dict                   # {"items": [...], "context": [...]}
    check: dict
    reasoning: str
    actions: list
    fixes: list                  # [{"kind", "name"}] for "Do these"
    mode: str                    # live / cached / replay / fallback / off_topic
    explain_source: str          # llm / template / none
    notes: list
    timings: dict
    retries: dict
    models: dict
    scenario: str
    created: float = 0.0
    sections: dict = field(default_factory=dict)     # {"answer", "why": [...], "do": [...], "note"}
    facts: list = field(default_factory=list)        # required facts: [{"key", "label", "appended"}]

    def to_json(self):
        return json.dumps(asdict(self), default=str)

    @staticmethod
    def from_json(s):
        return Answer(**json.loads(s))


# ---------------------------------------------------------------------------------------
# PLAN
# ---------------------------------------------------------------------------------------
def _money(x, what):
    try:
        v = Decimal(str(x).replace("$", "").replace(",", ""))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{what} must be a number, got {x!r}") from None
    if v <= 0:
        raise ValueError(f"{what} must be positive, got {x!r}")
    return engine.D(v)


def _semester_date(x, what):
    try:
        d = date.fromisoformat(str(x))
    except ValueError:
        raise ValueError(f"{what} must be YYYY-MM-DD, got {x!r}") from None
    if not config.DEMO_TODAY < d <= config.SEMESTER_END:
        raise ValueError(f"{what} {d} is outside the rest of the semester ({config.DEMO_TODAY + timedelta(days=1)} "
                         f"to {config.SEMESTER_END})")
    return d


def parse_plan(data, sub_names):
    """Strictly validate the PLAN model's JSON. Raises ValueError with a message the model can fix."""
    if not isinstance(data, dict):
        raise ValueError("the reply must be one JSON object")
    intent, tool = data.get("intent"), data.get("tool")
    clarifying = data.get("clarifying_question") or None
    if tool in (None, "", "none"):
        if intent != "off_topic" and not clarifying:
            raise ValueError('"tool" is required unless "intent" is "off_topic" or you ask a clarifying_question')
        return Plan(intent or "off_topic", None, {}, clarifying)
    if tool not in TOOLS:
        raise ValueError(f"unknown tool {tool!r}; use one of {sorted(TOOLS)}")
    args = data.get("args") or {}
    if not isinstance(args, dict):
        raise ValueError('"args" must be an object')
    unknown = set(args) - set(TOOLS[tool]["args"])
    if unknown:
        raise ValueError(f"{tool} has no argument(s) {sorted(unknown)}; allowed: {sorted(TOOLS[tool]['args'])}")
    clean, assumptions = {}, []
    tomorrow = config.DEMO_TODAY + timedelta(days=1)
    if tool == "can_afford":
        clean["cost"] = str(_money(args.get("cost"), "cost"))
        clean["item"] = (str(args.get("item") or "").strip() or "this purchase")[:60]
        clean["account"] = args.get("account") or "checking"
        if clean["account"] not in ("checking", "card"):
            raise ValueError(f'account must be "checking" or "card", got {clean["account"]!r}')
        if args.get("date"):
            clean["date"] = _semester_date(args["date"], "date").isoformat()
        else:
            clean["date"] = tomorrow.isoformat()
            assumptions.append(f"You didn't say when you'd buy it, so I assumed tomorrow, {w.day(tomorrow)}.")
    elif tool == "what_if":
        by_lower = {s.lower(): s for s in sub_names}
        cancels = []
        for name in args.get("cancel_subscriptions") or []:
            if str(name).lower() not in by_lower:
                raise ValueError(f"unknown subscription {name!r}; known: {sorted(sub_names)}")
            cancels.append(by_lower[str(name).lower()])
        shifts = []
        for s in args.get("extra_shifts") or []:
            if not isinstance(s, dict):
                raise ValueError('each extra shift must be {"date": "YYYY-MM-DD", "hours": number}')
            hours = _money(s.get("hours"), "hours")
            if hours > 12:
                raise ValueError(f"a shift can't be {hours} hours")
            shifts.append({"date": _semester_date(s.get("date"), "shift date").isoformat(), "hours": str(hours)})
        send = bool(args.get("send_verification_form"))
        if args.get("form_date") and not send:
            send = True
        form_date = _semester_date(args["form_date"], "form_date") if args.get("form_date") else tomorrow
        if not (cancels or shifts or send):
            raise ValueError("what_if needs at least one change (cancel_subscriptions, extra_shifts or "
                             "send_verification_form)")
        clean = {"cancel_subscriptions": cancels, "extra_shifts": shifts, "send_verification_form": send,
                 "form_date": form_date.isoformat()}
    return Plan(intent if intent in INTENTS else tool, tool, clean, clarifying, assumptions)


def plan_messages(question, scenario, sub_names):
    tools = "\n".join(f"- {name}: {t['does']}" + ("".join(f"\n    {a}: {d}" for a, d in t["args"].items()))
                      for name, t in TOOLS.items())
    system = (
        "You are the planner for Runway, a money app for one college student. Pick exactly ONE tool for the "
        "student's question and its arguments. You never do math and never answer the question yourself.\n"
        f"Today is {w.day(config.DEMO_TODAY)}, {config.DEMO_TODAY.isoformat()}. The semester ends "
        f"{w.day(config.SEMESTER_END)}, {config.SEMESTER_END.isoformat()}. Calendar: {' '.join(CALENDAR)}\n"
        f"The student's subscriptions: {', '.join(sub_names)}.\n"
        f"The student's current what-ifs: {scenario.describe()}.\n\nTools:\n{tools}\n\n"
        "Reply with JSON only, exactly this shape:\n"
        '{"intent": one of ' + json.dumps(list(INTENTS)) + ', "tool": a tool name or "none", "args": {...}, '
        '"clarifying_question": null}\n'
        "Rules: dates are YYYY-MM-DD between tomorrow and the semester end. A purchase date is when the money "
        "is spent, not when a trip happens (\"a flight home for Thanksgiving\" gives NO purchase date); if the "
        "student gives none, leave \"date\" out. Questions that are "
        'not about the student\'s money get "intent": "off_topic", "tool": "none". Vague worries ("am I ok?") '
        "use runway.")
    return [{"role": "system", "content": system}, {"role": "user", "content": question}]


_AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)")
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"], start=1)}
_MDAY = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b", re.I)


_DATE_WORDS = re.compile(
    r"\b(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}|\d{1,2}/\d{1,2}|"
    r"mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:rs|rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?|"
    r"today|tonight|tomorrow|next week|this week|weekend|in \d+ days?|on (?:thanksgiving|black friday|christmas))\b",
    re.I)


def ground_purchase_date(plan, question):
    """A purchase date must come from the question. "A flight home for Thanksgiving" names the trip, not
    when the money is spent, so an ungrounded date becomes tomorrow, with the assumption recorded."""
    if plan.tool != "can_afford" or plan.assumptions or _DATE_WORDS.search(question):
        return plan
    tomorrow = config.DEMO_TODAY + timedelta(days=1)
    if plan.args.get("date") != tomorrow.isoformat():
        plan.args["date"] = tomorrow.isoformat()
    plan.assumptions.append(f"You didn't say when you'd buy it, so I assumed tomorrow, {w.day(tomorrow)}.")
    return plan


def keyword_plan(question, sub_names):
    """Fallback when PLAN fails: keywords for the suggested questions. None if nothing matches."""
    q = question.lower()
    amount = _AMOUNT.search(question)
    if "afford" in q and amount:
        m = _MDAY.search(question)
        args = {"cost": amount.group(1), "item": "flight home" if "flight" in q else "this purchase",
                "account": "card" if "credit card" in q or "on my card" in q else "checking"}
        if m:
            args["date"] = date(2026, _MONTHS[m.group(1).lower()[:3]], int(m.group(2))).isoformat()
        try:
            p = parse_plan({"intent": "afford", "tool": "can_afford", "args": args}, sub_names)
        except ValueError:
            return None
    elif any(k in q for k in ("how long", "last", "run out", "runway", "am i ok", "okay")):
        p = Plan("runway", "runway", {})
    elif any(k in q for k in ("leak", "wast", "subscription")):
        p = Plan("leaks", "find_leaks", {})
    elif "refund" in q:
        p = Plan("refund", "refund_status", {})
    else:
        return None
    p.source = "keywords"
    return p


# ---------------------------------------------------------------------------------------
# EXECUTE
# ---------------------------------------------------------------------------------------
@dataclass
class ToolResult:
    verdict: str | None
    key: list                    # the Computed records the answer is about (most important first)
    ledger: engine.Ledger
    fixes: list = field(default_factory=list)            # engine.Fix (yes_if)
    zero_fixes: list = field(default_factory=list)       # fixes that save $0 (Apple Music)
    facts: dict = field(default_factory=dict)            # for templates and actions


def _without_fixes(scenario):
    return engine.Scenario(refund_submit_date=scenario.refund_submit_date, extra_shifts=scenario.extra_shifts)


def _projection_key(p, ledger):
    r = engine.main_reason(p)
    key = [p.lowest, p.lowest_date, p.first_below_zero, p.runway_weeks, p.end_balance]
    if r.event:
        key.insert(0, r.event.computed)
        key.append(ledger.add("balance the day before that payment", r.balance_before, "USD",
                              f"End-of-day checking balance on {w.day(r.event.date - timedelta(days=1))}.",
                              [p.lowest]))
    return key, r


def execute(plan, scenario, ds):
    ledger, a = engine.Ledger(), plan.args
    if plan.tool == "can_afford":
        v = engine.can_afford(Decimal(a["cost"]), a["date"], a["account"], _without_fixes(scenario), ds, a["item"])
        best = v.with_fixes or v.without_fixes
        key = [v.verdict_computed, v.without_fixes.lowest, v.without_fixes.lowest_date]
        if v.with_fixes:
            key += [v.with_fixes.lowest, v.with_fixes.lowest_date]
        key += [f.savings for f in v.considered]
        applied = all(f.kind == "refund" and scenario.refund_released or f.name in scenario.cancel_subscriptions
                      for f in v.fixes)
        return ToolResult(v.verdict, key, v.ledger, v.fixes, [f for f in v.considered if f.savings.value <= 0],
                          {"purchase": v.purchase, "fixes_applied": bool(v.fixes) and applied, "best": best,
                           "result": v})
    if plan.tool == "runway":
        p = engine.project(scenario, ds, ledger)
        key, r = _projection_key(p, ledger)
        return ToolResult("covered" if p.lasts_through_semester else "runs_out", key, ledger,
                          facts={"projection": p, "reason": r})
    if plan.tool == "what_if":
        new = scenario.plus(cancel_subscriptions=tuple(a["cancel_subscriptions"]),
                            extra_shifts=tuple(engine.ExtraShift(date.fromisoformat(s["date"]), Decimal(s["hours"]))
                                               for s in a["extra_shifts"]))
        if a["send_verification_form"]:
            new = engine.Scenario(True, date.fromisoformat(a["form_date"]), new.cancel_subscriptions,
                                  new.extra_shifts, new.purchases)
        before = engine.project(scenario, ds, ledger)
        after = engine.project(new, ds, ledger)
        deltas = engine.compare(before, after, ledger)
        key, r = _projection_key(after, ledger)
        key = [deltas["lowest"], deltas["end_balance"], deltas["runway_weeks"], *key, before.lowest,
               before.lowest_date, before.first_below_zero]
        shift_pay = [engine.extra_shift_pay(s, ds, scenario, ledger) for s in new.extra_shifts
                     if s not in scenario.extra_shifts]
        key += [c for _, c in shift_pay]
        latest = None                       # a shift paid after the run-out date: when would one be paid in time?
        run_out = after.first_below_zero.value
        if run_out and any(pay_date >= run_out for pay_date, _ in shift_pay):
            latest = engine.latest_shift_paid_before(run_out, ds, ledger)
            key += list(latest or [])
        fixes = engine.available_fixes(scenario, ds, ledger)
        chosen = [f for f in fixes if (f.kind == "refund" and a["send_verification_form"])
                  or f.name in a["cancel_subscriptions"]]
        key += [f.savings for f in chosen]
        return ToolResult("covered" if after.lasts_through_semester else "runs_out", key, ledger, chosen,
                          [f for f in fixes if f.savings.value <= 0 and f.name in a["cancel_subscriptions"]],
                          {"projection": after, "before": before, "reason": r, "shift_pay": shift_pay,
                           "new_scenario": new, "latest_shift": latest})
    if plan.tool == "find_leaks":
        leaks = engine.find_leaks(scenario, ds, ledger)
        key = [c for leak in leaks for c in leak.computed]
        return ToolResult(None, key, ledger, facts={"leaks": leaks})
    if plan.tool == "refund_status":
        f = engine.refund_status(scenario, ds, ledger)
        return ToolResult(None, list(f.computed.values()) if f else [], ledger, facts={"finding": f})
    if plan.tool == "cash_crunches":
        found = engine.cash_crunches(scenario, ds, ledger)
        return ToolResult(None, [c for f in found for c in f.computed.values()], ledger, facts={"findings": found})
    raise ValueError(f"unknown tool {plan.tool!r}")


# ---------------------------------------------------------------------------------------
# Evidence pack
# ---------------------------------------------------------------------------------------
class Pack:
    def __init__(self, items, context, ledger_to_pack):
        self.items, self.context, self.ids = items, context, ledger_to_pack

    def cite(self, computed):
        return f"[{self.ids[computed.id]}]" if computed.id in self.ids else ""

    def to_dict(self):
        return {"items": self.items, "context": self.context}

    def prompt_text(self):
        lines = ["Context:"] + [f"- {c}" for c in self.context] + ["", "Calculations:"]
        for it in self.items:
            if it["kind"] == "calc":
                lines.append(f"[{it['id']}] {it['title']} = {it['value']}. How: {it['how']}")
        lines += ["", "Source records:"]
        for it in self.items:
            if it["kind"] == "source":
                rows = "; ".join(f"{r['date']} {r['what']} {r['amount']}".strip() for r in it["rows"])
                more = f" (+{it['more']} more)" if it["more"] else ""
                lines.append(f"[{it['id']}] {it['title']}: {rows}{more}")
        return "\n".join(lines)


def build_pack(result, ds, plan, scenario):
    """The calculations the answer depends on (key records + their inputs, two levels), and the source
    rows behind them, grouped by the query that returned them."""
    ledger = result.ledger
    order, depth = [], {}
    queue = [(c.id, 0) for c in result.key if c is not None]
    while queue and len(order) < MAX_PACK_CALCS:
        cid, d = queue.pop(0)
        if cid in depth:
            continue
        depth[cid] = d
        order.append(cid)
        if d < 2:
            queue += [(i, d + 1) for i in ledger.get(cid).inputs if re.match(r"^C\d+$", i)]
    ids = {cid: f"C{n}" for n, cid in enumerate(order, start=1)}
    items, row_ids = [], []
    for cid in order:
        c = ledger.get(cid)
        items.append({"id": ids[cid], "kind": "calc", "title": c.label, "value": w.value(c), "raw": str(c.value),
                      "unit": c.unit, "how": c.how,
                      "uses": [ids.get(i, i) for i in c.inputs if not re.match(r"^C\d+$", i) or i in ids]})
        row_ids += [i for i in c.inputs if not re.match(r"^C\d+$", i)]
    row_ids = list(dict.fromkeys(row_ids))
    n = 0
    for ev in ds.evidence:
        used = [r for r in row_ids if r in ev.row_ids]
        if not used:
            continue
        n += 1
        rec0 = ds.row(used[0])
        rows = []
        for rid in used[:MAX_ROWS_PER_SOURCE]:
            d, what, amount = w.describe(ds.row(rid))
            rows.append({"row_id": rid, "date": w.day(d) if d else "", "what": what, "amount": amount})
        items.append({"id": f"E{n}", "kind": "source", "title": f"{w.SOURCE_PLAIN[rec0.source]} ({rec0.table})",
                      "source": rec0.source, "table": rec0.table, "rows": rows, "more": len(used) - len(rows),
                      "row_ids": used, "query": ev.query, "backend": ev.backend, "sql": ev.sql,
                      "duration_s": ev.duration_s, "original_duration_s": ev.original_duration_s})
    context = [f"Today is {w.day(config.DEMO_TODAY)}, {config.DEMO_TODAY.year}. The semester ends "
               f"{w.day(config.SEMESTER_END)}.", *CALENDAR,
               f"The student's current what-ifs: {scenario.describe()}.", *plan.assumptions]
    return Pack(items, context, ids)


# ---------------------------------------------------------------------------------------
# CHECK
# ---------------------------------------------------------------------------------------
MONEY_RE = re.compile(r"(?<![\w.])[-−]?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?")
DATE_RE = re.compile(r"\b(?:(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+)?"
                     r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b"
                     r"(?:,?\s+(20\d\d))?", re.I)
ISO_RE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
CITE_RE = re.compile(r"\[((?:[CE]\d+)(?:\s*[,;]\s*[CE]\d+)*)\]")
RECORD_ID = re.compile(r"\b(?:ACCT|AWD|CHK|CRD|DSB|HLD|JOB|LED|LT|PAY|PPI|REQ|RFD|RS|SHF|STM)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def find_amounts(text):
    out = []
    for m in MONEY_RE.finditer(text):
        out.append((m.group(0), Decimal(m.group(1).replace(",", "") + "." + (m.group(2) or "0"))))
    return out


def find_dates(text):
    """[(as written, date, weekday as written or None)]"""
    out = []
    for m in DATE_RE.finditer(text):
        month, dd = _MONTHS[m.group(2).lower()[:3]], int(m.group(3))
        year = int(m.group(4)) if m.group(4) else (2026 if month >= 8 else 2027)
        try:
            out.append((m.group(0), date(year, month, dd), m.group(1)))
        except ValueError:
            out.append((m.group(0), None, m.group(1)))
    for m in ISO_RE.finditer(text):
        try:
            out.append((m.group(0), date(int(m.group(1)), int(m.group(2)), int(m.group(3))), None))
        except ValueError:
            out.append((m.group(0), None, None))
    return out


def allowed_values(pack):
    """Every dollar amount (absolute value) and date that appears anywhere in the pack."""
    texts = list(pack.context)
    for it in pack.items:
        texts += [it.get("title", ""), it.get("value", ""), it.get("how", ""), it.get("raw", "")]
        texts += [f"{r['date']} {r['what']} {r['amount']}" for r in it.get("rows", [])]
    money, dates = {Decimal("0")}, set()
    for t in texts:
        money |= {abs(v) for _, v in find_amounts(t)}
        dates |= {d for _, d, _ in find_dates(t) if d}
    for it in pack.items:
        if it.get("unit") == "USD":
            try:
                money.add(abs(Decimal(it["raw"])))
            except InvalidOperation:
                pass
        elif it.get("unit") == "date" and it.get("raw") not in (None, "None"):
            dates.add(date.fromisoformat(it["raw"]))
    return money, dates


def _rounded(v):
    return abs(v).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


SECTION_HEAD = re.compile(r"^\s*[*#_]*\s*(ANSWER|WHY|DO THIS|NOTE)\s*[*_]*\s*:\s*[*_]*\s*(.*)$", re.I)


def parse_sections(text):
    """ANSWER / WHY / DO THIS / NOTE sections of an answer, or None if ANSWER or WHY is missing."""
    out, cur = {"answer": "", "why": [], "do": [], "note": ""}, None
    keys = {"ANSWER": "answer", "WHY": "why", "DO THIS": "do", "NOTE": "note"}
    for line in text.splitlines():
        m = SECTION_HEAD.match(line)
        if m:
            cur, line = keys[m.group(1).upper()], m.group(2)
        line = line.strip()
        if not line or cur is None:
            continue
        if cur in ("why", "do"):
            out[cur].append(re.sub(r"^(?:[-*•]|\d+[.)])\s*", "", line))
        else:
            out[cur] = (out[cur] + " " + line).strip()
    return out if out["answer"] and out["why"] else None


def check_answer(text, pack, require_format=False):
    """Every dollar amount and date must come from the pack; every citation must exist. A whole-dollar amount
    ("$1,462") matches a pack value that rounds to it ($1,462.37); signs are ignored, so "$1,462 below zero"
    and "-$1,462.37" both match -$1,462.37."""
    money, dates = allowed_values(pack)
    rounded = {_rounded(v) for v in money}
    ids = {it["id"] for it in pack.items}
    problems = [] if text.strip() else ["the answer is empty"]
    problems += [f"{x} is a record ID; never write record IDs" for x in dict.fromkeys(RECORD_ID.findall(text))]
    if require_format and text.strip() and parse_sections(text) is None:
        problems.append("the answer is not in the ANSWER / WHY / DO THIS format")
    amounts = find_amounts(text)
    for written, v in amounts:
        whole = "." not in written
        if abs(v) not in money and not (whole and abs(v) in rounded):
            problems.append(f"{written.strip()} is not in the facts")
    found = find_dates(text)
    for written, d, wd in found:
        if d is None or d not in dates:
            problems.append(f"{written.strip()} is not a date in the facts")
        elif wd and WEEKDAYS[d.weekday()] != wd.lower()[:3]:
            problems.append(f"{written.strip()} has the wrong weekday (it is a {d:%A})")
    cites = [c.strip() for m in CITE_RE.finditer(text) for c in re.split(r"[,;]", m.group(1))]
    problems += [f"[{c}] is not in the facts" for c in dict.fromkeys(cites) if c not in ids]
    return Check(not problems, list(dict.fromkeys(problems)), len(amounts), len(found), len(cites))


# ---------------------------------------------------------------------------------------
# EXPLAIN, template answers, verdicts
# ---------------------------------------------------------------------------------------
EXPLAIN_SYSTEM = (
    "You are Runway, a friendly money coach for a stressed college student.\n"
    "Write at a grade 6-8 reading level. Short sentences (under 15 words). One idea per sentence.\n"
    "Reply in EXACTLY this format, under 110 words in total:\n"
    "ANSWER: <one short sentence with the answer>\n"
    "WHY:\n- <short reason>\n- <short reason>\n- <optional third reason>\n"
    "DO THIS:\n1. <concrete next step>\n2. <optional second step>\n"
    "NOTE: <optional: one line for an assumption or a timing insight>\n"
    "Rules:\n"
    "- Use ONLY numbers and dates from the facts below. Never calculate or invent a number or date.\n"
    "- Money: from $100 up, round to whole dollars (\"$1,850\", \"$360\"). Under $100, keep the cents "
    "(\"$23.98\", \"$5.81\").\n"
    "- Never write a negative balance with a minus sign. Write \"$1,462 below zero\".\n"
    "- Dates like \"Mon, Nov 9\".\n"
    "- Put a citation after each number or date, like [C3] or [E2]. At most 2 citations per bullet. Only cite "
    "ids that exist in the facts.\n"
    "- If the facts list an assumption, put it in NOTE.\n"
    "- If cancelling a subscription is part of the answer and one saves $0.00, explain why in NOTE: its charges "
    "go on the credit card, and that bill is paid after the semester ends.\n"
    "- Include EVERY fact listed under \"Your answer must include all of these\", with its number, date and "
    "citation, in the place it asks for.\n"
    "- Never write record IDs such as HLD-01, CHK-0042 or RFD-01. Cite with [C#] or [E#] only.\n"
    "- No jargon: never say scenario, projection, ledger, evidence or computed. No bold, no headings.")


def explain_messages(question, plan, result, pack, verdict_label, required=()):
    facts = pack.prompt_text()
    head = f"Question: {question}\nWhat Runway checked: {plan_words(plan)}"
    if verdict_label:
        head += f"\nThe answer: {verdict_label}"
    if required:
        head += "\nYour answer must include all of these:\n" + "\n".join(f.prompt() for f in required)
    return [{"role": "system", "content": EXPLAIN_SYSTEM},
            {"role": "user", "content": f"{head}\n\n{facts}\n\nWrite the answer now, in the format."}]


def plan_words(plan):
    a = plan.args
    if plan.tool == "can_afford":
        how = "debit card (checking)" if a["account"] == "checking" else "credit card"
        return f"can you afford {a['item']} for {w.dollars(Decimal(a['cost']))} on " \
               f"{w.day(date.fromisoformat(a['date']))}, paid by {how}"
    if plan.tool == "what_if":
        parts = [f"cancel {', '.join(a['cancel_subscriptions'])}"] if a["cancel_subscriptions"] else []
        parts += [f"an extra {s['hours']}-hour shift on {w.day(date.fromisoformat(s['date']))}"
                  for s in a["extra_shifts"]]
        if a["send_verification_form"]:
            parts.append(f"send the verification form on {w.day(date.fromisoformat(a['form_date']))}")
        return "what happens if you " + " and ".join(parts)
    return {"runway": "how long your money lasts", "find_leaks": "where your money is leaking",
            "refund_status": "why your refund is on hold", "cash_crunches": "weeks where money gets tight"
            }.get(plan.tool, "your question")


def verdict_label(result):
    v = result.verdict
    if v == "yes_if":
        return "You can afford it." if result.facts.get("fixes_applied") else \
            f"Yes, if you do {w.things(len(result.fixes))}"
    if v == "yes":
        return "Yes"
    if v == "no":
        return "Not right now"
    if v == "covered":
        return "You're covered"
    if v == "runs_out":
        return f"Money runs out {w.day(result.facts['projection'].first_below_zero.value)}"
    return None


def _fix_step(f, ds, scenario, pack):
    if f.kind == "refund":
        rel = engine.refund_release_date(ds, scenario)
        return (f"Send your verification form to financial aid. Your {w.dollars(f.savings.value)} refund comes "
                f"around {w.day(rel)} {pack.cite(f.savings)}.")
    return f"Cancel {f.name}. That saves {w.dollars(f.savings.value)} this semester {pack.cite(f.savings)}."


def _format(answer, why, do, note=""):
    text = f"ANSWER: {answer}\nWHY:\n" + "\n".join(f"- {x}" for x in why)
    if do:
        text += "\nDO THIS:\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(do, start=1))
    return text + (f"\nNOTE: {note}" if note else "")


def template_answer(plan, result, pack, ds, scenario):
    """A short answer in the ANSWER / WHY / DO THIS format, built only from the pack, with citations. Used
    when no model is available."""
    c, f = pack.cite, result.facts
    note = " ".join(plan.assumptions)
    if plan.tool == "can_afford":
        r = f["result"]
        base, best = r.without_fixes, r.with_fixes
        if r.verdict == "yes":
            return _format(f"Yes, you can afford it {c(r.verdict_computed)}.",
                           [f"Your lowest point would be {w.balance(base.lowest.value)} {c(base.lowest)}.",
                            f"That's on {w.day(base.lowest_date.value)} {c(base.lowest_date)}."],
                           ["Check again if your plans change."], note)
        if r.verdict == "no":
            return _format(f"Not right now {c(r.verdict_computed)}.",
                           [f"Even with every fix, you'd be {w.balance(best.lowest.value)} {c(best.lowest)}.",
                            f"That's on {w.day(best.lowest_date.value)} {c(best.lowest_date)}."],
                           ["Try a later date, after your refund arrives."], note)
        zero = [z for z in result.zero_fixes]
        if zero:
            note = (note + " " if note else "") + (
                f"Cancelling {zero[0].name} saves {w.money(zero[0].savings.value)} {c(zero[0].savings)} this "
                "semester. Its card bill is paid after the semester ends.")
        return _format(f"Yes, if you do {w.things(len(r.fixes))} first {c(r.verdict_computed)}.",
                       [f"Without changes, you'd be {w.balance(base.lowest.value)} {c(base.lowest)}.",
                        f"With them, your lowest point is {w.balance(best.lowest.value)} {c(best.lowest)} on "
                        f"{w.day(best.lowest_date.value)}."],
                       [_fix_step(x, ds, scenario, pack) for x in r.fixes], note)
    if plan.tool in ("runway", "what_if"):
        p, r = f["projection"], f["reason"]
        if p.lasts_through_semester:
            answer = f"You're covered all semester {c(p.first_below_zero)}."
            why = [f"Your lowest point is {w.balance(p.lowest.value)} {c(p.lowest)}.",
                   f"That's on {w.day(p.lowest_date.value)} {c(p.lowest_date)}."]
        else:
            answer = (f"Your money runs out on {w.day(p.first_below_zero.value)} {c(p.first_below_zero)}, in "
                      f"{w.weeks_words(p.runway_weeks.value)} {c(p.runway_weeks)}.")
            why = [f"Your {w.event_name(r.event)} of {w.dollars(r.event.amount)} is due that week "
                   f"{c(r.event.computed)}."] if r.event else ["Everyday spending slowly adds up."]
        changes = [f"The extra shift adds {w.dollars(pay.value)} to your {w.day(pay_date)} paycheck {c(pay)}."
                   for pay_date, pay in f.get("shift_pay", [])]
        if changes:                                       # a what-if leads with the change itself
            answer, why = changes[0], [answer] + why + changes[1:]
        if f.get("latest_shift"):
            shift_c, pay_c = f["latest_shift"]
            why.append(f"A shift worked by {w.day(shift_c.value)} is paid {w.day(pay_c.value)}, before you run out "
                       f"{c(shift_c)}.")
        return _format(answer, why, ["Look at the ways to fix it in My semester."], note)
    if plan.tool == "find_leaks":
        why, do = [], []
        for leak in f["leaks"]:
            if leak.kind == "duplicate_subscriptions":
                comb = next(x for x in leak.computed if x.label.startswith("combined"))
                pick = next(x for x in leak.computed if x.label.startswith("which"))
                why.append(f"You pay {w.dollars(comb.value)} a month for two music apps {c(comb)}.")
                do.append(f"Cancel {pick.value}. That saves {w.dollars(leak.savings.value)} this semester "
                          f"{c(leak.savings)}.")
            else:
                fee = next(x for x in leak.computed if x.label.startswith("fee "))
                why.append(f"Rent caused a {w.dollars(fee.value)} overdraft fee {c(fee)}.")
        return _format("Two things are leaking money.", why, do or ["Keep an eye on your fees."],
                       "Fee savings are estimated.")
    if plan.tool == "refund_status":
        k = f["finding"].computed
        return _format(f"Your {w.dollars(k['refund_amount'].value)} refund is on hold {c(k['refund_amount'])}.",
                       ["Financial aid is waiting for your verification form.",
                        f"The refund comes {k['release_rule_business_days'].value} business days after that "
                        f"{c(k['release_rule_business_days'])}."],
                       [f"Send the form. Your refund comes around {w.day(k['release_date'].value)} "
                        f"{c(k['release_date'])}."], note)
    if plan.tool == "cash_crunches":
        why = []
        for fi in f["findings"]:
            k = fi.computed
            why += [f"A {w.dollars(k['installment'].value)} tuition payment is due {w.day(k['installment_due'].value)} "
                    f"{c(k['installment'])}.",
                    f"Your paycheck before it is only {w.dollars(k['paycheck_net'].value)} {c(k['paycheck_net'])}."]
        return _format("One week in November is tight." if why else "No tight weeks ahead.",
                       why or ["Your bills and paychecks line up."], ["Set that money aside now."], note)
    return OFF_TOPIC


def explain_chain():
    """EXPLAIN models to try in order: Super, then Lightning (the PLAN model, with thinking on)."""
    return list(dict.fromkeys(m for m in (config.NVIDIA_EXPLAIN_MODEL, config.NVIDIA_PLAN_MODEL) if m))


def model_name(model):
    if not model or model == "template":
        return "a template"
    if "super" in model:
        return "Nemotron Super"
    if "lightning" in model:
        return "Nemotron Lightning"
    return model


def _explain_with(llm, model, messages, pack, retries, required=()):
    """Stream one EXPLAIN answer from `model`, check it (numbers, dates, citations, format, record IDs, required
    facts), and allow one rewrite. Yields ("text"/"restart", ...) events and returns (text, reasoning, check,
    missing) where missing are the required facts the model still left out. Raises if the model fails or answers
    empty twice."""
    text, reasoning, check, missing = "", "", None, []
    for attempt in range(2):
        limit = EXPLAIN_MAX_TOKENS if model == config.NVIDIA_EXPLAIN_MODEL else FALLBACK_MAX_TOKENS
        stream = llm.stream_chat(messages, thinking=True, model=model, timeout=EXPLAIN_TIMEOUT_S, retries=1,
                                 max_tokens=limit)
        for kind, chunk in stream:
            if kind == "text":
                yield "text", chunk
        text, reasoning = _strip_think(stream.result.text, (reasoning + "\n" + stream.result.reasoning).strip())
        check = check_answer(text, pack, require_format=True)
        missing = missing_facts(text, required) if text else list(required)
        if (check.ok and not missing) or attempt == 1:
            break
        retries["explain_rewrite"] = retries.get("explain_rewrite", 0) + 1
        yield "restart", "Double-checking the numbers..."
        problems = check.problems + [f"missing {f.label}: {f.line}" + (" (put it FIRST)" if f.where == "lead" else
                                                                         " (in NOTE)" if f.where == "note" else "")
                                     for f in missing]
        messages = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "Problems: " + "; ".join(problems) +
             ". Rewrite the answer in the ANSWER / WHY / DO THIS / NOTE format, using only numbers, dates and ids "
             "from the facts, and include every required fact."}]
    if not text:
        raise llm_client.LLMError("the model returned an empty answer twice")
    return text, reasoning, check, missing


# ---------------------------------------------------------------------------------------
# Required facts: what every answer must contain, per tool (enforced by CHECK and scored by eval_agent.py)
# ---------------------------------------------------------------------------------------
VERDICT_WORDS = {"yes": ("yes", "can afford"), "yes_if": ("yes", "can afford"),
                 "no": ("not right now", "no,", "no.", "can't", "cannot", "not yet")}


@dataclass
class Fact:
    key: str
    label: str                   # what it is, in plain words (for the prompt and the rewrite request)
    line: str                    # a deterministic sentence stating it, with its citation (the fallback)
    money: tuple = ()            # amounts that must appear (rounded whole dollars accepted)
    date: date | tuple | None = None   # a date (or a tuple of dates) that must appear
    words: tuple = ()            # at least one of these words must appear (case-insensitive)
    where: str = "any"           # "any", "lead" (ANSWER or the first WHY bullet), "note", "answer"

    def prompt(self):
        place = {"lead": " (put this FIRST: in ANSWER or the first WHY bullet)", "note": " (in NOTE)",
                 "answer": " (in ANSWER)"}.get(self.where, "")
        return f"- {self.label}: {self.line}{place}"


def required_facts(plan, result, pack, ds, scenario):
    """The facts one answer must contain, each with its exact engine value and citation."""
    c, f, out = pack.cite, result.facts, []
    tool = plan.tool
    if tool == "can_afford":
        r = f["result"]
        label = verdict_label(result)
        out.append(Fact("verdict", "the answer", f"{label} {c(r.verdict_computed)}.",
                        words=VERDICT_WORDS[r.verdict], where="answer"))
        for fx in r.fixes:
            out.append(_fix_fact(fx, ds, scenario, c))
        best = r.with_fixes if r.verdict in ("yes_if", "no") and r.with_fixes else r.without_fixes
        what = "with the fixes" if r.verdict == "yes_if" else ("even with every fix" if r.verdict == "no" else "")
        out.append(Fact("lowest", f"the lowest point {what}".strip(),
                        f"Your lowest point would be {w.balance(best.lowest.value)} {c(best.lowest)} on "
                        f"{w.day(best.lowest_date.value)}.", money=(best.lowest.value,),
                        date=best.lowest_date.value))
    elif tool in ("runway", "what_if"):
        p, r = f["projection"], f["reason"]
        if tool == "what_if":
            for pay_date, pay in f.get("shift_pay", []):
                out.append(Fact("shift_pay", "the extra pay from the shift",
                                f"The extra shift adds {w.dollars(pay.value)} to your {w.day(pay_date)} paycheck "
                                f"{c(pay)}.", money=(pay.value,), date=pay_date if pay.value > 0 else None,
                                where="lead"))
            for fx in result.fixes:
                fact = _fix_fact(fx, ds, f["new_scenario"], c)
                fact.where = "lead"
                out.append(fact)
            if f.get("latest_shift"):
                shift_c, pay_c = f["latest_shift"]
                out.append(Fact("latest_shift", "the latest shift that would be paid before you run out",
                                f"A shift worked by {w.day(shift_c.value)} is paid {w.day(pay_c.value)}, before you "
                                f"run out {c(shift_c)}.", date=(shift_c.value, pay_c.value)))
        if p.lasts_through_semester:
            out.append(Fact("lowest", "covered all semester, and the lowest point",
                            f"You're covered all semester. Your lowest point is {w.balance(p.lowest.value)} "
                            f"{c(p.lowest)} on {w.day(p.lowest_date.value)}.",
                            money=(p.lowest.value,), date=p.lowest_date.value))
        else:
            out.append(Fact("runs_out", "the day the money runs out",
                            f"Your money runs out on {w.day(p.first_below_zero.value)} {c(p.first_below_zero)}.",
                            date=p.first_below_zero.value))
            if tool == "runway" and r.event:
                out.append(Fact("cause", "the payment that causes it and what you'll have",
                                f"A {w.dollars(r.event.amount)} {w.event_name(r.event)} {c(r.event.computed)} is due "
                                f"{w.day(r.event.date)}, when you'll have {w.balance(r.balance_before)}.",
                                money=(r.event.amount, r.balance_before)))
    elif tool == "find_leaks":
        for leak in f["leaks"]:
            if leak.kind == "duplicate_subscriptions":
                names = tuple(x.label.removesuffix(" monthly cost") for x in leak.computed
                              if x.label.endswith("monthly cost"))
                comb = next(x for x in leak.computed if x.label.startswith("combined"))
                for n in names:
                    out.append(Fact(f"sub_{n}", f"the duplicate subscription {n}",
                                    f"You pay for {n} {c(comb)}.", words=(n,)))
                out.append(Fact("monthly_total", "their monthly total",
                                f"Together they cost {w.dollars(comb.value)} a month {c(comb)}.",
                                money=(comb.value,)))
            else:
                fee = next(x for x in leak.computed if x.label.startswith("fee "))
                out.append(Fact("fee", "the overdraft fee", f"Rent caused a {w.dollars(fee.value)} overdraft fee "
                                f"{c(fee)}.", money=(fee.value,), words=("fee",)))
    elif tool == "refund_status":
        k = f["finding"].computed
        reqs = [ds.row(i) for i in f["finding"].row_ids[("aid", "requirements")]]
        form = reqs[0].description.split(" (")[0] if reqs else "verification form"
        out += [Fact("refund_amount", "the refund amount", f"Your {w.dollars(k['refund_amount'].value)} refund "
                     f"{c(k['refund_amount'])} is on hold.", money=(k["refund_amount"].value,)),
                Fact("waiting_on", "what it's waiting on, by name",
                     f"Financial aid is waiting for your {form}.", words=("verification",)),
                Fact("arrives", "when it would arrive", f"Send it, and the refund arrives around "
                     f"{w.day(k['release_date'].value)} {c(k['release_date'])}.", date=k["release_date"].value)]
    elif tool == "cash_crunches":
        for i, fi in enumerate(f["findings"]):
            k = fi.computed
            out += [Fact(f"payment{i}", "the payment and its date",
                         f"A {w.dollars(k['installment'].value)} tuition payment {c(k['installment'])} is due "
                         f"{w.day(k['installment_due'].value)}.", money=(k["installment"].value,),
                         date=k["installment_due"].value),
                    Fact(f"paycheck{i}", "the small paycheck and its date",
                         f"Your {w.day(k['paycheck_date'].value)} paycheck is only "
                         f"{w.dollars(k['paycheck_net'].value)} {c(k['paycheck_net'])}.",
                         money=(k["paycheck_net"].value,), date=k["paycheck_date"].value)]
    for a in plan.assumptions:
        out.append(Fact("assumption", "the assumption", a, date=config.DEMO_TODAY + timedelta(days=1), where="note"))
    return out


def _fix_fact(fx, ds, scenario, c):
    if fx.kind == "refund":
        rel = engine.refund_release_date(ds, scenario)
        return Fact("fix_refund", "sending the verification form, the refund amount and when it arrives",
                    f"Send your verification form: your {w.dollars(fx.savings.value)} refund arrives around "
                    f"{w.day(rel)} {c(fx.savings)}.", money=(fx.savings.value,), date=rel)
    return Fact(f"fix_{fx.name}", f"cancelling {fx.name} and what it saves",
                f"Cancelling {fx.name} saves {w.dollars(fx.savings.value)} this semester {c(fx.savings)}.",
                money=(fx.savings.value,), words=(fx.name,))


def _has_money(text, value):
    target = abs(Decimal(value))
    return any(abs(v) == target or ("." not in written and abs(v) == _rounded(target))
               for written, v in find_amounts(text))


def fact_present(fact, text, sections=None):
    sec = sections or parse_sections(text) or {}
    if fact.where == "lead" and sec:
        text = " ".join([sec.get("answer", "")] + sec.get("why", [])[:1])
    elif fact.where == "note" and sec:
        text = sec.get("note", "")
    elif fact.where == "answer" and sec:
        text = sec.get("answer", "")
    low = text.lower()
    return (all(_has_money(text, m) for m in fact.money)
            and all(any(d == want for _, d, _ in find_dates(text))
                    for want in (fact.date if isinstance(fact.date, tuple) else (fact.date,) if fact.date else ()))
            and (not fact.words or any(x.lower() in low for x in fact.words)))


def missing_facts(text, facts):
    sec = parse_sections(text)
    return [f for f in facts if not fact_present(f, text, sec)]


def append_facts(text, missing):
    """Add a plain sentence for each missing fact: lead facts become the first WHY bullet, note facts go in NOTE,
    others are added as WHY bullets. Built from engine values only."""
    sec = parse_sections(text) or {"answer": text.strip(), "why": [], "do": [], "note": ""}
    lead = [f.line for f in missing if f.where == "lead"]
    rest = [f.line for f in missing if f.where in ("any", "answer")]
    notes = [f.line for f in missing if f.where == "note"]
    note = " ".join(x for x in [sec.get("note", "")] + notes if x)
    return _format(sec["answer"], lead + sec["why"] + rest, sec["do"], note)


def _strip_think(text, reasoning):
    if "</think>" in text:
        head, _, text = text.partition("</think>")
        reasoning = (reasoning + "\n" + head.replace("<think>", "")).strip()
    return text.strip(), reasoning


# ---------------------------------------------------------------------------------------
# ACTIONS (templates; drafts are never sent)
# ---------------------------------------------------------------------------------------
def actions_for(plan, result, ds, scenario):
    out, items = [], []
    refund = next((r for r in ds.refunds if r.status == "HELD"), None)
    wants_refund = refund and (plan.tool == "refund_status" or any(f.kind == "refund" for f in result.fixes))
    if wants_refund:
        reqs = [r for r in ds.requirements if r.status not in ("SATISFIED", "RECEIVED")]
        hold = next((h for h in ds.holds if "refund" in h.blocks.lower()), None)
        doc = reqs[0].description if reqs else "the missing document"
        term = w.term_name(refund.term)
        out.append(Action(
            "email-aid", "email", "Email to the financial aid office",
            to=hold.originator if hold else "Office of Student Financial Aid",
            subject=f"{doc} for {term}, {w.STUDENT_NAME}",
            body=(f"Hello,\n\nI'm {w.STUDENT_NAME} (student ID: [your student ID]). My {term} refund of "
                  f"{w.money(refund.amount)} is on hold because my file is missing the {doc}. I've attached the "
                  f"completed worksheet.\n\nCould you confirm you've received it, and let me know if anything else "
                  f"is needed to clear the hold and release my refund?\n\nThank you,\n{w.STUDENT_NAME}")))
        rel = engine.refund_release_date(ds, scenario if plan.tool != "what_if" else result.facts["new_scenario"])
        items.append(f"Send the {doc} to financial aid (refund arrives around {w.day(rel)}).")
    cancels = [f.name for f in result.fixes if f.kind == "cancel"]
    if plan.tool == "find_leaks":
        cancels += [x.value for leak in result.facts["leaks"] for x in leak.computed if x.label.startswith("which")]
    subs = {s.merchant: s for s in engine.subscriptions(ds)}
    for name in dict.fromkeys(cancels):
        nxt = next((c for c, _ in engine.subscription_timing(subs[name], ds) if c > config.DEMO_TODAY), None)
        items.append(f"Cancel {name}" + (f" before {w.day(nxt)}." if nxt else "."))
    new_shifts = result.facts["new_scenario"].extra_shifts if plan.tool == "what_if" else ()
    for s in (x for x in new_shifts if x not in scenario.extra_shifts):
        items.append(f"Ask your manager for the extra shift on {w.day(s.date)}.")
    if items:
        out.append(Action("checklist", "checklist", "Your to-do list", items=items))
    return out


# ---------------------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------------------
def normalize_question(q):
    return " ".join(re.sub(r"[^a-z0-9$.,\s]", " ", q.lower()).split()).rstrip(".,")


def cache_path(question, scenario):
    key = hashlib.sha256(f"{normalize_question(question)}|{scenario.describe()}".encode()).hexdigest()[:20]
    return config.ANSWER_CACHE_DIR / f"{key}.json"


def load_cached(question, scenario):
    path = cache_path(question, scenario)
    return Answer.from_json(path.read_text(encoding="utf-8")) if path.exists() else None


def save_cached(answer, scenario):
    path = cache_path(answer.question, scenario)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(answer.to_json(), encoding="utf-8")


# ---------------------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------------------
def _replay(answer, mode, typing_s):
    for stage in STAGES.values():
        yield "stage", stage
        time.sleep(typing_s * 10)
    for word in re.findall(r"\S+\s*", answer.text):
        yield "text", word
        time.sleep(typing_s)
    answer.mode = mode
    yield "answer", answer


def run(question, scenario=None, ds=None, mode=None, llm=None, typing_s=0.035):
    """Answer one question. Yields ("stage" | "text" | "restart" | "answer", payload); "answer" comes last."""
    scenario, ds = scenario or engine.Scenario(), ds or normalize.load()
    mode, llm = (mode or config.ANSWER_MODE).lower(), llm or llm_client
    question = question.strip()
    if mode in ("cached", "replay"):
        cached = load_cached(question, scenario)
        if cached and mode == "replay":
            yield from _replay(cached, "replay", typing_s)
            return
        if cached:
            cached.mode = "cached"
            yield "answer", cached
            return
    t0 = time.perf_counter()
    timings, retries, notes = {}, {"plan_json": 0, "explain_rewrite": 0, "facts_appended": 0}, []
    models = {"plan": config.NVIDIA_PLAN_MODEL, "explain": config.NVIDIA_EXPLAIN_MODEL}
    sub_names = [s.merchant for s in engine.subscriptions(ds)]

    # PLAN
    yield "stage", STAGES["plan"]
    t = time.perf_counter()
    plan = None
    if mode != "replay":
        try:
            res = llm.chat_json(plan_messages(question, scenario, sub_names), thinking=False,
                                validate=lambda d: parse_plan(d, sub_names), timeout=PLAN_TIMEOUT_S, retries=1)
            plan = ground_purchase_date(parse_plan(res.data, sub_names), question)
            retries["plan_json"] = res.json_retries + res.retries
        except Exception as exc:                                   # slow, down, or unusable: keywords
            notes.append(f"The planner wasn't available ({type(exc).__name__}); Runway matched your question "
                         "by keywords.")
    if plan is None:
        plan = keyword_plan(question, sub_names) or Plan("off_topic", None, {}, None, [], "keywords")
    timings["plan_s"] = round(time.perf_counter() - t, 2)

    facts_record = []

    def finish(text, verdict=None, label=None, pack=None, check=None, reasoning="", actions=(), fixes=(),
               ans_mode=None, source="none"):
        timings["total_s"] = round(time.perf_counter() - t0, 2)
        return Answer(question, text, verdict, label, asdict(plan), pack.to_dict() if pack else {"items": [],
                      "context": []}, asdict(check) if check else {}, reasoning, [asdict(a) for a in actions],
                      [{"kind": f.kind, "name": f.name} for f in fixes], ans_mode or mode, source, notes, timings,
                      retries, models, scenario.describe(), time.time(), parse_sections(text) or {},
                      facts_record)

    if plan.tool is None:
        text = plan.clarifying_question or OFF_TOPIC
        yield "text", text
        yield "answer", finish(text, ans_mode="off_topic")
        return

    # EXECUTE
    yield "stage", STAGES["execute"]
    t = time.perf_counter()
    yield "stage", STAGES["math"]
    result = execute(plan, scenario, ds)
    pack = build_pack(result, ds, plan, scenario)
    label = verdict_label(result)
    actions = actions_for(plan, result, ds, scenario)
    timings["execute_s"] = round(time.perf_counter() - t, 3)

    # EXPLAIN + CHECK: Super, then Lightning (thinking on), then a template. One rewrite per model at most.
    yield "stage", STAGES["explain"]
    t = time.perf_counter()
    required = required_facts(plan, result, pack, ds, scenario)
    messages = explain_messages(question, plan, result, pack, label, required)
    text, reasoning, check, source, answered_by, missing = "", "", None, "template", None, []
    errors = []
    if mode == "replay":
        errors.append("no recorded answer")                     # replay never calls the models
    else:
        for model in explain_chain():
            try:
                text, reasoning, check, missing = yield from _explain_with(llm, model, messages, pack, retries,
                                                                           required)
                source, answered_by = "llm", model
                break
            except Exception as exc:
                errors.append(f"{model_name(model)}: {type(exc).__name__}")
                yield "restart", ""
    if answered_by is None:
        text = template_answer(plan, result, pack, ds, scenario)
        missing = missing_facts(text, required)
    if missing:                                              # still missing after the rewrite: add them ourselves
        text = append_facts(text, missing)
        retries["facts_appended"] = len(missing)
        if answered_by is not None:
            yield "restart", ""
            yield "text", text
    if answered_by is None:
        check = check_answer(text, pack)
        notes.append("There's no recorded answer for this question, so this is a short summary built straight "
                     "from your numbers." if mode == "replay" else
                     f"The AI explanation isn't available right now ({'; '.join(errors)}), so this is a short "
                     "summary built straight from your numbers.")
        yield "text", text
    else:
        if errors:
            notes.append(f"{model_name(config.NVIDIA_EXPLAIN_MODEL)} wasn't available ({'; '.join(errors)}), so "
                         f"{model_name(answered_by)} wrote this answer.")
        if missing:
            check = check_answer(text, pack, require_format=True)
        if not check.ok:
            notes.append("Some numbers or dates in this answer couldn't be matched to your records: "
                         + "; ".join(check.problems))
    facts_record = [{"key": f.key, "label": f.label, "appended": f in missing} for f in required]
    models["answered_by"] = answered_by or "template"
    models["explain_errors"] = errors
    timings["explain_s"] = round(time.perf_counter() - t, 2)
    answer = finish(text, result.verdict, label, pack, check, reasoning, actions, result.fixes,
                    ans_mode="fallback" if source == "template" or plan.source == "keywords" else "live",
                    source=source)
    if answer.mode == "live" and check.ok:
        save_cached(answer, scenario)
    yield "answer", answer


def ask(question, scenario=None, **kwargs):
    """run() without the progress events: returns the Answer."""
    answer = None
    for kind, payload in run(question, scenario, **kwargs):
        if kind == "answer":
            answer = payload
    return answer
