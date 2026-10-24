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
from decimal import Decimal, InvalidOperation

import config
import engine
import llm_client
import normalize
import wording as w

PLAN_TIMEOUT_S = 120
EXPLAIN_TIMEOUT_S = 240
EXPLAIN_MAX_TOKENS = 8192        # the reasoning trace counts too; 4096 once left no room for the answer
CALENDAR = ["Thanksgiving is Thu Nov 26, 2026."]
MAX_PACK_CALCS = 24
MAX_ROWS_PER_SOURCE = 8
STAGES = {"plan": "Understanding your question...", "execute": "Checking your accounts...",
          "math": "Doing the math...", "explain": "Writing your answer..."}
SUGGESTED = ["Can I afford a $400 flight home for Thanksgiving if I book it Nov 10?", "How long will my money last?",
             "Where is my money leaking?"]
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
        "is spent, not when a trip happens; if the student gives none, leave \"date\" out. Questions that are "
        'not about the student\'s money get "intent": "off_topic", "tool": "none". Vague worries ("am I ok?") '
        "use runway.")
    return [{"role": "system", "content": system}, {"role": "user", "content": question}]


_AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)")
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"], start=1)}
_MDAY = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b", re.I)


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
        fixes = engine.available_fixes(scenario, ds, ledger)
        chosen = [f for f in fixes if (f.kind == "refund" and a["send_verification_form"])
                  or f.name in a["cancel_subscriptions"]]
        key += [f.savings for f in chosen]
        return ToolResult("covered" if after.lasts_through_semester else "runs_out", key, ledger, chosen,
                          [f for f in fixes if f.savings.value <= 0 and f.name in a["cancel_subscriptions"]],
                          {"projection": after, "before": before, "reason": r, "shift_pay": shift_pay,
                           "new_scenario": new})
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


def check_answer(text, pack):
    money, dates = allowed_values(pack)
    ids = {it["id"] for it in pack.items}
    problems = [] if text.strip() else ["the answer is empty"]
    amounts = find_amounts(text)
    for written, v in amounts:
        if abs(v) not in money:
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
    "You are Runway, a friendly money coach for a stressed college student. Write in plain, warm English.\n"
    "Rules:\n"
    "- 60 to 150 words. Start with the answer in one sentence. Then the reasons.\n"
    "- Use ONLY numbers and dates that appear in the facts below. Never calculate, round or invent a number "
    "or date.\n"
    "- Put a citation right after every number or date, like [C3] for a calculation or [E2] for a source record. "
    "Only cite ids that exist in the facts.\n"
    "- Write dates like \"Mon Nov 9\" and money like \"$1,850.00\".\n"
    "- If the facts list an assumption, say it plainly.\n"
    "- If cancelling a subscription is part of the answer and one of them saves $0.00, say why: its charges go "
    "on the credit card and that bill is paid after the semester ends.\n"
    "- No jargon: never say scenario, projection, ledger, evidence or computed.\n"
    "- End with one concrete next step.")


def explain_messages(question, plan, result, pack, verdict_label):
    facts = pack.prompt_text()
    head = f"Question: {question}\nWhat Runway checked: {plan_words(plan)}"
    if verdict_label:
        head += f"\nThe answer: {verdict_label}"
    return [{"role": "system", "content": EXPLAIN_SYSTEM},
            {"role": "user", "content": f"{head}\n\n{facts}\n\nWrite the answer now."}]


def plan_words(plan):
    a = plan.args
    if plan.tool == "can_afford":
        how = "debit card (checking)" if a["account"] == "checking" else "credit card"
        return f"can you afford {a['item']} for {w.money(Decimal(a['cost']))} on " \
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


def _fix_words(f, ds, scenario, pack):
    if f.kind == "refund":
        rel = engine.refund_release_date(ds, scenario)
        return (f"send your verification form to financial aid, so your {w.money(f.savings.value)} refund "
                f"arrives around {w.day(rel)} {pack.cite(f.savings)}")
    return f"cancel {f.name}, which saves {w.money(f.savings.value)} before the semester ends {pack.cite(f.savings)}"


