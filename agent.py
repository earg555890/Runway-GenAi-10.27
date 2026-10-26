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

Answers are saved by (question, what-ifs): live answers in config.ANSWER_CACHE_DIR, the committed demo
answers in config.DEMO_ANSWERS_DIR. config.ANSWER_MODE picks live / cached / replay (see config.py). With no
saved answer and no way to call the models (replay, or no NVIDIA key), the answer says so.
"""
import difflib
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import actions as todo
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
             "Where is my money leaking?", "Can I afford a $400 flight home for Thanksgiving?",
             "What should I do this week?"]
MYDATA_SUGGESTED = ["How long will my money last?", "Where is my money leaking?", "What should I do this week?",
                    "Where did my money go last month?"]
# Tools that need school data the student's own bank file doesn't have (My data mode): what each one needs.
NEEDS = {"refund_status": lambda ds: ds.refunds, "cash_crunches": lambda ds: ds.installments and ds.job,
         "work_summary": lambda ds: ds.job, "find_aid": lambda ds: ds.opportunities, "meal_plan": lambda ds: ds.meal_plan}
NOT_AVAILABLE = ("That needs your school data (financial aid, student account, work schedule or meal plan), which "
                 "isn't connected. Connect your school data to see this.")
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
        does="How long the money lasts (when it runs out), the lowest point, whether they are OK this semester "
             "(vague worries too).", args={}),
    "what_if": dict(
        does="What changes if the student makes changes: cancel subscriptions, add work shifts, send the "
             "verification form to financial aid.",
        args={"cancel_subscriptions": "list of subscription names", "extra_shifts": "list of {\"date\": "
              "\"YYYY-MM-DD\", \"hours\": number}", "send_verification_form": "true or false",
              "form_date": "YYYY-MM-DD when the form is sent (optional; default tomorrow)"}),
    "find_leaks": dict(does="Where money is leaking: duplicate subscriptions, fees.", args={}),
    "refund_status": dict(does="Why the financial aid refund is held, how much, and what releases it.", args={}),
    "cash_crunches": dict(does="Weeks where a bill lands right after a small paycheck.", args={}),
    "spending_summary": dict(
        does="How much was spent in a past period, by category (groceries, eating out...) or by merchant.",
        args={"start": "YYYY-MM-DD (default: the semester start)", "end": "YYYY-MM-DD (default: today)",
              "group_by": "\"category\" (default) or \"merchant\"",
              "account": "\"both\" (default), \"checking\" or \"card\""}),
    "find_transactions": dict(
        does="Find past transactions by merchant or keyword (\"Kroger\", \"Uber\", \"coffee\"): how many, how "
             "much, when the last one was.",
        args={"query": "merchant name or keyword", "start": "YYYY-MM-DD (optional)", "end": "YYYY-MM-DD (optional)",
              "account": "\"both\" (default), \"checking\" or \"card\"", "min_amount": "dollars (optional)",
              "max_amount": "dollars (optional)"}),
    "upcoming_bills": dict(
        does="Scheduled money out coming up (rent, card payments, tuition installments, subscriptions, bills).",
        args={"start": "YYYY-MM-DD (default: tomorrow)", "end": "YYYY-MM-DD (default: a week after start)"}),
    "work_summary": dict(
        does="Hours worked or scheduled at the job, and the pay, for a period.",
        args={"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}),
    "balance_on": dict(does="The checking balance on one date (past or future), with that day's payments.",
                       args={"date": "YYYY-MM-DD"}),
    "accounts_today": dict(does="Balances RIGHT NOW and what's pending today (not how long the money lasts): "
                                "checking, next card payment, the held refund, the next paycheck.", args={}),
    "money_ideas": dict(does="Ways to get money before the money runs out (extra shifts paid in time, the "
                             "refund, cancellations), ranked by when the money arrives.", args={}),
    "budget_status": dict(
        does="Her budget: how much is left in one category (\"food\" = groceries + eating out) or in the whole "
             "budget this month, the pace, and what sticking to it does to the forecast. Says so if no budget is set.",
        args={"category": "Groceries, Eating out, Meal plan, Shopping, Entertainment, Transportation, Other, or "
                          "\"food\"; leave it out for the whole budget",
              "month": "YYYY-MM (optional; default this month)"}),
    "find_aid": dict(
        does="Grants, scholarships, emergency money and work-study from her school that she may qualify for, and "
             "when the money would arrive IF APPROVED (never certain money).",
        args={"type": "\"emergency_grant\", \"scholarship\" or \"work_study\" (optional; leave out for all)"}),
    "search_scholarships": dict(
        does="Scholarships and emergency aid found ONLINE (not her school's list): titles, sites and links, with an "
             "amount or deadline only if the page says it. She must check each one before applying.", args={}),
    "meal_plan": dict(
        does="Her campus meal plan: swipes and dining dollars left, when the dining dollars run out, swipes left at "
             "the end of the semester, and how to make both last.", args={}),
    "action_plan": dict(
        does="What the student should DO (this week, first, next): the items that need attention, most urgent "
             "first, each with its next step.",
        args={"start": "YYYY-MM-DD (optional; default today)", "end": "YYYY-MM-DD (optional; default the semester "
              "end; \"this week\" = today plus 6 days)"}),
    "general_info": dict(does="A general money question NOT about the student's own data (\"What's a credit "
                              "score?\", \"What is FAFSA verification?\"). Never for questions about her money.",
                         args={"topic": "the question, in a few words"}),
}
INTENTS = ("afford", "runway", "what_if", "leaks", "refund", "crunch", "off_topic", *list(TOOLS)[6:])
MAX_CALLS = 3
DATA_START = None                      # config.DATA_START at call time (Maya: Jul 1, 2026; My data: her first day)


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
    calls: list = field(default_factory=list)          # [{"tool", "args"}], up to MAX_CALLS; [0] = tool/args
    resolved_question: str | None = None               # the question as answered, follow-ups resolved

    def __post_init__(self):
        if not self.calls and self.tool:
            self.calls = [{"tool": self.tool, "args": self.args}]


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
    quick: str = ""              # the instant answer built from the engine (shown before the AI answer)
    think: bool = False          # answered in "Think harder" mode (Super, thinking on)

    def to_json(self):
        return json.dumps(asdict(self), default=str)

    @staticmethod
    def from_json(s):
        return Answer(**json.loads(s))


def event_answer(text):
    """A message from Runway that isn't an answer to a question (e.g. after the student marks something done).
    Built from the engine; no model call. mode "event": the chat shows it, PLAN never sees it."""
    return Answer("", text, None, None, asdict(Plan("event", None, {}, source="none")), {"items": [], "context": []},
                  {}, "", [], [], "event", "none", [], {}, {}, {}, "", time.time())


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


def _any_date(x, what, earliest=None):
    """A date in Maya's data range (history or the rest of the semester)."""
    earliest = earliest or config.DATA_START
    try:
        d = date.fromisoformat(str(x))
    except ValueError:
        raise ValueError(f"{what} must be YYYY-MM-DD, got {x!r}") from None
    if not earliest <= d <= config.SEMESTER_END:
        raise ValueError(f"{what} {d} is outside {earliest} to {config.SEMESTER_END}")
    return d


def _choice(x, what, allowed, default):
    x = x or default
    if x not in allowed:
        raise ValueError(f"{what} must be one of {list(allowed)}, got {x!r}")
    return x


def _amount_or_none(x, what):
    return None if x in (None, "") else str(_money(x, what))


def validate_call(tool, args, sub_names):
    """(clean args, assumptions) for one tool call. Raises ValueError with a message the model can fix."""
    if tool not in TOOLS:
        raise ValueError(f"unknown tool {tool!r}; use one of {sorted(TOOLS)}")
    args = args or {}
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
        clean["account"] = _choice(args.get("account"), "account", ("checking", "card"), "checking")
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
        for sh in args.get("extra_shifts") or []:
            if not isinstance(sh, dict):
                raise ValueError('each extra shift must be {"date": "YYYY-MM-DD", "hours": number}')
            hours = _money(sh.get("hours"), "hours")
            if hours > 12:
                raise ValueError(f"a shift can't be {hours} hours")
            shifts.append({"date": _semester_date(sh.get("date"), "shift date").isoformat(), "hours": str(hours)})
        send = bool(args.get("send_verification_form")) or bool(args.get("form_date"))
        form_date = _semester_date(args["form_date"], "form_date") if args.get("form_date") else tomorrow
        if not (cancels or shifts or send):
            raise ValueError("what_if needs at least one change (cancel_subscriptions, extra_shifts or "
                             "send_verification_form)")
        clean = {"cancel_subscriptions": cancels, "extra_shifts": shifts, "send_verification_form": send,
                 "form_date": form_date.isoformat()}
    elif tool in ("spending_summary", "find_transactions"):
        default_start = config.SEMESTER_START if tool == "spending_summary" else None
        start = _any_date(args["start"], "start") if args.get("start") else default_start
        end = _any_date(args["end"], "end") if args.get("end") else config.DEMO_TODAY
        if start and start > config.DEMO_TODAY:
            raise ValueError(f"{tool} looks at past transactions; start {start} is after today "
                             f"({config.DEMO_TODAY}). Use upcoming_bills for future payments.")
        if start and end < start:
            raise ValueError(f"end {end} is before start {start}")
        clean = {"start": start.isoformat() if start else None, "end": min(end, config.DEMO_TODAY).isoformat(),
                 "account": _choice(args.get("account"), "account", ("both", "checking", "card"), "both")}
        if tool == "spending_summary":
            clean["group_by"] = _choice(args.get("group_by"), "group_by", ("category", "merchant"), "category")
        else:
            clean["query"] = str(args.get("query") or "").strip()[:40]
            clean["min_amount"] = _amount_or_none(args.get("min_amount"), "min_amount")
            clean["max_amount"] = _amount_or_none(args.get("max_amount"), "max_amount")
            if not (clean["query"] or clean["min_amount"] or clean["max_amount"]):
                raise ValueError("find_transactions needs a query (merchant or keyword) or an amount range")
    elif tool == "upcoming_bills":
        start = max(_any_date(args["start"], "start"), tomorrow) if args.get("start") else tomorrow   # "from today"
        end = _semester_date(args["end"], "end") if args.get("end") else min(start + timedelta(days=6),
                                                                           config.SEMESTER_END)
        if end < start:
            raise ValueError(f"end {end} is before start {start}")
        clean = {"start": start.isoformat(), "end": end.isoformat()}
    elif tool == "work_summary":
        start = _any_date(args["start"], "start") if args.get("start") else config.DEMO_TODAY.replace(day=1)
        end = _any_date(args["end"], "end") if args.get("end") else config.SEMESTER_END
        if end < start:
            raise ValueError(f"end {end} is before start {start}")
        clean = {"start": start.isoformat(), "end": end.isoformat()}
    elif tool == "balance_on":
        if not args.get("date"):
            raise ValueError('balance_on needs "date"')
        clean = {"date": _any_date(args["date"], "date", config.SEMESTER_START).isoformat()}
    elif tool == "find_aid":
        kind = str(args.get("type") or "").strip().lower() or None
        kind = None if kind in ("all", "any", "both", "grant_or_scholarship") else kind      # seen live: "all"
        if kind and kind not in ("emergency_grant", "scholarship", "work_study"):
            raise ValueError(f"type must be emergency_grant, scholarship or work_study, got {kind!r}")
        clean = {"type": kind}
    elif tool == "budget_status":
        cat = str(args.get("category") or "").strip()
        names = {c.lower(): c for c in (*normalize.FLEXIBLE, *engine.BUDGET_GROUPS)}
        if cat and cat.lower() not in names:
            raise ValueError(f"unknown budget category {cat!r}; use one of {sorted(names.values())} or leave it out")
        month = str(args.get("month") or f"{config.DEMO_TODAY:%Y-%m}")
        if not re.fullmatch(r"2026-(0[89]|1[0-2])", month):
            raise ValueError(f"month must be YYYY-MM between 2026-08 and 2026-12, got {month!r}")
        clean = {"category": names.get(cat.lower()) if cat else None, "month": month}
    elif tool == "action_plan":
        start = max(_any_date(args["start"], "start"), config.DEMO_TODAY) if args.get("start") else config.DEMO_TODAY
        end = min(_any_date(args["end"], "end"), config.SEMESTER_END) if args.get("end") else config.SEMESTER_END
        if end < start:
            raise ValueError(f"end {end} is before start {start}")
        clean = {"start": start.isoformat(), "end": end.isoformat()}
    elif tool == "general_info":
        clean = {"topic": str(args.get("topic") or "").strip()[:80]}
    return clean, assumptions


def parse_plan(data, sub_names):
    """Strictly validate the PLAN model's JSON: {"resolved_question", "calls": [{"tool", "args"}, ...up to 3],
    "clarifying_question"} (the older one-tool shape {"intent", "tool", "args"} is accepted too). Raises
    ValueError with a message the model can fix."""
    if not isinstance(data, dict):
        raise ValueError("the reply must be one JSON object")
    intent, clarifying = data.get("intent"), data.get("clarifying_question") or None
    resolved = (str(data.get("resolved_question") or "").strip() or None)
    calls = data.get("calls")
    if calls is None:
        calls = [] if data.get("tool") in (None, "", "none") else [{"tool": data.get("tool"),
                                                                    "args": data.get("args") or {}}]
    if not isinstance(calls, list):
        raise ValueError('"calls" must be a list of {"tool": ..., "args": {...}}')
    calls = [c for c in calls if isinstance(c, dict) and c.get("tool") not in (None, "", "none")]
    if not calls:
        if intent != "off_topic" and not clarifying:
            raise ValueError('give at least one call with a "tool" unless "intent" is "off_topic" or you ask a '
                             'clarifying_question')
        return Plan(intent or "off_topic", None, {}, clarifying, resolved_question=resolved)
    if len(calls) > MAX_CALLS:
        raise ValueError(f"at most {MAX_CALLS} calls, got {len(calls)}")
    clean, assumptions = [], []
    for c in calls:
        args, assumed = validate_call(c.get("tool"), c.get("args"), sub_names)
        if not any(x["tool"] == c["tool"] and x["args"] == args for x in clean):
            clean.append({"tool": c["tool"], "args": args})
            assumptions += [a for a in assumed if a not in assumptions]
    first = clean[0]
    return Plan(intent if intent in INTENTS else first["tool"], first["tool"], first["args"], clarifying, assumptions,
                calls=clean, resolved_question=resolved)


