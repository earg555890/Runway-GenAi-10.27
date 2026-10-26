"""The Budget tab's top line: one deterministic sentence about where the money went, and an optional short summary
by the fast model, checked like any answer (every amount must be one of the spending totals; only categories she
actually spent on; short, finished, no repeats). The UI shows the sentence at once and never waits for the model.

    sp = engine.spending_by_category(start, end, account, ds)
    summary.sentence(sp, period)          # "So far in October, you spent $1,757. Most went to Rent ($725) and ..."
"""
import re
from dataclasses import dataclass
from datetime import date, timedelta

import agent
import config
import llm_client
import normalize
import wording as w

TIMEOUT_S = 20
MAX_WORDS = 45


@dataclass(frozen=True)
class Period:
    key: str
    label: str                   # "Oct"
    start: date
    end: date                    # may be after DEMO_TODAY (Nov, Dec): nothing spent yet

    @property
    def words(self):
        """"in October", "so far in October", "this semester"."""
        if self.key == "semester":
            return "this semester"
        name = f"{self.start:%B}"
        return f"so far in {name}" if self.start <= config.DEMO_TODAY < self.end else f"in {name}"

    @property
    def future(self):
        return self.start > config.DEMO_TODAY


def periods():
    """Each month from the semester start (her first day in My data mode) to its end, then the whole semester."""
    out, d = [], config.SEMESTER_START.replace(day=1)
    while d <= config.SEMESTER_END:
        last = (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        out.append(Period(f"{d:%Y-%m}", f"{d:%b}" + ("" if d.year == 2026 else f" {d:%y}"), d, last))
        d = last + timedelta(days=1)
    return out + [Period("semester", "This semester", config.SEMESTER_START, config.SEMESTER_END)]


PERIODS = periods()                     # Maya's: Aug - Dec 2026 and the semester
ACCOUNT_WORDS = {"both": "", "checking": " from checking", "card": " on the card"}


def period(key):
    return next((p for p in periods() if p.key == key), None) or next(p for p in periods() if p.key == "semester")


def _cap(s):
    return s[0].upper() + s[1:]


def sentence(sp, per):
    """One plain sentence (two at most) about where the money went."""
    where = ACCOUNT_WORDS[sp.account]
    if per.future:
        return f"Nothing spent yet in {per.start:%B}: it hasn't started."
    if not sp.categories:
        return _cap(f"{per.words}, you spent nothing{where}.")
    head = _cap(f"{per.words}, you spent {w.dollars(sp.total.value)}{where}.")
    top = sp.categories[:2]
    if len(sp.categories) == 1:
        return f"{head} All of it went to {top[0].name}."
    return (f"{head} Most went to {top[0].name} ({w.dollars(top[0].spent.value)}) and {top[1].name} "
            f"({w.dollars(top[1].spent.value)}).")


SYSTEM = ("You are Runway, a friendly money coach for a college student named Maya. In at most two short sentences "
          "(under 40 words), say where her money went and the one thing worth noticing. Use only the amounts below, "
          "rounded like \"$461\" (keep cents under $100, like \"$81.32\"). No new numbers, no percentages, no dates, "
          "no advice about rent or school, no headings, no lists.")


def messages(sp, per):
    lines = [f"- {c.name} ({c.kind}): {w.dollars(c.spent.value)}" for c in sp.categories]
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Spending {per.words}{ACCOUNT_WORDS[sp.account]}: "
                                        f"{w.dollars(sp.total.value)} in all.\n" + "\n".join(lines)
                                        + "\n\nWrite the summary."}]


def check(text, sp):
    """Problems with an AI summary ([] = fine)."""
    if not text.strip():
        return ["empty"]
    allowed = {sp.total.value} | {c.spent.value for c in sp.categories}
    rounded = {agent._rounded(v) for v in allowed}
    problems = [f"{x.strip()} is not one of the totals" for x, v in agent.find_amounts(text)
                if abs(v) not in allowed and not ("." not in x and abs(v) in rounded)]
    problems += [f"{x.strip()} is a date" for x, _, _ in agent.find_dates(text)]
    if "%" in text or re.search(r"\bpercent\b", text, re.I):
        problems.append("a percentage")
    spent = {c.name.lower() for c in sp.categories}
    problems += [f"names {name}, which she didn't spend on" for name in normalize.SPENDING_OUT
                 if name.lower() not in spent and re.search(r"\b" + re.escape(name.lower()) + r"\b", text.lower())]
    if text.rstrip()[-1] not in ".!":
        problems.append("not a finished sentence")
    if len(text.split()) > MAX_WORDS or text.count(".") + text.count("!") > 3:
        problems.append("too long")
    problems += ["record ID"] if agent.RECORD_ID.search(text) else []
    return problems + agent.repetition_problems(text) + agent.cutoff_problems(text)


def enabled():
    return config.AI_GREETING and bool(config.NVIDIA_API_KEY) and config.ANSWER_MODE != "replay"


def ai_summary(sp, per, llm=llm_client):
    """The model's summary if it passes the check, else None. One call, fast model, thinking off."""
    if per.future or not sp.categories:
        return None
    try:
        res = llm.chat(messages(sp, per), thinking=False, model=config.general_model(), timeout=TIMEOUT_S,
                       retries=0, max_tokens=160)
    except Exception:
        return None
    text = " ".join((res.text or "").split()).strip().strip('"')
    return text if not check(text, sp) else None


def budget_effect_line(effect):
    """What sticking to the budget does to the forecast, in one or two sentences, from engine.budget_effect."""
    w_out, w_in = effect.without, effect.with_budget
    days = effect.days_longer.value
    if w_in.lasts_through_semester and w_out.lasts_through_semester:
        change = effect.end_change.value
        more = (f"You'd end the semester with {w.dollars(change)} more." if change > 0 else
                f"You'd end the semester with {w.dollars(change)} less, because your usual spending is more than "
                "the forecast assumes." if change < 0 else "")
        return f"Your money lasts all semester either way. {more}".strip()
    if w_in.lasts_through_semester:
        return "If you stick to this budget, your money lasts all semester."
    when = w.day(w_in.first_below_zero.value)
    if days and days > 0:
        return f"If you stick to this budget, your money lasts until {when} ({days} days longer)."
    if days and days < 0:
        return f"With this budget, your money runs out on {when} ({-days} days sooner)."
    low = effect.lowest_change.value
    return (f"Your money still runs out on {when}." + (f" But your lowest point is {w.dollars(low)} higher." if low > 0
                                                        else f" Your lowest point is {w.dollars(low)} lower." if low < 0
                                                        else ""))