def template_answer(plan, result, pack, ds, scenario):
    """A plain answer built only from the pack, with citations. Used when EXPLAIN is unavailable."""
    c, f = pack.cite, result.facts
    if plan.tool == "can_afford":
        r, p = f["result"], f["purchase"]
        base = r.without_fixes
        if r.verdict == "yes":
            text = (f"Yes, you can afford {p.label} {c(r.verdict_computed)}. Your lowest point would be "
                    f"{w.money(base.lowest.value)} {c(base.lowest)} on {w.day(base.lowest_date.value)} "
                    f"{c(base.lowest_date)}.")
        elif r.verdict == "no":
            text = (f"Not right now {c(r.verdict_computed)}. Even with every fix, your balance drops to "
                    f"{w.money(r.with_fixes.lowest.value)} {c(r.with_fixes.lowest)} on "
                    f"{w.day(r.with_fixes.lowest_date.value)} {c(r.with_fixes.lowest_date)}.")
        else:
            steps = "; and ".join(_fix_words(x, ds, scenario, pack) for x in r.fixes)
            text = (f"Yes, if you do {w.things(len(r.fixes))} {c(r.verdict_computed)}: {steps}. Then your lowest "
                    f"point would be {w.money(r.with_fixes.lowest.value)} {c(r.with_fixes.lowest)} on "
                    f"{w.day(r.with_fixes.lowest_date.value)} {c(r.with_fixes.lowest_date)}. Without them, you'd "
                    f"drop to {w.money(base.lowest.value)} {c(base.lowest)}.")
            for z in result.zero_fixes:
                text += (f" Cancelling {z.name} won't help: it's billed to your credit card, and that bill is paid "
                         f"after the semester, so it saves {w.money(z.savings.value)} {c(z.savings)} before then.")
        return text + " Next step: " + ("make those changes today." if r.verdict == "yes_if" else
                                        "check again if anything changes.")
    if plan.tool in ("runway", "what_if"):
        p, r = f["projection"], f["reason"]
        if p.lasts_through_semester:
            text = (f"You're covered through {w.day(config.SEMESTER_END)}. Your lowest point is "
                    f"{w.money(p.lowest.value)} {c(p.lowest)} on {w.day(p.lowest_date.value)} {c(p.lowest_date)}.")
        else:
            text = (f"Your money runs out {w.day(p.first_below_zero.value)} {c(p.first_below_zero)}, "
                    f"{w.weeks_words(p.runway_weeks.value)} from today {c(p.runway_weeks)}.")
            if r.event:
                text += (f" The {w.event_name(r.event)} of {w.money(-r.event.amount)} {c(r.event.computed)} "
                         f"that week is the biggest bill.")
        for _, pay in f.get("shift_pay", []):
            text += f" The extra shift adds {w.money(pay.value)} {c(pay)} to your pay."
        return text + " Next step: look at the ways to fix it in My semester."
    if plan.tool == "find_leaks":
        parts = []
        for leak in f["leaks"]:
            if leak.kind == "duplicate_subscriptions":
                comb = next(x for x in leak.computed if x.label.startswith("combined"))
                pick = next(x for x in leak.computed if x.label.startswith("which"))
                parts.append(f"You pay {w.money(comb.value)} a month {c(comb)} for two music apps; cancelling "
                             f"{pick.value} {c(pick)} helps most, saving {w.money(leak.savings.value)} "
                             f"{c(leak.savings)} this semester.")
            else:
                fee = next(x for x in leak.computed if x.label.startswith("fee "))
                parts.append(f"Rent caused a {w.money(fee.value)} overdraft fee {c(fee)}; staying above $0 could "
                             f"save about {w.money(leak.savings.value)} {c(leak.savings)} more (estimated).")
        return " ".join(parts) + " Next step: cancel the subscription you use less."
    if plan.tool == "refund_status":
        fi = f["finding"]
        k = fi.computed
        return (f"Your {w.money(k['refund_amount'].value)} refund {c(k['refund_amount'])} is on hold because "
                f"financial aid is waiting for your verification form. It's released "
                f"{k['release_rule_business_days'].value} business days {c(k['release_rule_business_days'])} after "
                f"the hold clears: around {w.day(k['release_date'].value)} {c(k['release_date'])} if you send it "
                f"{w.day(scenario.submit_date)}. Next step: send the form today.")
    if plan.tool == "cash_crunches":
        texts = []
        for fi in f["findings"]:
            k = fi.computed
            texts.append(f"A {w.money(k['installment'].value)} {c(k['installment'])} tuition payment is due "
                         f"{w.day(k['installment_due'].value)} {c(k['installment_due'])}, right after a "
                         f"{w.money(k['paycheck_net'].value)} {c(k['paycheck_net'])} paycheck.")
        return (" ".join(texts) or "No tight weeks ahead.") + " Next step: set that money aside now."
    return OFF_TOPIC


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
    timings, retries, notes = {}, {"plan_json": 0, "explain_rewrite": 0}, []
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
            plan = parse_plan(res.data, sub_names)
            retries["plan_json"] = res.json_retries + res.retries
        except Exception as exc:                                   # slow, down, or unusable: keywords
            notes.append(f"The planner wasn't available ({type(exc).__name__}); Runway matched your question "
                         "by keywords.")
    if plan is None:
        plan = keyword_plan(question, sub_names) or Plan("off_topic", None, {}, None, [], "keywords")
    timings["plan_s"] = round(time.perf_counter() - t, 2)

    def finish(text, verdict=None, label=None, pack=None, check=None, reasoning="", actions=(), fixes=(),
               ans_mode=None, source="none"):
        timings["total_s"] = round(time.perf_counter() - t0, 2)
        return Answer(question, text, verdict, label, asdict(plan), pack.to_dict() if pack else {"items": [],
                      "context": []}, asdict(check) if check else {}, reasoning, [asdict(a) for a in actions],
                      [{"kind": f.kind, "name": f.name} for f in fixes], ans_mode or mode, source, notes, timings,
                      retries, models, scenario.describe(), time.time())

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

    # EXPLAIN + CHECK (one rewrite at most)
    yield "stage", STAGES["explain"]
    t = time.perf_counter()
    messages = explain_messages(question, plan, result, pack, label)
    text, reasoning, check, source = "", "", None, "llm"
    try:
        if mode == "replay":
            raise LookupError("no recorded answer")            # replay never calls the models
        for attempt in range(2):
            stream = llm.stream_chat(messages, thinking=True, timeout=EXPLAIN_TIMEOUT_S, retries=1,
                                     max_tokens=EXPLAIN_MAX_TOKENS)
            for kind, chunk in stream:
                if kind == "text":
                    yield "text", chunk
            text, reasoning = _strip_think(stream.result.text, (reasoning + "\n" + stream.result.reasoning).strip())
            check = check_answer(text, pack)
            if check.ok or attempt == 1:
                break
            retries["explain_rewrite"] = 1
            yield "restart", "Double-checking the numbers..."
            messages = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": "These are not in the facts: " + "; ".join(check.problems) +
                 ". Rewrite the answer using only numbers, dates and ids from the facts."}]
        if not text:
            raise llm_client.LLMError("the model returned an empty answer twice")
        if not check.ok:
            notes.append("Some numbers or dates in this answer couldn't be matched to your records: "
                         + "; ".join(check.problems))
    except Exception as exc:
        source = "template"
        text = template_answer(plan, result, pack, ds, scenario)
        check = check_answer(text, pack)
        notes.append("There's no recorded answer for this question, so this is a short summary built straight "
                     "from your numbers." if mode == "replay" else
                     f"The AI explanation isn't available right now ({type(exc).__name__}), so this is a short "
                     "summary built straight from your numbers.")
        yield "restart", ""
        yield "text", text
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