def _turn_summary(a):
    sec = a.sections or {}
    said = sec.get("answer") or a.text.split("\n")[0]
    return (f"Student: {a.question}\nRunway checked: {plan_words(Plan(**a.plan))}\n"
            f"Runway answered: {strip_citations(said)[:200]}")


def plan_messages(question, scenario, sub_names, history=()):
    tools = "\n".join(f"- {name}: {t['does']}" + ("".join(f"\n    {a}: {d}" for a, d in t["args"].items()))
                      for name, t in TOOLS.items())
    recent = ""
    if history:
        recent = ("\nRecent conversation (oldest first). Resolve follow-ups like \"what about Nov 17 instead?\", "
                  "\"why?\" or \"and if I also cancel Apple Music?\" against it:\n"
                  + "\n\n".join(_turn_summary(a) for a in history[-3:]) + "\n")
    system = (
        "You are the planner for Runway, a money app for one college student. Pick the tool(s) for the student's "
        "question and their arguments. You never do math and never answer the question yourself.\n"
        f"Today is {w.day(config.DEMO_TODAY)}, {config.DEMO_TODAY.isoformat()}. The semester ends "
        f"{w.day(config.SEMESTER_END)}, {config.SEMESTER_END.isoformat()}. Calendar: {' '.join(CALENDAR)}\n"
        f"The student's subscriptions: {', '.join(sub_names)}.\n"
        f"The student's current what-ifs: {scenario.describe()}.\n{recent}\nTools:\n{tools}\n\n"
        "Reply with JSON only, exactly this shape:\n"
        '{"resolved_question": "the full question you are answering, follow-ups written out", '
        '"intent": one of ' + json.dumps(list(INTENTS)) + ', '
        '"calls": [{"tool": a tool name, "args": {...}}], "clarifying_question": null}\n'
        "Rules: use ONE call for a specific question. Never add a call the student didn't ask about. A broad "
        "request for help or a plan (\"help me get through the semester\", \"make me a plan\") "
        f"uses runway, money_ideas and find_leaks ({MAX_CALLS} calls). Dates are YYYY-MM-DD. "
        "A purchase date is when the money is spent, not when a trip happens (\"a flight home for Thanksgiving\" "
        "gives NO purchase date); if the student gives none, leave \"date\" out. \"This month\" is October 2026; "
        "\"next week\" is the 7 days after today. Questions not about money get \"intent\": \"off_topic\" and no "
        "calls. resolved_question: the student's question written out in full, in their words (for a follow-up, "
        "fill in what it refers to); nothing else.\n"
        "Vague worries (\"am I ok?\", \"money is stressing me out\") use runway.\n"
        "Examples (question -> calls):\n"
        '- How long will my money last? / Am I ok? / Money stuff is stressing me out -> [{"tool": "runway"}]\n'
        '- What\'s my balance right now? / What\'s pending? -> [{"tool": "accounts_today"}]\n'
        '- Can I afford a $60 jacket on Nov 20? -> [{"tool": "can_afford", "args": {"item": "jacket", "cost": 60, '
        '"date": "2026-11-20"}}]\n'
        '- What if I cancel Spotify? -> [{"tool": "what_if", "args": {"cancel_subscriptions": ["Spotify"]}}]\n'
        '- What if I work 4 hours this Saturday and next Saturday? (today Mon Oct 26) -> [{"tool": "what_if", '
        '"args": {"extra_shifts": [{"date": "2026-10-31", "hours": 4}, {"date": "2026-11-07", '
        '"hours": 4}]}}]\n'
        '- What if I pick up a 4 hour shift on Nov 12? -> [{"tool": "what_if", "args": {"extra_shifts": '
        '[{"date": "2026-11-12", "hours": 4}]}}]\n'
        '- How much did I spend on food in October? -> [{"tool": "spending_summary", "args": {"start": '
        '"2026-10-01", "end": "2026-10-31"}}]\n'
        '- How much did I spend at Kroger? -> [{"tool": "find_transactions", "args": {"query": "Kroger"}}]\n'
        '- What bills are due next week? -> [{"tool": "upcoming_bills"}]\n'
        '- Is there a week where money gets tight? -> [{"tool": "cash_crunches"}]\n'
        '- How many hours did I work in October? -> [{"tool": "work_summary", "args": {"start": "2026-10-01", '
        '"end": "2026-10-31"}}]\n'
        '- What will my balance be on Thanksgiving? -> [{"tool": "balance_on", "args": {"date": "2026-11-26"}}]\n'
        '- What can I do to get money before I run out? -> [{"tool": "money_ideas"}]\n'
        '- Where is my money leaking? -> [{"tool": "find_leaks"}]\n'
        f'- What should I do this week? -> [{{"tool": "action_plan", "args": {{"start": "{config.DEMO_TODAY}", '
        f'"end": "{config.DEMO_TODAY + timedelta(days=6)}"}}}}]\n'
        '- What should I do first? / What do I need to do? -> [{"tool": "action_plan"}]\n'
        '- Where did my money go in October? -> [{"tool": "spending_summary", "args": {"start": "2026-10-01", '
        '"end": "2026-10-31"}}]\n'
        '- How much is left in my food budget? -> [{"tool": "budget_status", "args": {"category": "food"}}]\n'
        '- Are there any grants or scholarships I qualify for? -> [{"tool": "find_aid"}]\n'
        '- Is there emergency money? -> [{"tool": "find_aid", "args": {"type": "emergency_grant"}}]\n'
        '- Will my dining dollars last? / How many swipes do I have left? -> [{"tool": "meal_plan"}]\n'
        '- Find me scholarships online -> [{"tool": "search_scholarships"}]\n'
        '- What happens if I stick to my budget? / Am I on budget? -> [{"tool": "budget_status"}]\n'
        '- Help me get through the semester -> [{"tool": "runway"}, {"tool": "money_ideas"}, {"tool": '
        '"find_leaks"}]\n'
        '- What is a credit score? / What is FAFSA verification? -> [{"tool": "general_info", "args": {"topic": '
        '"credit score"}}]\n'
        '- After "Can I afford a $400 flight if I book it Nov 10?", "what about Nov 17 instead?" -> '
        '[{"tool": "can_afford", "args": {"item": "flight home", "cost": 400, "date": "2026-11-17"}}]')
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


BROAD_RE = re.compile(r"\b(?:get through|make (?:me )?a plan|help me (?:out|with my money|survive)|"
                      r"survive (?:the|this) semester|help me (?:get|make it))\b", re.I)
BROAD_CALLS = ("runway", "money_ideas", "find_leaks")


def widen_broad_plan(plan, question):
    """A broad request for help ("Help me get through the semester") needs the whole picture: when PLAN picked
    just one overview tool, or none at all (it once called it off-topic), use all three (rule-based; still one
    PLAN call)."""
    tools = [c["tool"] for c in plan.calls]
    if BROAD_RE.search(question) and (not tools or len(tools) == 1 and tools[0] in BROAD_CALLS + ("accounts_today",)):
        plan.calls = [{"tool": t, "args": {}} for t in BROAD_CALLS]
        plan.tool, plan.args = plan.calls[0]["tool"], plan.calls[0]["args"]
        if plan.intent == "off_topic":
            plan.intent = plan.tool
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
    elif "get through" in q or "help me" in q and "semester" in q:
        p = Plan("runway", "runway", {}, calls=[{"tool": t, "args": {}} for t in ("runway", "money_ideas", "find_leaks")])
    elif "shift" in q and re.search(r"(\d+(?:\.\d)?)[\s-]*h(?:ou)?r", q) and _MDAY.search(question):
        m, hours = _MDAY.search(question), re.search(r"(\d+(?:\.\d)?)[\s-]*h(?:ou)?r", q).group(1)
        day = date(2026, _MONTHS[m.group(1).lower()[:3]], int(m.group(2))).isoformat()
        try:
            p = Plan("what_if", "what_if", validate_call("what_if", {"extra_shifts": [{"date": day, "hours": hours}]},
                                                         sub_names)[0])
        except ValueError:
            return None
    elif "online" in q and any(k in q for k in ("scholarship", "grant", "aid")):
        p = Plan("search_scholarships", "search_scholarships", {})
    elif any(k in q for k in ("grant", "scholarship", "emergency money", "work-study", "work study", "financial help")):
        args = {"type": "emergency_grant"} if "emergency" in q else {}
        p = Plan("find_aid", "find_aid", validate_call("find_aid", args, sub_names)[0])
    elif any(k in q for k in ("dining", "swipe", "meal plan")):
        p = Plan("meal_plan", "meal_plan", {})
    elif "budget" in q:
        cat = next((c for c in (*engine.BUDGET_GROUPS, *normalize.FLEXIBLE) if c.lower() in q), None)
        p = Plan("budget_status", "budget_status", validate_call("budget_status", {"category": cat}, sub_names)[0])
    elif "should i do" in q or "need to do" in q or "to-do" in q or "todo" in q:
        args = {"end": (config.DEMO_TODAY + timedelta(days=6)).isoformat()} if "week" in q else {}
        p = Plan("action_plan", "action_plan", validate_call("action_plan", args, sub_names)[0])
    elif any(k in q for k in ("make money", "get money", "earn", "more money")):
        p = Plan("money_ideas", "money_ideas", {})
    elif any(k in q for k in ("how long", "last", "run out", "runway", "am i ok", "okay")):
        p = Plan("runway", "runway", {})
    elif "spend at" in q or "spent at" in q:
        place = re.split(r"spen[dt] at\s+", q, maxsplit=1)[1].split("?")[0].split(" in ")[0].strip(" .")
        p = Plan("find_transactions", "find_transactions", validate_call("find_transactions", {"query": place},
                                                                          sub_names)[0])
    elif "spend" in q or "spent" in q:
        month = "october" in q or "this month" in q
        args = {"start": "2026-10-01", "end": "2026-10-31"} if month else {}
        p = Plan("spending_summary", "spending_summary", validate_call("spending_summary", args, sub_names)[0])
    elif "bill" in q or " due" in q:
        p = Plan("upcoming_bills", "upcoming_bills", validate_call("upcoming_bills", {}, sub_names)[0])
    elif "hours" in q or "worked" in q:
        args = {"start": "2026-10-01", "end": "2026-10-31"} if "october" in q or "this month" in q else {}
        p = Plan("work_summary", "work_summary", validate_call("work_summary", args, sub_names)[0])
    elif "balance" in q and "thanksgiving" in q:
        p = Plan("balance_on", "balance_on", {"date": "2026-11-26"})
    elif "balance" in q or "pending" in q:
        p = Plan("accounts_today", "accounts_today", {})
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
    tool: str | None = None
    args: dict = field(default_factory=dict)


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
        key.append(ledger.add("balance at the end of the day of that payment", p.balance_on(r.event.date), "USD",
                              f"End-of-day checking balance on {w.day(r.event.date)}, after the payment.",
                              [p.lowest]))
    return key, r


def execute(plan, scenario, ds):
    """The first call of the plan (the one-tool path)."""
    return execute_all(plan, scenario, ds)[0]


def execute_all(plan, scenario, ds, done=(), budget=None):
    """Every call of the plan, in order. Each ToolResult remembers its tool and args."""
    out = []
    for c in plan.calls:
        r = execute_call(c["tool"], c["args"], scenario, ds, done, budget)
        r.tool, r.args = c["tool"], c["args"]
        out.append(r)
    return out


def execute_call(tool, a, scenario, ds, done=(), budget=None):
    """One tool call. done: check-in item kinds the student marked done (action_plan leaves them out). budget:
    {category: monthly dollars} she set in the Budget tab (budget_status)."""
    ledger = engine.Ledger()
    if tool in NEEDS and not NEEDS[tool](ds):         # My data mode: no school data for this tool
        return ToolResult(None, [], ledger, facts={"unavailable": True})
    if tool == "can_afford":
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
    if tool == "runway":
        p = engine.project(scenario, ds, ledger)
        key, r = _projection_key(p, ledger)
        return ToolResult("covered" if p.lasts_through_semester else "runs_out", key, ledger,
                          facts={"projection": p, "reason": r})
    if tool == "what_if":
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
        plan_ = None
        if len(shift_pay) > 1:                 # several shifts: amounts that add up, the total, days longer
            plan_ = engine.shift_plan(new.extra_shifts, new, ds, ledger)
            shift_pay = [(p.pay_date, p.added) for p in plan_.shifts]
            key += [plan_.total] + ([plan_.days_longer] if plan_.days_longer else [])
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
                           "new_scenario": new, "latest_shift": latest, "shift_plan": plan_})
    if tool == "find_leaks":
        leaks = engine.find_leaks(scenario, ds, ledger)
        key = [c for leak in leaks for c in leak.computed]
        return ToolResult(None, key, ledger, facts={"leaks": leaks})
    if tool == "refund_status":
        f = engine.refund_status(scenario, ds, ledger)
        return ToolResult(None, list(f.computed.values()) if f else [], ledger, facts={"finding": f})
    if tool == "cash_crunches":
        found = engine.cash_crunches(scenario, ds, ledger)
        return ToolResult(None, [c for f in found for c in f.computed.values()], ledger, facts={"findings": found})
    if tool == "spending_summary":
        sp = engine.spending_summary(a["start"], a["end"], a["group_by"], a["account"], ds, ledger)
        return ToolResult(None, [sp.total, *(c for _, c, _ in sp.groups)], ledger, facts={"spending": sp})
    if tool == "find_transactions":
        m = engine.find_transactions(a["query"], a["start"], a["end"], a["account"], a["min_amount"], a["max_amount"],
                                     ds, ledger)
        key = [m.count, m.spent, m.received, m.last]
        return ToolResult(None, [c for c in key if c is not None], ledger, facts={"matches": m})
    if tool == "upcoming_bills":
        b = engine.upcoming_bills(a["start"], a["end"], scenario, ds, ledger)
        return ToolResult(None, [b.total, *(e.computed for e in b.events), b.balance_after], ledger,
                          facts={"bills": b})
    if tool == "work_summary":
        wk = engine.work_summary(a["start"], a["end"], scenario, ds, ledger)
        key = [wk.worked_hours, wk.scheduled_hours, wk.pay_total, *(c for _, n, d in wk.periods for c in (n, d))]
        return ToolResult(None, key, ledger, facts={"work": wk})
    if tool == "balance_on":
        b = engine.balance_on(a["date"], scenario, ds, ledger)
        evs = [e.computed for e in b.events if hasattr(e, "computed")]
        return ToolResult(None, [b.balance, *evs], ledger, facts={"day": b})
    if tool == "accounts_today":
        t = engine.accounts_today(scenario, ds, ledger)
        key = [t.checking, t.next_card_payment.computed if t.next_card_payment else None, t.refund, t.refund_release,
               t.next_paycheck.computed if t.next_paycheck else None, t.next_paycheck_date]
        return ToolResult(None, [c for c in key if c is not None], ledger, facts={"today": t})
    if tool == "money_ideas":
        ideas, deadline, p = engine.money_ideas(scenario, ds, ledger)
        key = [deadline] + [c for i in ideas for c in (i.amount, i.arrives, i.detail) if c is not None]
        return ToolResult("covered" if p.lasts_through_semester else "runs_out", key, ledger,
                          facts={"ideas": ideas, "deadline": deadline, "projection": p})
    if tool == "find_aid":
        checks = engine.eligible_opportunities(None, scenario, ds, ledger)
        if a.get("type"):
            checks = [x for x in checks if x.opp.type == a["type"]]
        total = engine.opportunities_total(checks, ledger)
        run_out = engine.project(scenario, ds, ledger).first_below_zero
        # only what she qualifies for: an "almost" award's amount and date stay out, so no answer can offer it
        key = [total, run_out] + [c for x in checks if x.status == "eligible"
                                  for c in (x.amount, x.arrives, x.this_semester) if c is not None]
        return ToolResult(None, key, ledger, facts={"checks": checks, "total": total, "run_out": run_out})
    if tool == "search_scholarships":
        import websearch
        found = websearch.get(ds.profile, None, live=config.ANSWER_MODE.lower() != "replay") or {}
        rows, key = [], []
        for r in (found.get("results") or [])[:5]:
            amount = deadline = None
            if r["amount"] != websearch.SEE:
                amount = ledger.add(f"amount stated on {r['url']}", engine.D(re.sub(r"[^0-9.]", "", r["amount"])), "USD",
                                    f"Written on the page: \"{r['amount']}\". Not checked by Runway.", [])
            parsed = find_dates(r["deadline"]) if r["deadline"] != websearch.SEE else []
            if parsed and parsed[0][1]:
                deadline = ledger.add(f"deadline stated on {r['url']}", parsed[0][1], "date",
                                      f"Written on the page: \"{r['deadline']}\".", [])
            rows.append((r, amount, deadline))
            key += [c for c in (amount, deadline) if c]
        when = None
        if found.get("found_at"):
            when = ledger.add("searched online on", date.fromisoformat(found["found_at"][:10]), "date",
                              f"{found.get('provider', 'web search')}.", [])
            key.append(when)
        return ToolResult(None, key, ledger, facts={"web": rows, "found_at": when})
    if tool == "meal_plan":
        m = engine.meal_plan_status(scenario, ds, ledger)
        return ToolResult(None, [*m.c.values(), *m.tip.values()] if m else [], ledger, facts={"meal": m})
    if tool == "budget_status":
        b = engine.budget_status(budget, a["month"], a.get("category"), scenario, ds, ledger)
        if b.suggestion:
            sg = b.suggestion
            key = [sg.available.amount, sg.total, *(x.suggested for x in sg.lines), sg.available.money_in,
                   sg.available.fixed]
        else:
            e = b.effect
            key = [b.left, b.spent, b.budget, *([b.one_offs] if b.one_offs else []),
                   *(x for r in b.rows for x in (r.spent, r.left)), e.days_longer,
                   e.with_budget.first_below_zero, e.without.first_below_zero, e.lowest_change, e.end_change,
                   e.with_budget.lowest, e.with_budget.lowest_date]
        return ToolResult(None, key, ledger, facts={"status": b})
    if tool == "action_plan":
        start, end = date.fromisoformat(a["start"]), date.fromisoformat(a["end"])
        every = [it for it in engine.attention_items(scenario, ds, ledger) if it.kind not in done]
        items = [it for it in every if start <= it.due.value <= end]
        span = (ledger.add("from", start, "date", "Start of the period asked about.", []),
                ledger.add("to", end, "date", "End of the period asked about.", []))
        key = [c for it in items[:3] for c in (it.due, *it.facts.values(), it.urgency)] + list(span)
        nxt = next((it for it in every if it.due.value > end), None)
        if not items and nxt:
            key += [nxt.due, *nxt.facts.values()]
        return ToolResult(None, key, ledger, facts={"items": items, "span": span, "next": None if items else nxt})
    if tool == "general_info":
        return ToolResult(None, [], ledger, facts={"topic": a.get("topic", "")})
    raise ValueError(f"unknown tool {tool!r}")


# ---------------------------------------------------------------------------------------
# Evidence pack
# ---------------------------------------------------------------------------------------
class Pack:
    def __init__(self, items, context, cite_ids):
        self.items, self.context, self.cite_ids = items, context, cite_ids      # id(Computed) -> "C3"

    def cite(self, computed):
        return f"[{self.cite_ids[id(computed)]}]" if computed is not None and id(computed) in self.cite_ids else ""

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


def build_pack(results, ds, plan, scenario):
    """The calculations the answer depends on (each result's key records + their inputs, two levels deep), and
    the source rows behind them, grouped by the query that returned them. Several results (a multi-step plan)
    share one numbering: C1.. and E1.."""
    results = results if isinstance(results, list) else [results]
    order, seen = [], set()                  # [(ledger, cid)]
    for r in results:
        queue = [(c.id, 0) for c in r.key if c is not None]
        budget = MAX_PACK_CALCS if len(results) == 1 else max(8, MAX_PACK_CALCS // len(results) + 4)
        taken = 0
        while queue and taken < budget:
            cid, d = queue.pop(0)
            if (id(r.ledger), cid) in seen:
                continue
            seen.add((id(r.ledger), cid))
            order.append((r.ledger, cid))
            taken += 1
            if d < 2:
                queue += [(i, d + 1) for i in r.ledger.get(cid).inputs if re.match(r"^C\d+$", i)]
    pack_id = {(id(lg), cid): f"C{n}" for n, (lg, cid) in enumerate(order, start=1)}
    items, row_ids, cite_ids = [], [], {}
    for lg, cid in order:
        c = lg.get(cid)
        cite_ids[id(c)] = pack_id[(id(lg), cid)]
        items.append({"id": pack_id[(id(lg), cid)], "kind": "calc", "title": c.label, "value": w.value(c),
                      "raw": str(c.value), "unit": c.unit, "how": c.how,
                      "uses": [pack_id.get((id(lg), i), i) for i in c.inputs
                               if not re.match(r"^C\d+$", i) or (id(lg), i) in pack_id]})
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
               *([f"The student's current what-ifs: {scenario.describe()}."] if scenario.describe() != "nothing changes"
                 else []), *plan.assumptions]
    return Pack(items, context, cite_ids)


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


def strip_citations(text):
    return re.sub(r"\s*" + CITE_RE.pattern, "", text)


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
        year = int(m.group(4)) if m.group(4) else (2026 if month >= 7 else 2027)     # data: Jul 2026 to Jan 2027
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


def unflatten(text):
    """A one-line answer ("ANSWER: ... WHY: - a. - b. DO THIS: 1. x. NOTE: ...", which the fast model sometimes
    writes) back on separate lines, words unchanged. Text that already has line breaks is returned as is."""
    t = text.strip()
    if "\n" in t or not SECTION_HEAD.match(t) or not re.search(r"\sWHY\s*:", t):
        return text
    out = []
    for line in re.split(r"\s+(?=(?:WHY|DO THIS|NOTE)\s*:)", t):
        head = SECTION_HEAD.match(line)
        name = head.group(1).upper() if head else ""
        if name in ("WHY", "DO THIS") and head.group(2).strip():
            items = re.split(r"(?<=[.!?\]])\s+(?=-\s)" if name == "WHY" else r"(?<=[.!?\]])\s+(?=\d+[.)]\s)",
                             head.group(2).strip())       # a new item only after a finished sentence
            out += [f"{name}:"] + [x.strip() for x in items if x.strip()]
        else:
            out.append(line.strip())
    return "\n".join(out)


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


def merchant_accounts(ds):
    """{merchant name as a student would write it: accounts it charges} for every named merchant (not fees,
    transfers or income). "Greenway Property Mgmt (rent)" -> "Greenway Property Mgmt"."""
    out = {}
    for t in ds.checking_txns + ds.card_txns:
        if t.amount < 0 and t.category not in ("fee", "card_payment", "income"):
            out.setdefault(re.sub(r"\s*\(.*\)", "", t.merchant).strip(), set()).add(t.account)
    return out


def private_amounts(ds):
    """Every dollar amount in Maya's data (for the general-info rule: never state her numbers)."""
    vals = {abs(t.amount) for t in ds.checking_txns + ds.card_txns}
    vals |= {abs(r.amount) for r in ds.refunds} | {abs(ds.checking_account.current_balance)}
    vals |= {abs(p.net) for p in ds.pay_periods if p.net} | {abs(i.amount) for i in ds.installments}
    return {v for v in vals if v >= 1}


CARD_CLAIM = re.compile(r"\b(?:charged|billed|charges?|bills?|goes|go|is|are|lands?)\s+(?:to|on)\s+(?:your\s+|the\s+|her\s+)?"
                        r"(?:credit\s+)?card\b|\bcard\s+(?:bill|charges?)\b|\bon\s+(?:your\s+|the\s+)?credit\s+card\b",
                        re.I)
CHECKING_CLAIM = re.compile(r"\b(?:charged|billed)\s+(?:to|on)\s+(?:your\s+|the\s+)?checking\b|\bcharges\s+(?:your\s+)?"
                            r"checking\b|\bdirectly from (?:your\s+)?checking\b", re.I)   # an explicit charging claim
SAVES_RE = re.compile(r"\bsav(?:e|es|ed|ing|ings of)\s+(?:you\s+|her\s+)?(?:only\s+|about\s+|just\s+)?"
                      r"([-−]?\$\s?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)", re.I)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n")


def _windows(text, names):
    """[(merchant, the text from its mention to the next merchant mention or the end of the sentence)]."""
    out = []
    for sentence in SENTENCE_END.split(text):
        hits = sorted((m.start(), m.end(), name) for name in names
                      for m in re.finditer(r"\b" + re.escape(name) + r"\b", sentence, re.I))
        for i, (start, end, name) in enumerate(hits):
            stop = hits[i + 1][0] if i + 1 < len(hits) else len(sentence)
            out.append((name, sentence[end:stop]))
    return out


def reason_problems(text, pack, names):
    """Reason claims must match the facts: a merchant named must be in the pack; "charged to the card" /
    "charges checking" must match where the merchant really charges; "saves $X" next to a merchant must equal a
    computed saving for that merchant."""
    problems = []
    pack_text = " ".join([*pack.context, *(f"{it.get('title', '')} {it.get('how', '')} "
                                          + " ".join(r["what"] for r in it.get("rows", [])) for it in pack.items)]).lower()
    for name, window in _windows(text, names):
        if name.lower() not in pack_text:
            problems.append(f"{name} is not in the facts")
            continue
        accounts = names[name]
        if CARD_CLAIM.search(window) and "card" not in accounts:
            problems.append(f"{name} is not charged to the credit card (it charges checking)")
        if CHECKING_CLAIM.search(window) and "checking" not in accounts:
            problems.append(f"{name} does not charge checking (it is billed to the credit card)")
        m = SAVES_RE.search(window)
        if m:
            written, v = find_amounts(m.group(1))[0]
            titles = [(it, it["title"].split("(")[0].lower()) for it in pack.items      # not the what-ifs in (...)
                      if it["kind"] == "calc" and it.get("unit") == "USD"]
            savings = [Decimal(it["raw"]) for it, t in titles
                       if name.lower() in t and ("sav" in t or "cancel" in t)]
            ok = any(abs(v) == abs(x) or ("." not in written and abs(v) == _rounded(x)) for x in savings)
            if not ok:
                problems.append(f"\"saves {written.strip()}\" for {name} doesn't match its computed saving"
                                + (f" ({', '.join(w.money(x) for x in savings)})" if savings else
                                   " (there is no saving for it in the facts)"))
    return problems


def _units(text):
    """Bullets and sentences, normalized for comparing (no citations, no section heads, lowercase)."""
    out = []
    for line in text.splitlines():
        line = SECTION_HEAD.sub(lambda m: m.group(2), line)
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", strip_citations(line))
        for part in re.split(r"(?<=[.!?])\s+", line):
            norm = " ".join(re.sub(r"[^a-z0-9$ ]", " ", part.lower()).split())
            if len(norm.split()) >= 4:
                out.append((part.strip(), norm))
    return out


def _same(a, b):
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.9


def remove_repeats(text):
    """The answer with every repeated or near-identical sentence removed (the first one is kept), by the same rule
    as repetition_problems(). No word is added or changed; a bullet or NOTE left empty is dropped."""
    seen, out = [], []
    for line in text.splitlines():
        head = SECTION_HEAD.match(line)
        if head:
            prefix, body = line[:head.start(2)], head.group(2)
        else:
            m = re.match(r"^\s*(?:[-*•]|\d+[.)])\s*", line)
            prefix, body = (line[:m.end()], line[m.end():]) if m else ("", line)
        keep = []
        for part in re.split(r"(?<=[.!?])\s+", body):
            norm = " ".join(re.sub(r"[^a-z0-9$ ]", " ", strip_citations(part).lower()).split())
            if len(norm.split()) >= 4:
                if any(_same(s, norm) for s in seen):
                    continue
                seen.append(norm)
            keep.append(part)
        if body.strip() and not " ".join(keep).strip() and (not head or head.group(1).upper() == "NOTE"):
            continue                                      # the whole bullet / NOTE was a repeat
        out.append((prefix + " ".join(keep)).rstrip())
    return "\n".join(out)


def repetition_problems(text):
    units, problems = _units(text), []
    for i in range(len(units)):
        for j in range(i + 1, len(units)):
            a, b = units[i][1], units[j][1]
            if _same(a, b):
                problems.append(f"the answer repeats itself (\"{units[j][0][:60]}\")")
                return problems
    return problems


BUDGET_RE = re.compile(r"\b(?:budget|limit|cap|target|goal)\b[^.\n]{0,40}\$|\$[\d,.]+\s+(?:\w+\s+){0,3}"
                       r"(?:budget|limit|cap|target|goal)\b", re.I)


COPIED_HINT = re.compile(r"\((?:as a WHY bullet|in NOTE|in ANSWER|put this FIRST[^)]*)\)", re.I)


def copied_hint_problems(text):
    """The prompt's placement hints ("(as a WHY bullet)") must never end up in the answer."""
    return [f"the answer copied an instruction: {m.group(0)}" for m in COPIED_HINT.finditer(text)][:1]


NEGATIVE_MONEY = re.compile(r"(?<![\w.])[-\u2212]\s?\$\s?\d[\d,]*(?:\.\d{1,2})?")


def negative_money_problems(text):
    """A balance below zero is written "$1,568 below zero", never with a minus sign (readability rule)."""
    return [f"{m.group(0)} has a minus sign; write it as \"{m.group(0).lstrip('-\u2212 ')} below zero\""
            for m in NEGATIVE_MONEY.finditer(text)][:1]


AID_WORDS = re.compile(r"\b(?:grant|scholarship|award|work-study|aid)\b", re.I)
HEDGES = re.compile(r"\b(?:if (?:you(?:'re| are) )?(?:approved|hired)|may|might|could|up to|if you apply|if accepted)\b",
                    re.I)


QUALIFY_CLAIM = re.compile(r"\byou (?:qualify|are eligible|'re eligible|will get|will receive)\b", re.I)


def web_claim_problems(text):
    """Online results are unchecked: never tell her she qualifies for them."""
    m = QUALIFY_CLAIM.search(strip_citations(text))
    return [f"\"{m.group(0)}\": Runway didn't check online results; say \"check before applying\""] if m else []


def assumption_place_problems(text, required):
    """The plan's assumption ("You didn't say when you'd buy it, so I assumed tomorrow ...") belongs in NOTE only."""
    sec = parse_sections(text)
    if not sec:
        return []
    out = []
    for f in required:
        if f.key != "assumption":
            continue
        key = " ".join(re.sub(r"[^a-z ]", " ", f.line.lower()).split()[:6])        # "you didn t say when you d"
        elsewhere = [sec["answer"], *sec["why"], *sec["do"]]
        if any(key in " ".join(re.sub(r"[^a-z ]", " ", x.lower()).split()) for x in elsewhere):
            out.append("the assumption is outside NOTE; write it once, in NOTE only")
    return out


def certainty_problems(text):
    """Aid opportunities are never certain: a sentence about a grant or scholarship that states an amount or an
    arrival must say "if approved" (or may / could / up to / if hired)."""
    for sentence in SENTENCE_END.split(strip_citations(text)):
        if AID_WORDS.search(sentence) and (find_amounts(sentence) or re.search(r"\barriv|\bpaid\b|\bget\b", sentence,
                                                                               re.I)) and not HEDGES.search(sentence):
            return [f"\"{sentence.strip()[:60]}\" treats aid as certain; say \"if approved\""]
    return []


DEADLINE_WORDS = re.compile(r"\bdeadline\b|\bapply (?:by|before)\b", re.I)


def deadline_problems(text, opportunities):
    """A sentence naming an opportunity with a deadline must use that opportunity's own deadline (seen live: "Apply
    for the Student Emergency Grant before the Nov 15 deadline"; the grant is rolling, Nov 15 is another award's)."""
    for sentence in SENTENCE_END.split(strip_citations(text)):
        if not DEADLINE_WORDS.search(sentence):
            continue
        found = [d for _, d, _ in find_dates(sentence) if d]
        for o in opportunities:
            alias = " ".join(re.sub(r"[^a-z ]", " ", o.name.lower()).split()[-2:])
            if alias in " ".join(re.sub(r"[^a-z ]", " ", sentence.lower()).split()) and found:
                if o.deadline is None:
                    return [f"the {o.name} has no deadline (apply anytime), not {w.day(found[0])}"]
                if found[0] != o.deadline:
                    return [f"the {o.name}'s deadline is {w.day(o.deadline)}, not {w.day(found[0])}"]
    return []


# What only the engine's notes look like: "Tue Oct 27" (no comma after the weekday), the demo year, "=", " x ", " / ".
# Plain wording writes "Tue, Oct 27" and shows a year only when it isn't 2026 ("Fri, Jan 15, 2027").
ENGINE_STYLE = re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b"
                          r"|\b2026\b|=|\sx\s|\s/\s")


def copied_how_problems(text, pack):
    """The "How:" notes in the facts explain the math to the model ("Missing form submitted Tue Oct 27, 2026 + 7
    business days = Thu Nov 5, 2026."); copied into an answer they read like a spreadsheet. A sentence or bullet
    that is mostly one of them (90% alike, or sharing a 35-character run) AND carries the notes' engine formatting
    (ENGINE_STYLE) fails. A plain restatement ("Groceries $176.49 plus Eating out $81.32") is fine."""
    hows = [h for it in pack.items if it.get("kind") == "calc"
            for h in re.split(r"(?<=[.;])\s+", it.get("how", "")) if len(h.split()) >= 6]
    norm = [" ".join(re.sub(r"[^a-z0-9$ ]", " ", h.lower()).split()) for h in hows]
    for shown, unit in _units(text):
        if not ENGINE_STYLE.search(shown):
            continue
        for n in norm:
            m = difflib.SequenceMatcher(None, unit, n, autojunk=False)
            if m.ratio() >= 0.9 or m.find_longest_match(0, len(unit), 0, len(n)).size >= 35:
                return [f"the answer copied a calculation note (\"{shown[:50]}\"); say it in plain words"]
    return []


def invented_budget_problems(text, pack=None):
    """A step that sets a budget or limit with a dollar amount Runway never computed invents a number (a budget
    amount from the facts, e.g. her own budget, is fine)."""
    sec = parse_sections(text) or {}
    money = allowed_values(pack)[0] if pack is not None else set()
    rounded = {_rounded(v) for v in money}
    return [f"\"{x[:50]}\" sets a budget or limit Runway didn't compute" for x in sec.get("do", [])
            if BUDGET_RE.search(x) and not all(abs(v) in money or ("." not in s and abs(v) in rounded)
                                               for s, v in find_amounts(x))]


DANGLING = {"to", "the", "a", "an", "and", "or", "of", "for", "your", "on", "at", "with", "by", "from", "in", "is",
            "are", "was", "be", "will", "save", "saves", "that", "this", "it", "if", "because", "but", "so", "than",
            "about", "into", "when", "you", "until", "before", "after", "$"}


def cutoff_problems(text, finish_reason=None):
    """Cut off: the model hit its token limit, or the answer ends on a word no sentence ends with ("...to save").
    A list item without a final period is fine."""
    if finish_reason == "length":
        return ["the answer was cut off (it ran out of room); write a shorter answer"]
    tail = strip_citations(text).rstrip()
    words = re.findall(r"[a-z$]+", tail.lower()[-40:])
    if tail and tail[-1] not in ".!?)\"'”’]" and words and words[-1] in DANGLING:
        return ["the answer stops mid-sentence"]
    return []


EVENT_WORDS = {"rent": "rent", "credit card payment": "card", "card payment": "card", "card bill": "card",
               "paycheck": "pay", "payday": "pay", "refund": "refund", "tuition": "tuition", "installment": "tuition"}
EVENT_RE = re.compile(r"\b(" + "|".join(sorted(EVENT_WORDS, key=len, reverse=True)) + r")\b(?!\s+(?:form|money))",
                      re.I)


def event_dates(ds, scenario):
    """{"rent" | "card" | "pay" | "refund" | "tuition": dates that event really happens} from the records and the
    projection, for the event/date check."""
    out = {k: set() for k in ("rent", "card", "pay", "refund", "tuition")}
    out["rent"] |= {r.due for r in ds.rent_schedule} | {t.date for t in ds.checking_txns if t.category == "rent"}
    out["card"] |= {s.due for s in ds.statements} | {t.date for t in ds.checking_txns if t.category == "card_payment"}
    out["pay"] |= {p.pay_date for p in ds.pay_periods} | {t.date for t in ds.checking_txns if t.purpose == "wages"}
    out["tuition"] |= {i.due for i in ds.installments}
    for s in {scenario, engine.Scenario(refund_released=True, refund_submit_date=scenario.refund_submit_date)}:
        p = engine.project(s, ds, engine.Ledger())
        for e in p.events:
            kind = {"rent": "rent", "card_autopay": "card", "paycheck": "pay", "refund": "refund",
                    "installment": "tuition"}.get(e.kind)
            if kind:
                out[kind].add(e.date)
        rel = engine.refund_release_date(ds, s)
        if rel:
            out["refund"].add(rel)
    return out


def event_date_problems(text, events):
    """"Rent on Mon, Nov 9" must be a real rent date (rent is due on the 1st; Nov 9 is the card payment): the first
    date after an event word, in the same clause and before any other event word, must be one of its dates."""
    if not events:
        return []
    problems = []
    for sentence in SENTENCE_END.split(text):
        hits = list(EVENT_RE.finditer(sentence))
        for i, m in enumerate(hits):
            stop = hits[i + 1].start() if i + 1 < len(hits) else len(sentence)
            window = sentence[m.end():min(stop, m.end() + 60)]
            found = find_dates(window)
            between = window[:window.find(found[0][0])].lower() if found else ""
            if re.search(r",|\b(?:before|after|until|by|than|since|following|then|and)\b", between):
                continue                       # "paycheck after Fri, Nov 20": the date belongs to something else
            if found and found[0][1] and found[0][1] not in events[EVENT_WORDS[m.group(1).lower()]]:
                problems.append(f"{found[0][0].strip()} is not a {m.group(1).lower()} date")
    return problems


def copied_label_problems(text, required):
    """The required facts' labels ("the duplicate subscription Apple Music:") are instructions, not answer text."""
    low = text.lower()
    return [f"the answer copied an instruction: \"{f.label}:\"" for f in required if f"{f.label.lower()}:" in low][:1]


def check_answer(text, pack, require_format=False, *, names=None, finish_reason=None, general=False,
                 private=None, required=(), events=None, aid=False, web=False):
    """Every dollar amount and date must come from the pack; every citation must exist. A whole-dollar amount
    ("$1,462") matches a pack value that rounds to it ($1,462.37); signs are ignored, so "$1,462 below zero"
    and "-$1,462.37" both match -$1,462.37. Also: reason claims about merchants (names: merchant_accounts()),
    no repeated sentences, no cut-off answers. General info (general=True) skips the number check but must not
    state any of the student's own amounts (private: private_amounts())."""
    problems = [] if text.strip() else ["the answer is empty"]
    problems += [f"{x} is a record ID; never write record IDs" for x in dict.fromkeys(RECORD_ID.findall(text))]
    if require_format and text.strip() and parse_sections(text) is None:
        problems.append("the answer is not in the ANSWER / WHY / DO THIS format")
    amounts, found, cites = find_amounts(text), find_dates(text), []
    if general:
        problems += [f"{x.strip()} looks like one of the student's own numbers; general info never states them"
                     for x, v in amounts if private and (abs(v) in private or _rounded(abs(v)) in
                                                         {_rounded(p) for p in private})]
    else:
        money, dates = allowed_values(pack)
        rounded = {_rounded(v) for v in money}
        ids = {it["id"] for it in pack.items}
        for written, v in amounts:
            whole = "." not in written
            if abs(v) not in money and not (whole and abs(v) in rounded):
                problems.append(f"{written.strip()} is not in the facts")
        for written, d, wd in found:
            if d is None or d not in dates:
                problems.append(f"{written.strip()} is not a date in the facts")
            elif wd and WEEKDAYS[d.weekday()] != wd.lower()[:3]:
                problems.append(f"{written.strip()} has the wrong weekday (it is a {d:%A})")
        cites = [c.strip() for m in CITE_RE.finditer(text) for c in re.split(r"[,;]", m.group(1))]
        problems += [f"[{c}] is not in the facts" for c in dict.fromkeys(cites) if c not in ids]
        if names:
            problems += reason_problems(text, pack, names)
        problems += (event_date_problems(text, events) + copied_label_problems(text, required)
                     + copied_how_problems(text, pack) + assumption_place_problems(text, required))
    if text.strip():
        problems += (repetition_problems(text) + cutoff_problems(text, finish_reason)
                     + invented_budget_problems(text, None if general else pack) + copied_hint_problems(text)
                     + negative_money_problems(text)
                     + (certainty_problems(text) + deadline_problems(text, aid if aid is not True else []) if aid else [])
                     + (web_claim_problems(text) if web else []))
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
    "- Never write a negative balance with a minus sign. Write \"$1,462 below zero\". A fact whose value is "
    "negative (like -144.19) is a balance below zero: write \"$144 below zero\".\n"
    "- Dates like \"Mon, Nov 9\".\n"
    "- Put a citation after each number or date, like [C3] or [E2]. At most 2 citations per bullet. Only cite "
    "ids that exist in the facts.\n"
    "- If the facts list an assumption (like \"You didn't say when you'd buy it, so I assumed tomorrow\"), "
    "write it ONCE, in NOTE only. Never put it in ANSWER, WHY or DO THIS.\n"
    "- Only name a store, app or subscription that appears in the facts. Only say what it is charged to (the "
    "credit card or checking) if the facts say so.\n"
    "- Never repeat a sentence or a bullet, and never repeat the ANSWER in WHY. Finish every sentence.\n"
    "- DO THIS steps use only amounts from the facts. Never invent a budget, a limit or a target amount.\n"
    "- Only say what the facts support. Don't guess about holds, rules or deadlines.\n"
    "- Include EVERY fact listed under \"Your answer must include all of these\", with its number, date and "
    "citation, in the place it asks for. The easy way: copy each quoted sentence as written (without the quotes "
    "or the words before it).\n"
    "- Never write record IDs such as HLD-01, CHK-0042 or RFD-01. Cite with [C#] or [E#] only.\n"
    "- The \"How:\" notes explain the math to you. Never copy them; say things in plain words.\n"
    "- No jargon: never say scenario, projection, ledger, evidence or computed. No bold, no headings.")

GENERAL_SYSTEM = (
    "You are Runway, a friendly money coach for a college student. Answer a GENERAL money question in plain "
    "words. It is not about the student's own accounts.\n"
    "Write at a grade 6-8 reading level. Short sentences (under 15 words). One idea per sentence.\n"
    "Reply in EXACTLY this format, under 90 words in total:\n"
    "ANSWER: <one short sentence>\nWHY:\n- <key point>\n- <key point>\n"
    "DO THIS:\n1. <one practical step>\nNOTE: <optional>\n"
    "Rules: never mention the student's own balances, bills, payments or any number about them. No citations. "
    "Never repeat a sentence. Finish every sentence. If it depends on the school or the lender, say so. Don't "
    "name specific government tools, websites or programs; point the student to their financial aid office "
    "instead.")


def explain_messages(question, plan, results, pack, verdict_label, required=(), general=False):
    if general:
        return [{"role": "system", "content": GENERAL_SYSTEM},
                {"role": "user", "content": f"Question: {question}\n\nWrite the answer now, in the format."}]
    facts = pack.prompt_text()
    head = f"Question: {question}\nWhat Runway checked: {plan_words(plan)}"
    if verdict_label:
        head += f"\nThe answer: {verdict_label}"
    if required:
        head += "\nYour answer must include all of these:\n" + "\n".join(f.prompt() for f in required)
    zero = [z for r in results for z in r.zero_fixes]
    for z in {z.name: z for z in zero}.values():          # the "explain why" moment, only when it applies
        head += (f"\nIn NOTE, say that cancelling {z.name} saves $0.00 {pack.cite(z.savings)} this semester: "
                 f"{z.name} is billed to the credit card, and that card bill is paid after the semester ends.")
    return [{"role": "system", "content": EXPLAIN_SYSTEM},
            {"role": "user", "content": f"{head}\n\n{facts}\n\nWrite the answer now, in the format."}]


def plan_words(plan):
    """What Runway checked, in plain words (every call of a multi-step plan, joined)."""
    if not plan.calls:
        return "nothing (off-topic)"
    return "; ".join(call_words(c["tool"], c["args"]) for c in plan.calls)


def _span(a):
    start = w.day(date.fromisoformat(a["start"])) if a.get("start") else "the start of your records"
    return f"{start} to {w.day(date.fromisoformat(a['end']))}"


def call_words(tool, a):
    if tool == "can_afford":
        how = "debit card (checking)" if a["account"] == "checking" else "credit card"
        return f"can you afford {a['item']} for {w.dollars(Decimal(a['cost']))} on "                f"{w.day(date.fromisoformat(a['date']))}, paid by {how}"
    if tool == "what_if":
        parts = [f"cancel {', '.join(a['cancel_subscriptions'])}"] if a["cancel_subscriptions"] else []
        parts += [f"an extra {s['hours']}-hour shift on {w.day(date.fromisoformat(s['date']))}"
                  for s in a["extra_shifts"]]
        if a["send_verification_form"]:
            parts.append(f"send the verification form on {w.day(date.fromisoformat(a['form_date']))}")
        return "what happens if you " + " and ".join(parts)
    if tool == "spending_summary":
        return f"what you spent by {a['group_by']}, {_span(a)}"
    if tool == "find_transactions":
        return f"your transactions matching \"{a['query'] or 'any'}\", {_span(a)}"
    if tool == "upcoming_bills":
        return f"bills due {_span(a)}"
    if tool == "work_summary":
        return f"your hours and pay, {_span(a)}"
    if tool == "balance_on":
        return f"your checking balance on {w.day(date.fromisoformat(a['date']))}"
    if tool == "action_plan":
        return f"what needs your attention, {_span(a)}"
    if tool == "find_aid":
        return "grants, scholarships and work-study you may qualify for" + (
            f" ({a['type'].replace('_', ' ')})" if a.get("type") else "")
    if tool == "meal_plan":
        return "your meal plan"
    if tool == "search_scholarships":
        return "scholarships and aid found online"
    if tool == "budget_status":
        return f"your {(a.get('category') or 'whole').lower()} budget, {date.fromisoformat(a['month'] + '-01'):%B}"
    if tool == "general_info":
        return f"general info: {a.get('topic') or 'your question'}"
    return {"runway": "how long your money lasts", "find_leaks": "where your money is leaking",
            "refund_status": "why your refund is on hold", "cash_crunches": "weeks where money gets tight",
            "accounts_today": "your balances and what's pending today",
            "money_ideas": "ways to get money before you run out"}.get(tool, "your question")


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
    if f.get("unavailable"):
        return _format("That needs your school data.", [NOT_AVAILABLE.split(". ")[0] + "."],
                       ["Connect your school data to see this."])
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
            why = [f"A {w.dollars(r.event.amount)} {w.event_name(r.event)} {c(r.event.computed)} is due "
                   f"{w.day(r.event.date)}, when you'll have {w.balance(r.balance_before)}."] if r.event else                 ["Everyday spending slowly adds up."]
        changes = [f"The extra shift adds {w.dollars(pay.value)} to your {w.day(pay_date)} paycheck {c(pay)}."
                   for pay_date, pay in f.get("shift_pay", [])]
        if f.get("shift_plan"):                       # several shifts: the total, then one line per payday
            sp = f["shift_plan"]
            paid = {}
            for x in sp.shifts:
                paid.setdefault(x.pay_date, []).append(x)
            changes = [f"These {len(sp.shifts)} shifts add {w.dollars(sp.total.value)} {c(sp.total)}."]
            for pay_date, xs in paid.items():
                when = {"in_time": "before you run out" if sp.before.first_below_zero.value else "",
                        "late": "after you run out", "after_semester": "after the semester"}[xs[0].timing]
                days = [w.day(x.shift.date) for x in xs]
                days = days[0] if len(days) == 1 else ", ".join(days[:-1]) + " and " + days[-1]
                changes.append(f"Pay for {days} arrives {w.day(pay_date)}" + (f", {when}" if when else "")
                               + f" {c(xs[0].added)}.")
        if changes:                                       # a what-if leads with the change itself
            answer, why = changes[0], [answer] + why + changes[1:]
        if f.get("latest_shift") and not f.get("shift_plan"):
            shift_c, pay_c = f["latest_shift"]
            why.append(f"A shift worked by {w.day(shift_c.value)} is paid {w.day(pay_c.value)}, before you run out "
                       f"{c(shift_c)}.")
        if f.get("shift_plan"):                       # the total leads; the run-out line, then the paydays
            why = why[:1] + changes[1:]
        return _format(answer, why, ["Try these in the shift planner in the Semester tab."
                                     if f.get("shift_plan") else "Look at the ways to fix it in the Semester tab."],
                       note)
    if plan.tool == "find_leaks":
        why, do = [], []
        for leak in f["leaks"]:
            if leak.kind == "duplicate_subscriptions":
                comb = next(x for x in leak.computed if x.label.startswith("combined"))
                pick = next(x for x in leak.computed if x.label.startswith("which"))
                subs = [x.label.removesuffix(" monthly cost") for x in leak.computed if x.label.endswith("monthly cost")]
                why.append(f"You pay for {' and '.join(subs)}: {w.dollars(comb.value)} a month together {c(comb)}.")
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
    parts = lookup_template(plan.tool, result, c)
    if parts:
        answer, why, do, extra = parts
        return _format(answer, why, do, " ".join(x for x in (extra, note) if x))
    return OFF_TOPIC


def _single(plan, r):
    return Plan(plan.intent, r.tool or plan.tool, r.args or plan.args, None, plan.assumptions, plan.source)


def template_all(plan, results, pack, ds, scenario):
    """The template answer for every call of the plan, merged into one (None for general info only)."""
    results = [r for r in (results if isinstance(results, list) else [results]) if (r.tool or plan.tool) != "general_info"]
    if not results:
        return None
    parts = [parse_sections(template_answer(_single(plan, r), r, pack, ds, scenario)) for r in results]
    if len(parts) == 1:
        return template_answer(_single(plan, results[0]), results[0], pack, ds, scenario)
    m = merge_sections(parts)
    return _format(m["answer"], m["why"], m["do"], m["note"])


def quick_answer(plan, results, pack, ds, scenario, required):
    """The instant answer: the template (verdict and key numbers, cited) plus any required fact it doesn't
    already state. Deterministic, so it always passes the number check. None for general info."""
    text = template_all(plan, results, pack, ds, scenario)
    if text is None:
        return None
    missing = missing_facts(text, required)
    return append_facts(text, missing) if missing else text


FAST_MAX_TOKENS = 1024           # thinking off: the answer alone is under 200 tokens
FAST_TIMEOUT_S = 60


def explain_chain(think=False):
    """EXPLAIN (model, thinking) pairs to try in order. Fast (default): Lightning with thinking off, then Super
    with thinking off. Think harder: Super with thinking on, then Lightning with thinking on."""
    fast, big = config.NVIDIA_PLAN_MODEL, config.NVIDIA_EXPLAIN_MODEL
    order = [(big, True), (fast, True)] if think else [(fast, False), (big, False)]
    return list(dict.fromkeys((m, t) for m, t in order if m))


def model_name(model):
    if not model or model == "template":
        return "a template"
    if "super" in model:
        return "Nemotron Super"
    if "lightning" in model:
        return "Nemotron Lightning"
    return model


def _explain_with(llm, model, thinking, messages, pack, retries, required=(), *, names=None, general=False,
                  private=None, events=None, aid=False, web=False):
    """Stream one EXPLAIN answer from `model`, check it (numbers, dates, citations, format, record IDs, reasons,
    repetition, cut-off, required facts), and allow one rewrite. Yields ("text"/"restart", ...) events and returns
    (text, reasoning, check, missing) where missing are the required facts the model still left out. Raises if the
    model fails or answers empty twice."""
    text, reasoning, check, missing = "", "", None, []
    for attempt in range(2):
        limit = FAST_MAX_TOKENS if not thinking else (
            EXPLAIN_MAX_TOKENS if model == config.NVIDIA_EXPLAIN_MODEL else FALLBACK_MAX_TOKENS)
        stream = llm.stream_chat(messages, thinking=thinking, model=model, retries=1, max_tokens=limit,
                                 timeout=EXPLAIN_TIMEOUT_S if thinking else FAST_TIMEOUT_S)
        for kind, chunk in stream:
            if kind == "text":
                yield "text", chunk
        text, reasoning = _strip_think(stream.result.text, (reasoning + "\n" + stream.result.reasoning).strip())
        text = unflatten(text)
        check = check_answer(text, pack, require_format=True, names=names, general=general, private=private,
                             finish_reason=getattr(stream.result, "finish_reason", None), required=required,
                             events=events, aid=aid, web=web)
        if not check.ok and all(p.startswith("the answer repeats itself") for p in check.problems):
            fixed = remove_repeats(text)              # the only problem is a repeat: drop it, change no words
            again = check_answer(fixed, pack, require_format=True, names=names, general=general, private=private,
                                 finish_reason=getattr(stream.result, "finish_reason", None), required=required,
                                 events=events, aid=aid, web=web)
            if again.ok:
                text, check = fixed, again
                retries["repaired"] = "removed duplicate line"
        missing = missing_facts(text, required) if text else list(required)
        if (check.ok and not missing) or attempt == 1:
            break
        retries["explain_rewrite"] = retries.get("explain_rewrite", 0) + 1
        yield "restart", "Double-checking the numbers..."
        problems = check.problems + [f"missing {f.label}: {f.line}" + (" (put it FIRST)" if f.where == "lead" else
                                                                         " (in NOTE)" if f.where == "note" else "")
                                     for f in missing]
        if any("has a minus sign" in p for p in check.problems):
            problems.append("write every balance below zero as \"$144 below zero\" (the amount, then \"below "
                            "zero\"), never with a minus sign, and never copy a How note")
        if any(p.startswith("the assumption is outside NOTE") for p in check.problems):
            problems.append("delete the assumption from ANSWER, WHY and DO THIS; keep it only as the NOTE line")
        if any(p.startswith("the answer repeats itself") for p in check.problems):   # Lightning resends it as is
            problems.append("ANSWER must be ONE short sentence; say each reason once, in WHY only, and delete "
                            "the copy")
        messages = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "Problems: " + "; ".join(problems) +
             ". Rewrite the answer in the ANSWER / WHY / DO THIS / NOTE format"
             + (", with no numbers about the student." if general else
                ", using only numbers, dates and ids from the facts, and include every required fact.")
             + " Keep it short and finish every sentence."}]
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
    where: str = "any"           # "any", "lead" (ANSWER or the first WHY bullet), "note", "answer", "why"

    def prompt(self):
        place = {"lead": " (put this FIRST: in ANSWER or the first WHY bullet)", "note": " (in NOTE)",
                 "answer": " (in ANSWER)", "why": " (as a WHY bullet)"}.get(self.where, "")
        return f'- {self.label}{place}: "{self.line}"'


def _hours(x):
    return f"{float(x):g}"


def _short(name):
    return re.sub(r"\s*\(.*\)", "", name).strip()


def _sentence(s):
    return s if s.rstrip().endswith((".", "!", "?")) else s.rstrip() + "."


def _spending_step(sp):
    """Where to look first: the biggest flexible category (rent and bills can't be trimmed), or merchant."""
    if sp.group_by == "category":
        flex = next((n for n, _, _ in sp.groups if n in normalize.FLEXIBLE), None)
        return (f"Look at {flex.lower()} first: it's your biggest flexible category." if flex else
                "Most of it was rent and bills, which you can't trim month to month.")
    return f"Start with {_short(sp.groups[0][0])}, your biggest merchant."


def lookup_template(tool, result, c):
    """(answer, why, do, note) for the data-lookup tools, built only from engine values, with citations."""
    f = result.facts
    if tool == "spending_summary":
        sp = f["spending"]
        if not sp.count:
            return (f"You had no spending from {w.day(sp.start)} to {w.day(sp.end)} {c(sp.total)}.",
                    ["Nothing was bought in that period."], [], "")
        return (f"You spent {w.dollars(sp.total.value)} from {w.day(sp.start)} to {w.day(sp.end)} {c(sp.total)}.",
                [f"{_short(n)}: {w.dollars(g.value)} {c(g)}." for n, g, _ in sp.groups[:4]],
                [_spending_step(sp)],
                "Card payments are not counted: they just move money between your accounts.")
    if tool == "find_transactions":
        m = f["matches"]
        what = m.query or "that"
        if not m.rows:
            return (f"I didn't find any transactions matching \"{what}\" {c(m.count)}.",
                    [f"Nothing matched from {w.day(m.start)} to {w.day(m.end)}."], [], "")
        n = m.count.value
        head = (f"You spent {w.dollars(m.spent.value)} at {what} {c(m.spent)}." if m.spent else
                f"You received {w.dollars(m.received.value)} from {what} {c(m.received)}.")
        why = [f"That's {n} transaction{'s' if n != 1 else ''} from {w.day(m.start)} to {w.day(m.end)} {c(m.count)}.",
               f"The most recent one was on {w.day(m.last.value)} {c(m.last)}."]
        if m.spent and m.received:
            why.append(f"You also received {w.dollars(m.received.value)} {c(m.received)}.")
        return head, why, [], ""
    if tool == "upcoming_bills":
        b = f["bills"]
        if not b.events:
            return (f"No bills are due from {w.day(b.start)} to {w.day(b.end)} {c(b.total)}.",
                    ["Only everyday spending comes out in those days."], [],
                    f"Your balance at the end of {w.day(b.end)} would be {w.balance(b.balance_after.value)} "
                    f"{c(b.balance_after)}.")
        k = len(b.events)
        return (f"You have {k} bill{'s' if k != 1 else ''} due from {w.day(b.start)} to {w.day(b.end)}: "
                f"{w.dollars(b.total.value)} in all {c(b.total)}.",
                [f"{w.event_name(e).capitalize()}: {w.dollars(e.amount)} on {w.day(e.date)} {c(e.computed)}."
                 for e in b.events[:5]],
                ["Keep that money in checking before each due date."],
                f"Your balance at the end of {w.day(b.end)} would be {w.balance(b.balance_after.value)} "
                f"{c(b.balance_after)}.")
    if tool == "work_summary":
        wk = f["work"]
        why = []
        if wk.scheduled_hours.value:
            why.append(f"You're scheduled for {_hours(wk.scheduled_hours.value)} more hours {c(wk.scheduled_hours)}.")
        why += [f"Your {w.day(d.value)} paycheck: {w.dollars(n.value)} {c(n)}." for _, n, d in wk.periods[:4]]
        if wk.called_off:
            why.append(f"You called off {len(wk.called_off)} shift{'s' if len(wk.called_off) != 1 else ''}.")
        head = (f"You worked {_hours(wk.worked_hours.value)} hours from {w.day(wk.start)} to "
                f"{w.day(min(wk.end, config.DEMO_TODAY))} {c(wk.worked_hours)}." if wk.start <= config.DEMO_TODAY
                else f"You're scheduled for {_hours(wk.scheduled_hours.value)} hours {c(wk.scheduled_hours)}.")
        if wk.periods:
            why.append(f"Paychecks in that time add up to {w.dollars(wk.pay_total.value)} {c(wk.pay_total)}.")
        return head, why or ["No paychecks in that time."], [], "Pay is after withholding."
    if tool == "balance_on":
        b = f["day"]
        past = b.day <= config.DEMO_TODAY
        head = f"On {w.day(b.day)}, your checking balance {'was' if past else 'would be'} " \
               f"{w.balance(b.balance.value)} {c(b.balance)}."
        evs = [e for e in b.events if hasattr(e, "computed")]
        why = [f"{w.event_name(e).capitalize()}: {w.dollars(e.amount)} {'in' if e.amount > 0 else 'out'} "
               f"{c(e.computed)}." for e in evs[:4]] or (
            [f"{t.merchant}: {w.dollars(t.amount)} {'in' if t.amount > 0 else 'out'}." for t in b.events[:4]]
            if past else ["Only everyday spending that day."])
        return head, why or ["No transactions that day."], [], "" if past else "This is a projection."
    if tool == "accounts_today":
        t = f["today"]
        why = []
        if t.next_card_payment:
            e = t.next_card_payment
            why.append(f"Your next credit card payment is {w.dollars(e.amount)} on {w.day(e.date)} {c(e.computed)}.")
        if t.refund:
            why.append(f"Your {w.dollars(t.refund.value)} refund is on hold {c(t.refund)}.")
        if t.next_paycheck:
            why.append(f"Your next paycheck is {w.dollars(t.next_paycheck.amount)} on "
                       f"{w.day(t.next_paycheck.date)} {c(t.next_paycheck.computed)}.")
        do = [f"Send the verification form. The refund comes around {w.day(t.refund_release.value)} "
              f"{c(t.refund_release)}."] if t.refund else []
        return (f"You have {w.dollars(t.checking.value)} in checking today {c(t.checking)}.", why, do, "")
    if tool == "find_aid":
        checks, total, run_out = f["checks"], f["total"], f["run_out"]
        ok = [x for x in checks if x.status == "eligible"]
        if not ok:
            return "I didn't find aid you qualify for right now.", ["None of the school's opportunities fit yet."], [], ""
        ok.sort(key=lambda x: (not x.before_run_out, x.arrives.value))
        lines = [aid_line(x, c) for x in ok[:4]]
        money_ok = [x for x in ok if x.amount]
        head = (f"You may qualify for {len(money_ok)} award{'s' if len(money_ok) != 1 else ''} worth up to "
                f"{w.dollars(total.value)} {c(total)}, if approved." if money_ok else
                "You may qualify for a work-study job, if you're hired.")
        soon = [x for x in ok if x.before_run_out and x.amount]
        do = ([f"Apply for the {soon[0].opp.name.lower()} first: it's the only one that could arrive before "
               f"{w.day(run_out.value)} {c(run_out)}."] if soon and run_out.value else [])
        do.append("Open Find money to draft the application.")
        almost = [x for x in checks if x.status == "almost"]
        note = " ".join(f"You'd need {x.missing[0]} for the {x.opp.name}." for x in almost[:1])
        return head, lines, do, ("None of this is certain until it's approved. " + note).strip()
    if tool == "search_scholarships":
        rows, when = f["web"], f["found_at"]
        if not rows:
            return ("I couldn't find scholarships online right now.", ["The web search didn't return results."],
                    ["Try again later, or ask your financial aid office."], "")
        why = []
        for r, amount, deadline in rows[:4]:
            a = f"{w.dollars(amount.value)} {c(amount)}" if amount else "see website"
            d = f"{w.day(deadline.value)} {c(deadline)}" if deadline else "see website"
            why.append(f"[{r['title']}]({r['url']}) ({r['organization']}): amount {a}; deadline {d}.")
        note = ("Check each one before applying: Runway didn't check who can apply, and none of this is in your "
                "forecast." + (f" Searched {w.day(when.value)} {c(when)}." if when else ""))
        return (f"Here are {len(rows)} scholarships and grants I found online. Check before applying.", why,
                ["Open each link and read who can apply before you start."], note)
    if tool == "meal_plan":
        m = f["meal"]
        if not m:
            return "I don't see a meal plan.", ["No meal plan is on file."], [], ""
        k = m.c
        head = (f"Your dining dollars run out around {w.day(m.runs_out)} {c(k['dd_runs_out'])}." if m.runs_out else
                f"Your dining dollars last the semester {c(k['dd_runs_out'])}.")
        why = [f"You have {k['swipes_left'].value} swipes {c(k['swipes_left'])} and {w.dollars(k['dd_left'].value)} "
               f"in dining dollars {c(k['dd_left'])} left.",
               f"You'll have about {k['swipes_end'].value:.0f} swipes left on {w.day(config.SEMESTER_END)} "
               f"{c(k['swipes_end'])}."]
        why.append(f"Swipes cover the gap, so checking pays {w.dollars(k['cost'].value)} {c(k['cost'])}."
                   if not k["cost"].value else
                   f"Checking would pay {w.dollars(k['cost'].value)} for meals {c(k['cost'])}.")
        do = ([f"Use 2 swipes a week instead of dining dollars: you'd still have {w.dollars(m.tip['dd_end'].value)} "
               f"in dining dollars on {w.day(config.SEMESTER_END)} {c(m.tip['dd_end'])}."]
              if m.runs_out and m.tip_works else [])
        return head, why, do, ""
    if tool == "budget_status":
        b = f["status"]
        if b.suggestion:
            sg = b.suggestion
            m, month = sg.available, f"{sg.start:%B}"
            if sg.fits:
                return ("You haven't set a budget yet.",
                        [f"You have {w.dollars(m.amount.value)} to spend after rent and bills in {month} "
                         f"{c(m.amount)}.",
                         "Based on your usual spending: " + ", ".join(f"{x.category} {w.dollars(x.suggested.value)} "
                                                                       f"{c(x.suggested)}".strip() for x in sg.lines)
                         + "."],
                        ["Open the Budget tab and press Suggest a budget."], "")
            short = (f"Without your refund, {month}'s bills are {w.dollars(m.amount.value)} more than your money "
                     f"{c(m.amount)}." if not b.refund_released else
                     f"{month}'s bills are {w.dollars(m.amount.value)} more than your money {c(m.amount)}.")
            return ("You haven't set a budget yet.", [short, "So no budget fits until more money comes in."],
                    ["Send your verification form first. Then set a budget."] if not b.refund_released else [], "")
        name = (b.categories[0] if len(b.categories) == 1 else
                next((g for g, cs in engine.BUDGET_GROUPS.items() if cs == b.categories), "whole"))
        spent = (f"You've spent {w.dollars(b.spent.value)} {c(b.spent)} this month, against a budget of "
                 f"{w.dollars(b.budget.value)}.")
        pace = {"on pace": "You're on pace.", "spending fast": "You're spending faster than the budget allows.",
                "over": "You're over budget."}[b.pace]
        extra = ([f"Plus {w.dollars(b.one_offs.value)} in one-off purchases of $100 or more {c(b.one_offs)}, not "
                  "counted against the budget."] if b.one_offs else [])
        if name != "whole":
            label = name.lower()
            head = (f"You have {w.dollars(b.left.value)} left in your {label} budget {c(b.left)}." if b.left.value >= 0
                    else f"You're {w.dollars(b.left.value)} over your {label} budget {c(b.left)}.")
            return head, [spent, pace] + extra, [], ""
        e = b.effect
        over = [r for r in b.rows if r.left.value < 0]
        why = [spent] + [f"{r.category} is {w.dollars(r.left.value)} over {c(r.left)}." for r in over[:2]] + extra
        return todo_effect(e, c(e.days_longer)), why, [], pace
    if tool == "action_plan":
        items, (start, end), nxt = f["items"], f["span"], f["next"]
        when = f"from {w.day(start.value)} to {w.day(end.value)}"
        if not items:
            why = ["No deadlines fall in those days."]
            if nxt:
                title, sentence = todo.text(nxt, c)
                why = [f"Next up after that: {title[0].lower()}{title[1:]}.", sentence]
            return f"Nothing needs you {when} {c(end)}.", why, [], ""
        top, k = items[:3], len(items)
        lines = [todo.line(it, c) for it in top]
        head = (f"Start here: {todo.step(top[0])[0].lower()}{todo.step(top[0])[1:]}" if end.value == config.SEMESTER_END
                else f"{w.things(k).capitalize()} need{'s' if k == 1 else ''} you {when} {c(end)}.")
        return (head, lines, [todo.step(it) for it in top[:2]],
                "Most urgent first: the money at stake and how soon it's due."
                + (f" {k - 3} more in your check-in." if k > 3 else ""))
    if tool == "money_ideas":
        ideas, dl, p = f["ideas"], f["deadline"], f["projection"]
        lines = []
        for i in ideas[:4]:
            if i.kind == "refund":
                lines.append(f"Send the verification form: your {w.dollars(i.amount.value)} refund arrives around "
                             f"{w.day(i.arrives.value)} {c(i.amount)}.")
            elif i.kind == "shift":
                lines.append(f"Work an extra shift by {w.day(i.detail.value)}: it adds {w.dollars(i.amount.value)} "
                             f"on {w.day(i.arrives.value)} {c(i.amount)}.")
            else:
                lines.append(f"{i.name.capitalize()}: that saves {w.dollars(i.amount.value)} from "
                             f"{w.day(i.arrives.value)} {c(i.amount)}.")
        when = f"before you run out on {w.day(dl.value)}" if p.first_below_zero.value else \
            f"by {w.day(dl.value)}"
        if not ideas:
            return (f"I don't see a quick way to add money {when} {c(dl)}.",
                    ["The refund and extra shifts would come too late."], [], "")
        k = len(ideas)
        return (f"Here {'is 1 way' if k == 1 else f'are {k} ways'} to get money {when} {c(dl)}.", lines,
                [lines[0].split(":")[0] + "."], "Ranked by when the money arrives.")
    return None


def aid_line(x, c):
    """One opportunity in one sentence, always "if approved" (or "if you're hired")."""
    o = x.opp
    if o.type == "work_study":
        return (f"{o.name}: ${o.hourly_rate:.0f}/hour; if you're hired, your first paycheck comes "
                f"{w.day(x.arrives.value)} {c(x.arrives)}.")
    amount = f"up to {w.dollars(x.amount.value)}" if o.max_amount and not o.amount else w.dollars(x.amount.value)
    if x.this_semester is not None and not x.this_semester.value:
        return (f"{o.name}: {amount} {c(x.amount)}; if approved, it's paid {w.day(x.arrives.value)} {c(x.arrives)}, "
                f"after the semester. So it adds {w.dollars(0)} this semester.")
    return f"{o.name}: {amount} {c(x.amount)}; if approved, it arrives around {w.day(x.arrives.value)} {c(x.arrives)}."


def todo_effect(e, cite=""):
    """What sticking to the budget does, in one sentence (the same words as the Budget tab), cited."""
    import summary
    first = summary.budget_effect_line(e).split(". ")[0].rstrip(".")
    return f"{first} {cite}".rstrip() + "."


def merge_sections(parts):
    """One answer from several (a multi-step plan): the first answer leads; each other part adds its answer and
    up to two reasons; steps and notes are combined. Identical lines appear once."""
    first = parts[0]
    why = list(first["why"][:2])
    for p in parts[1:]:
        why += [p["answer"]] + p["why"][:1]
    do = [x for p in parts for x in p["do"][:1]]
    note = " ".join(dict.fromkeys(p["note"] for p in parts if p["note"]))
    return {"answer": first["answer"], "why": list(dict.fromkeys(why))[:7], "do": list(dict.fromkeys(do))[:3],
            "note": note}


def lookup_facts(tool, result, c):
    """Required facts for the data-lookup tools."""
    f, out = result.facts, []
    if tool == "spending_summary":
        sp = f["spending"]
        out.append(Fact("total", "the total spent", f"You spent {w.dollars(sp.total.value)} from {w.day(sp.start)} "
                        f"to {w.day(sp.end)} {c(sp.total)}.", money=(sp.total.value,)))
        for n, g, _ in sp.groups[:3]:
            out.append(Fact(f"group_{n}", f"{_short(n)} and its amount", f"{_short(n)}: {w.dollars(g.value)} {c(g)}.",
                            money=(g.value,), words=(_short(n),)))
    elif tool == "find_transactions":
        m = f["matches"]
        if not m.rows:
            out.append(Fact("none", "that nothing matched", f"No transactions matched \"{m.query}\" {c(m.count)}.",
                            words=("no ", "didn't", "did not", "none", "nothing", "not find")))
        else:
            if m.spent:
                out.append(Fact("spent", "how much was spent", f"You spent {w.dollars(m.spent.value)} {c(m.spent)}.",
                                money=(m.spent.value,)))
            if m.received and not m.spent:
                out.append(Fact("received", "how much came in", f"You received {w.dollars(m.received.value)} "
                                f"{c(m.received)}.", money=(m.received.value,)))
            out.append(Fact("count", "how many transactions", f"That's {m.count.value} transactions {c(m.count)}.",
                            words=(str(m.count.value),)))
    elif tool == "upcoming_bills":
        b = f["bills"]
        if not b.events:
            out.append(Fact("none", "that no bills are due", f"No bills are due from {w.day(b.start)} to "
                            f"{w.day(b.end)} {c(b.total)}.", words=("no bill", "no scheduled", "nothing", "none")))
        for i, e in enumerate(b.events[:5]):
            out.append(Fact(f"bill{i}", f"the {w.event_name(e)} and its date",
                            f"{w.event_name(e).capitalize()}: {w.dollars(e.amount)} on {w.day(e.date)} {c(e.computed)}.",
                            money=(e.amount,), date=e.date))
        if len(b.events) > 1:
            out.append(Fact("total", "the total", f"That's {w.dollars(b.total.value)} in all {c(b.total)}.",
                            money=(b.total.value,)))
    elif tool == "work_summary":
        wk = f["work"]
        if wk.start <= config.DEMO_TODAY:
            out.append(Fact("worked", "the hours worked", f"You worked {_hours(wk.worked_hours.value)} hours "
                            f"{c(wk.worked_hours)}.", words=(_hours(wk.worked_hours.value),)))
        if wk.scheduled_hours.value:
            out.append(Fact("scheduled", "the hours still scheduled", f"You're scheduled for "
                            f"{_hours(wk.scheduled_hours.value)} more hours {c(wk.scheduled_hours)}.",
                            words=(_hours(wk.scheduled_hours.value),)))
        if wk.periods:
            out.append(Fact("pay", "the pay in that time", f"Paychecks in that time add up to "
                            f"{w.dollars(wk.pay_total.value)} {c(wk.pay_total)}.", money=(wk.pay_total.value,)))
    elif tool == "balance_on":
        b = f["day"]
        out.append(Fact("balance", "the balance on that day", f"On {w.day(b.day)}, your checking balance is "
                        f"{w.balance(b.balance.value)} {c(b.balance)}.", money=(b.balance.value,), date=b.day,
                        where="lead"))
    elif tool == "accounts_today":
        t = f["today"]
        out.append(Fact("checking", "the checking balance today", f"You have {w.dollars(t.checking.value)} in "
                        f"checking today {c(t.checking)}.", money=(t.checking.value,), where="lead"))
        if t.next_card_payment:
            e = t.next_card_payment
            out.append(Fact("card", "the next card payment", f"Your next credit card payment is {w.dollars(e.amount)} "
                            f"on {w.day(e.date)} {c(e.computed)}.", money=(e.amount,), date=e.date))
        if t.refund:
            out.append(Fact("refund", "the held refund", f"Your {w.dollars(t.refund.value)} refund is on hold "
                            f"{c(t.refund)}.", money=(t.refund.value,)))
        if t.next_paycheck:
            e = t.next_paycheck
            out.append(Fact("paycheck", "the next paycheck", f"Your next paycheck is {w.dollars(e.amount)} on "
                            f"{w.day(e.date)} {c(e.computed)}.", money=(e.amount,), date=e.date))
    elif tool == "find_aid":
        ok = [x for x in f["checks"] if x.status == "eligible"]
        out.append(Fact("if_approved", "that the money is only if approved", "None of this is certain until it's "
                        "approved.", words=("if approved", "if you're approved", "if you are approved")))
        if any(x.amount for x in ok):
            out.append(Fact("total", "the total you may qualify for, if approved",
                            f"You may qualify for up to {w.dollars(f['total'].value)} {c(f['total'])}, if approved.",
                            money=(f["total"].value,)))
        for x in sorted(ok, key=lambda x: (not x.before_run_out, x.arrives.value))[:2]:
            out.append(Fact(f"aid_{x.opp.row_id}", f"the {x.opp.name.lower()}, its amount and when it would arrive",
                            aid_line(x, c), money=(x.amount.value,) if x.amount else (), date=x.arrives.value))
    elif tool == "search_scholarships":
        out.append(Fact("check", "that she must check before applying", "Check before applying.",
                        words=("check before applying", "check each", "check them")))
    elif tool == "meal_plan":
        m = f["meal"]
        if m:
            k = m.c
            out.append(Fact("runs_out", "when the dining dollars run out",
                            f"Your dining dollars run out around {w.day(m.runs_out)} {c(k['dd_runs_out'])}."
                            if m.runs_out else f"Your dining dollars last the semester {c(k['dd_runs_out'])}.",
                            date=m.runs_out, words=() if m.runs_out else ("last",), where="answer"))
            out.append(Fact("swipes_end", "the swipes left on Dec 18",
                            f"You'll have about {k['swipes_end'].value:.0f} swipes left on {w.day(config.SEMESTER_END)} "
                            f"{c(k['swipes_end'])}.", words=(f"{k['swipes_end'].value:.0f}",)))
            out.append(Fact("cost", "what checking pays for meals",
                            f"Checking pays {w.dollars(k['cost'].value)} for meals {c(k['cost'])}.",
                            money=(k["cost"].value,)))
    elif tool == "budget_status":
        b = f["status"]
        if b.suggestion:
            out.append(Fact("no_budget", "that no budget is set", "You haven't set a budget yet.",
                            words=("haven't set", "no budget", "not set", "don't have a budget", "haven't made")))
            m = b.suggestion.available
            out.append(Fact("available", "what's left after rent and bills next month",
                            f"You have {w.dollars(m.amount.value)} to spend after rent and bills {c(m.amount)}."
                            if m.amount.value > 0 else
                            f"The bills are {w.dollars(m.amount.value)} more than your money {c(m.amount)}.",
                            money=(m.amount.value,)))
        else:
            single = len(b.categories) == 1 or any(cs == b.categories for cs in engine.BUDGET_GROUPS.values())
            if single:
                out.append(Fact("left", "how much is left (or over) in that budget",
                                f"You have {w.dollars(b.left.value)} left {c(b.left)}." if b.left.value >= 0 else
                                f"You're {w.dollars(b.left.value)} over {c(b.left)}.", money=(b.left.value,),
                                where="answer"))
            else:
                e = b.effect
                d = e.with_budget.first_below_zero.value
                out.append(Fact("effect", "what sticking to the budget does to the forecast",
                                todo_effect(e, c(e.days_longer)), date=d,
                                words=() if d else ("all semester",), where="answer"))
            out.append(Fact("spent", "spent so far and the budget",
                            f"You've spent {w.dollars(b.spent.value)} {c(b.spent)} this month, against a budget of "
                            f"{w.dollars(b.budget.value)}.", money=(b.spent.value, b.budget.value)))
    elif tool == "action_plan":
        main = {"refund": ("refund", "arrives"), "rent": ("rent", None), "run_out": ("payment", None),
                "subscriptions": ("saves", None), "tight_week": ("installment", None), "grant": ("amount", None),
                "meal_plan": (None, None)}
        for it in f["items"][:3]:
            money_key, date_key = main.get(it.kind, (None, None))
            out.append(Fact(f"todo_{it.kind}", todo.LABELS.get(it.kind, it.kind), todo.line(it, c),
                            money=(it.facts[money_key].value,) if money_key in it.facts else (),
                            date=it.facts[date_key].value if date_key else it.due.value))
        if not f["items"]:
            out.append(Fact("none", "that nothing is due then", f"Nothing needs you then {c(f['span'][1])}.",
                            words=("nothing", "no ", "caught up", "none")))
    elif tool == "money_ideas":
        ideas, dl, p = f["ideas"], f["deadline"], f["projection"]
        if p.first_below_zero.value:
            out.append(Fact("deadline", "the day the money runs out", f"You run out on {w.day(dl.value)} {c(dl)}.",
                            date=dl.value))
        for i in ideas[:3]:
            if i.kind == "refund":
                out.append(Fact("idea_refund", "the refund, its amount and arrival date",
                                f"Send the verification form: your {w.dollars(i.amount.value)} refund arrives around "
                                f"{w.day(i.arrives.value)} {c(i.amount)}.", money=(i.amount.value,),
                                date=i.arrives.value))
            elif i.kind == "shift":
                out.append(Fact("idea_shift", "the extra shift: by when, how much, paid when",
                                f"Work an extra shift by {w.day(i.detail.value)}: it adds {w.dollars(i.amount.value)} "
                                f"on {w.day(i.arrives.value)} {c(i.amount)}.", money=(i.amount.value,),
                                date=(i.detail.value, i.arrives.value), words=("shift",)))
            else:
                name = i.name.removeprefix("cancel ")
                out.append(Fact(f"idea_{name}", f"cancelling {name} and what it saves",
                                f"Cancel {name}: that saves {w.dollars(i.amount.value)} from {w.day(i.arrives.value)} "
                                f"{c(i.amount)}.", money=(i.amount.value,), words=(name,)))
    return out


def required_facts(plan, results, pack, ds, scenario):
    """The facts one answer must contain, each with its exact engine value and citation (every call of a
    multi-step plan), then the plan's assumptions."""
    out = []
    for r in results if isinstance(results, list) else [results]:
        tool = r.tool or plan.tool
        if r.facts.get("unavailable"):
            continue
        facts = lookup_facts(tool, r, pack.cite) if tool in LOOKUP_TOOLS else _core_facts(tool, r, pack, ds, scenario)
        out += [f for f in facts if f.key not in {x.key for x in out}]
    for a in plan.assumptions:
        out.append(Fact("assumption", "the assumption", a, date=config.DEMO_TODAY + timedelta(days=1), where="note"))
    return out


LOOKUP_TOOLS = ("spending_summary", "find_transactions", "upcoming_bills", "work_summary", "balance_on",
                "accounts_today", "money_ideas", "action_plan", "budget_status", "find_aid", "meal_plan",
                "search_scholarships", "general_info")


def _core_facts(tool, result, pack, ds, scenario):
    c, f, out = pack.cite, result.facts, []
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
                        date=best.lowest_date.value, where="why"))
    elif tool in ("runway", "what_if"):
        p, r = f["projection"], f["reason"]
        if tool == "what_if" and f.get("shift_plan"):
            sp = f["shift_plan"]
            out.append(Fact("shifts_total", "the total extra pay from the shifts",
                            f"These {len(sp.shifts)} shifts add {w.dollars(sp.total.value)} {c(sp.total)}.",
                            money=(sp.total.value,), where="lead"))
            for pay_date in dict.fromkeys(x.pay_date for x in sp.shifts if x.timing != "after_semester"):
                first = next(x for x in sp.shifts if x.pay_date == pay_date)
                out.append(Fact(f"payday_{pay_date}", f"the payday {w.day(pay_date)}",
                                f"Pay for the shift on {w.day(first.shift.date)} arrives {w.day(pay_date)} "
                                f"{c(first.added)}.", date=pay_date))
            for fx in result.fixes:
                fact = _fix_fact(fx, ds, f["new_scenario"], c)
                fact.where = "lead"
                out.append(fact)
        elif tool == "what_if":
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
                            date=p.first_below_zero.value, where="answer" if tool == "runway" else "any"))
            if tool == "runway" and r.event:
                out.append(Fact("cause", "the payment that causes it and what you'll have",
                                f"A {w.dollars(r.event.amount)} {w.event_name(r.event)} {c(r.event.computed)} is due "
                                f"{w.day(r.event.date)}, when you'll have {w.balance(r.balance_before)}.",
                                money=(r.event.amount, r.balance_before), where="why"))
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
    """Add a plain sentence for each missing fact: an ANSWER fact becomes the ANSWER (the model's ANSWER didn't
    say it, so it moves to the first WHY bullet), lead facts become the first WHY bullet, note facts go in NOTE,
    others are added as WHY bullets. Built from engine values only."""
    sec = parse_sections(text) or {"answer": text.strip(), "why": [], "do": [], "note": ""}
    moved = [f for f in missing if f.where in ("lead", "note")]            # stated, but in the wrong place: move it
    sec["why"] = [b for b in sec["why"] if not any(fact_present(f, b, {}) for f in moved)]
    answer = [f.line for f in missing if f.where == "answer"]
    lead = [f.line for f in missing if f.where == "lead"]
    rest = [f.line for f in missing if f.where in ("any", "why")]
    notes = [f.line for f in missing if f.where == "note"]
    note = " ".join(x for x in [sec.get("note", "")] + notes if x)
    old = [sec["answer"]] if answer and len(sec["answer"].split()) >= 4 else []     # a real sentence stays, as WHY
    return _format(" ".join(answer) or sec["answer"], lead + old + sec["why"] + rest, sec["do"], note)


def _strip_think(text, reasoning):
    if "</think>" in text:
        head, _, text = text.partition("</think>")
        reasoning = (reasoning + "\n" + head.replace("<think>", "")).strip()
    return text.strip(), reasoning


# ---------------------------------------------------------------------------------------
# ACTIONS (templates; drafts are never sent)
# ---------------------------------------------------------------------------------------
def actions_for(plan, result, ds, scenario):
    if plan.tool == "action_plan":         # the same buttons as the check-in cards, for these items
        kinds = [it.kind for it in result.facts["items"][:3]]
        return [Action("attention", "attention", "What to do", items=kinds)] if kinds else []
    out, items = [], []
    refund = next((r for r in ds.refunds if r.status == "HELD"), None)
    ideas = result.facts.get("ideas", []) if plan.tool == "money_ideas" else []
    wants_refund = refund and (plan.tool == "refund_status" or any(f.kind == "refund" for f in result.fixes)
                               or any(i.kind == "refund" for i in ideas))
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
    items += [f"Ask your manager for an extra shift by {w.day(i.detail.value)}." for i in ideas if i.kind == "shift"]
    if items:
        out.append(Action("checklist", "checklist", "Your to-do list", items=items))
    return out


def actions_for_all(plan, results, ds, scenario):
    """Drafts for every call of the plan: one email at most, one combined to-do list."""
    emails, items, todos = {}, [], []
    for r in results:
        for a in actions_for(_single(plan, r), r, ds, scenario):
            if a.kind == "email":
                emails.setdefault(a.id, a)
            elif a.kind == "attention":
                todos.append(a)
            else:
                items += [x for x in a.items if x not in items]
    out = todos + list(emails.values())
    if items:
        out.append(Action("checklist", "checklist", "Your to-do list", items=items))
    return out


# ---------------------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------------------
def normalize_question(q):
    return " ".join(re.sub(r"[^a-z0-9$.,\s]", " ", q.lower()).split()).rstrip(".,")


def cache_path(question, scenario, folder=None, history=(), done=(), budget=None):
    """Saved answers are keyed by the question, the what-ifs, for follow-ups the earlier questions, and the
    check-in items marked done (when there are any)."""
    key = f"{normalize_question(question)}|{scenario.describe()}"
    if done:
        key += "|done:" + ",".join(sorted(done))
    if budget and any(budget.values()):
        key += "|budget:" + ",".join(f"{c}={int(v)}" for c, v in sorted(budget.items()) if v)
    if history:
        key += "|" + "||".join(normalize_question(a.question) for a in history[-3:])
    return (folder or config.ANSWER_CACHE_DIR) / f"{hashlib.sha256(key.encode()).hexdigest()[:20]}.json"


def answer_folders(mode):
    """Where saved answers are looked up: replay = only the committed demo answers; cached = local cache first."""
    return [config.DEMO_ANSWERS_DIR] if mode == "replay" else [config.ANSWER_CACHE_DIR, config.DEMO_ANSWERS_DIR]


def load_cached(question, scenario, mode="cached", history=(), done=(), budget=None):
    for folder in answer_folders(mode):
        path = cache_path(question, scenario, folder, history, done, budget)
        if path.exists():
            return Answer.from_json(path.read_text(encoding="utf-8"))
    return None


def save_cached(answer, scenario, folder=None, history=(), done=(), budget=None):
    path = cache_path(answer.question, scenario, folder, history, done, budget)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(answer.to_json(), encoding="utf-8")


def no_live_answer_text(mode):
    """What a question with no saved answer gets when the models can't be called."""
    why = ("Live answers are off in replay mode." if config.NVIDIA_API_KEY else
           "Live answers need an NVIDIA key.")
    fix = ("restart with ANSWER_MODE=cached." if config.NVIDIA_API_KEY else
           "add NVIDIA_API_KEY to .env and restart with ANSWER_MODE=cached.")
    return (f"{why} Recorded answers cover the four suggested questions, with nothing changed or with both "
            f"fixes on. To ask anything else, {fix}")


# ---------------------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------------------
def _replay(answer, mode, typing_s):
    for stage in STAGES.values():
        yield "stage", stage
        time.sleep(typing_s * 10)
    if answer.quick:
        yield "quick", answer.quick
    for word in re.findall(r"\S+\s*", answer.text):
        yield "text", word
        time.sleep(typing_s)
    answer.mode = mode
    yield "answer", answer


def _verdict_result(results):
    return next((r for r in results if r.verdict), results[0])


def run(question, scenario=None, ds=None, mode=None, llm=None, typing_s=0.035, history=(), think=False, done=(),
        budget=None, private=False):
    """Answer one question. Yields ("stage" | "quick" | "text" | "restart" | "answer", payload); "answer" comes
    last. "quick" is the instant answer built from the engine (shown while the AI writes); "text" chunks are the
    AI answer streaming in. history: earlier Answers in this conversation (oldest first), for follow-ups.
    think: Nemotron Super with thinking on (slower, shows its reasoning); default: Lightning, thinking off.
    done: check-in item kinds the student marked done (left out of "what should I do" answers). budget: the
    amounts she set in the Budget tab (budget questions). private: her own data (My data mode): never read or
    write saved answers, always answer live (rule 7)."""
    scenario, ds = scenario or engine.Scenario(), ds or normalize.load()
    mode, llm = (mode or config.ANSWER_MODE).lower(), llm or llm_client
    question, history, done = question.strip(), list(history or [])[-3:], tuple(sorted(done or ()))
    if private:
        mode = "live"
    if mode in ("cached", "replay"):
        cached = load_cached(question, scenario, mode, history, done, budget)
        if cached and mode == "replay":
            yield from _replay(cached, "replay", typing_s)
            return
        if cached:
            cached.mode = "cached"
            yield "answer", cached
            return
    t0 = time.perf_counter()
    timings, retries, notes = {}, {"plan_json": 0, "explain_rewrite": 0, "facts_appended": 0}, []
    chain = explain_chain(think)
    models = {"plan": config.NVIDIA_PLAN_MODEL, "explain": chain[0][0] if chain else None, "think": think}
    if mode == "replay" or (llm is llm_client and not config.NVIDIA_API_KEY):    # nothing saved, no models
        text = no_live_answer_text(mode)
        yield "text", text
        timings["total_s"] = round(time.perf_counter() - t0, 2)
        yield "answer", Answer(question, text, None, None, asdict(Plan("off_topic", None, {}, None, [], "none")),
                               {"items": [], "context": []}, {}, "", [], [], "no_key", "none", [], timings,
                               retries, models, scenario.describe(), time.time(), {}, [], think=think)
        return
    sub_names = [s.merchant for s in engine.subscriptions(ds)]

    # PLAN (one call; the last 3 turns let it resolve follow-ups)
    yield "stage", STAGES["plan"]
    t = time.perf_counter()
    plan = None
    try:
        res = llm.chat_json(plan_messages(question, scenario, sub_names, history), thinking=False,
                            validate=lambda d: parse_plan(d, sub_names), timeout=PLAN_TIMEOUT_S, retries=1)
        plan = parse_plan(res.data, sub_names)
        plan = ground_purchase_date(plan, f"{question} {plan.resolved_question or ''}")
        plan = widen_broad_plan(plan, question)
        retries["plan_json"] = res.json_retries + res.retries
    except Exception as exc:                                       # slow, down, or unusable: keywords
        notes.append(f"The planner wasn't available ({type(exc).__name__}); Runway matched your question "
                     "by keywords.")
    if plan is None:
        plan = keyword_plan(question, sub_names) or Plan("off_topic", None, {}, None, [], "keywords")
    timings["plan_s"] = round(time.perf_counter() - t, 2)
    facts_record, quick = [], ""

    def finish(text, verdict=None, label=None, pack=None, check=None, reasoning="", actions=(), fixes=(),
               ans_mode=None, source="none"):
        timings["total_s"] = round(time.perf_counter() - t0, 2)
        return Answer(question, text, verdict, label, asdict(plan), pack.to_dict() if pack else {"items": [],
                      "context": []}, asdict(check) if check else {}, reasoning, [asdict(a) for a in actions],
                      [{"kind": f.kind, "name": f.name} for f in fixes], ans_mode or mode, source, notes, timings,
                      retries, models, scenario.describe(), time.time(), parse_sections(text) or {},
                      facts_record, quick=quick, think=think)

    if plan.tool is None:
        text = plan.clarifying_question or OFF_TOPIC
        yield "text", text
        yield "answer", finish(text, ans_mode="off_topic")
        return

    # EXECUTE (every call of the plan), then the instant quick answer
    yield "stage", STAGES["execute"]
    t = time.perf_counter()
    yield "stage", STAGES["math"]
    results = execute_all(plan, scenario, ds, done, budget)
    if results and all(r.facts.get("unavailable") for r in results):     # My data mode: needs school data
        yield "text", NOT_AVAILABLE
        timings["execute_s"] = round(time.perf_counter() - t, 3)
        yield "answer", finish(NOT_AVAILABLE, ans_mode="unavailable")
        return
    pack = build_pack(results, ds, plan, scenario)
    lead = _verdict_result(results)
    label = verdict_label(lead)
    actions = actions_for_all(plan, results, ds, scenario)
    fixes = list({(f.kind, f.name): f for r in results for f in r.fixes}.values())
    required = required_facts(plan, results, pack, ds, scenario)
    general = all(r.tool == "general_info" for r in results)
    quick = quick_answer(plan, results, pack, ds, scenario, required) or ""
    timings["execute_s"] = round(time.perf_counter() - t, 3)
    if quick:
        timings["quick_s"] = round(time.perf_counter() - t0, 2)
        yield "quick", quick

    # EXPLAIN + CHECK. Fast: Lightning, thinking off (then Super, thinking off). Think harder: Super, thinking on
    # (then Lightning, thinking on). One rewrite per model at most. If no AI answer passes, the quick answer stays.
    yield "stage", STAGES["explain"]
    t = time.perf_counter()
    names, private = merchant_accounts(ds), private_amounts(ds) if general else None
    events = None if general else event_dates(ds, scenario)
    aid = ds.opportunities if any((r.tool or plan.tool) == "find_aid" for r in results) else False   # never certain
    web = any((r.tool or plan.tool) == "search_scholarships" for r in results)
    messages = explain_messages(plan.resolved_question or question, plan, results, pack, label, required, general)
    text, reasoning, check, answered_by, missing, errors = "", "", None, None, [], []
    for model, thinking in chain:
        try:
            text, reasoning, check, missing = yield from _explain_with(
                llm, model, thinking, messages, pack, retries, required, names=names, general=general,
                private=private, events=events, aid=aid, web=web)
            answered_by = model
            break
        except Exception as exc:
            errors.append(f"{model_name(model)}: {type(exc).__name__}")
            yield "restart", ""
    if answered_by is not None and missing and check.ok:  # passed every check but left facts out: add them ourselves
        text = append_facts(text, missing)
        retries["facts_appended"] = len(missing)
        check = check_answer(text, pack, require_format=True, names=names, general=general, private=private,
                             required=required, events=events, aid=aid, web=web)
    passed = answered_by is not None and check.ok
    if passed:
        source = "llm"
        if errors:
            notes.append(f"{model_name(chain[0][0])} wasn't available ({'; '.join(errors)}), so "
                         f"{model_name(answered_by)} wrote this answer.")
        if missing:
            yield "restart", ""
            yield "text", text
    else:
        source = "template"
        if answered_by is not None:
            notes.append("The AI answer didn't pass Runway's checks (" + "; ".join(check.problems[:3]) + "), so this "
                         "is the quick answer built straight from your numbers.")
        elif general:
            notes.append(f"General info isn't available right now ({'; '.join(errors)}).")
        else:
            notes.append(f"The AI explanation isn't available right now ({'; '.join(errors)}), so this is the quick "
                         "answer built straight from your numbers.")
        text = quick or ("I can't look that up right now. Try again in a minute." if general else OFF_TOPIC)
        missing = missing_facts(text, required)
        check = check_answer(text, pack, names=names, general=general, private=private, required=required,
                             events=events, aid=aid, web=web)
        reasoning = reasoning if answered_by is not None else ""
        yield "restart", ""
    facts_record = [{"key": f.key, "label": f.label, "appended": f in missing} for f in required]
    models["answered_by"] = answered_by if passed else "template"
    models["explain_errors"] = errors
    timings["explain_s"] = round(time.perf_counter() - t, 2)
    answer = finish(text, lead.verdict, label, pack, check, reasoning, actions, fixes,
                    ans_mode="fallback" if source == "template" or plan.source == "keywords" else "live",
                    source=source)
    if answer.mode == "live" and check.ok and not private:
        save_cached(answer, scenario, history=history, done=done, budget=budget)
    yield "answer", answer


def ask(question, scenario=None, **kwargs):
    """run() without the progress events: returns the Answer."""
    answer = None
    for kind, payload in run(question, scenario, **kwargs):
        if kind == "answer":
            answer = payload
    return answer
