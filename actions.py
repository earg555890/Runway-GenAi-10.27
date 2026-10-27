"""The check-in and its actions: plain words for each attention item (engine.attention_items), and what Runway
prepares for the student to approve: calendar reminders (.ics), an email (mailto: link + text to copy), the
official page to cancel a subscription, and "mark as done". Nothing here sends anything or does money math.

    items = engine.attention_items(scenario, ds)
    title, sentence = actions.text(items[0])                 # cite=pack.cite adds [C#] after each number
    actions.for_item(items[0], ds)                           # [Action(kind="email" | "calendar" | "cancel", ...)]
    actions.ics([actions.reminder(it) for it in items])     # one .ics file with every deadline
"""
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

import config
import engine
import wording as w

AID_EMAIL = "finaid@stateu.example"           # synthetic: .example is a reserved domain (RFC 2606)

# Official cancel pages, from each service's own help docs (checked Oct 24, 2026):
# Spotify's "How to cancel Premium plans" (support.spotify.com/us/article/cancel-premium/) links "Manage your
# plan" to the URL below. Apple's "How to cancel Apple Music" (support.apple.com/en-us/118399) gives steps on
# music.apple.com but no direct cancel URL, so Runway links to that help page.
CANCEL_PAGES = {
    "Spotify": ("https://www.spotify.com/account/subscription/manage/", "Open Spotify's cancel page"),
    "Apple Music": ("https://support.apple.com/en-us/118399", "How to cancel Apple Music (Apple help)"),
}

DONE_LABELS = {"refund": "Form sent", "rent": "Got it", "run_out": "Got it", "tight_week": "Got it",
               "grant": "Applied", "meal_plan": "Got it"}
REMINDER_TIME = time(9, 0)


def _none(_):
    return ""


def _c(cite, computed):
    mark = cite(computed)
    return f" {mark}" if mark else ""


def text(item, cite=_none):
    """(title, one sentence with the key numbers). cite: pack.cite for chat answers ([C#] after each number)."""
    f, k = item.facts, item.kind
    if k == "refund":
        return ("Send your verification form",
                f"Send it, and your {w.dollars(f['refund'].value)} refund{_c(cite, f['refund'])} arrives around "
                f"{w.day(f['arrives'].value)}{_c(cite, f['arrives'])}.")
    if k == "rent":
        return (f"Rent is due {w.day(item.due.value)}",
                f"After the {w.dollars(f['rent'].value)} rent{_c(cite, f['rent'])}, you'll have just "
                f"{w.balance(f['left'].value)}{_c(cite, f['left'])} left. Last time, rent before payday cost a "
                f"{w.dollars(f['fee'].value)} fee{_c(cite, f['fee'])}.")
    if k == "run_out":
        if "payment" in f:
            return (f"Card payment on {w.day(item.due.value)}",
                    f"The {w.dollars(f['payment'].value)} payment{_c(cite, f['payment'])} takes you to "
                    f"{w.balance(f['after'].value)}{_c(cite, f['after'])}.")
        return (f"Money runs out {w.day(item.due.value)}",
                f"Everyday spending takes you below zero on {w.day(item.due.value)}{_c(cite, item.due)}.")
    if k == "subscriptions":
        return (f"You pay for {f['count'].value} music apps",
                f"Cancel {f['pick'].value} before {w.day(item.due.value)}{_c(cite, item.due)} to keep "
                f"{w.dollars(f['saves'].value)}{_c(cite, f['saves'])} this semester.")
    if k == "grant":
        return (f"You may qualify for a {w.dollars(f['amount'].value)} emergency grant",
                f"It's decided in about {f['decision_days'].value} days{_c(cite, f['decision_days'])}. Apply by "
                f"{w.day(item.due.value)}{_c(cite, item.due)} and, if approved, it arrives before "
                f"{w.day(f['runs_out'].value)}{_c(cite, f['runs_out'])}.")
    if k == "meal_plan" and "per" in f:                 # her own day or week plan
        word = "meals" if f["kind"] == "meals" else "points"
        return (f"Your {word} run short around {w.day(item.due.value)}",
                f"At your pace, you run short {f['short_periods'].value} of {f['periods_left'].value} "
                f"{f['per']}s{_c(cite, f['short_periods'])}. Checking would pay about {w.dollars(f['cost'].value)}"
                f"{_c(cite, f['cost'])} for meals (estimated).")
    if k == "meal_plan":
        return (f"Your dining dollars run out around {w.day(item.due.value)}",
                f"You'll have about {f['swipes_end'].value:.0f} swipes{_c(cite, f['swipes_end'])} left on "
                f"{w.day(config.SEMESTER_END)}. Use 2 swipes a week instead, and both last.")
    if k == "tight_week":
        return ("A tight week is coming",
                f"A {w.dollars(f['installment'].value)} tuition payment{_c(cite, f['installment'])} is due "
                f"{w.day(f['installment_due'].value)}. That's {w.dollars(f['shortfall'].value)}"
                f"{_c(cite, f['shortfall'])} more than your {w.day(f['paycheck_date'].value)} paycheck.")
    return (k, "")


LABELS = {"refund": "the verification form and when the refund arrives", "rent": "the rent and what it leaves",
          "run_out": "the card payment and where it takes you", "subscriptions": "the subscription to cancel",
          "tight_week": "the tuition payment in the tight week",
          "grant": "the emergency grant (if approved) and when to apply", "meal_plan": "when the dining dollars run out"}


def line(item, cite=_none):
    """One self-contained line for a chat answer (the card's title and sentence in one)."""
    f, k = item.facts, item.kind
    if k == "refund":
        return (f"Send your verification form: your {w.dollars(f['refund'].value)} refund{_c(cite, f['refund'])} "
                f"then arrives around {w.day(f['arrives'].value)}{_c(cite, f['arrives'])}.")
    if k == "rent":
        return (f"Rent of {w.dollars(f['rent'].value)}{_c(cite, f['rent'])} is due {w.day(item.due.value)}"
                f"{_c(cite, item.due)} and leaves you just {w.balance(f['left'].value)}{_c(cite, f['left'])}. "
                f"Last time, rent before payday cost a {w.dollars(f['fee'].value)} fee{_c(cite, f['fee'])}.")
    if k == "run_out" and "payment" in f:
        return (f"Your {w.dollars(f['payment'].value)} card payment{_c(cite, f['payment'])} on "
                f"{w.day(item.due.value)}{_c(cite, item.due)} takes you to {w.balance(f['after'].value)}"
                f"{_c(cite, f['after'])}.")
    return text(item, cite)[1]


def step(item):
    """The one thing to do, as a short imperative (chat DO THIS and to-do lists)."""
    f = item.facts
    return {"refund": "Send your verification form to financial aid.",
            "rent": f"Keep {w.dollars(f['rent'].value)} in checking for rent on {w.day(item.due.value)}."
            if "rent" in f else "Keep rent money in checking.",
            "run_out": f"Plan for the card payment on {w.day(item.due.value)}.",
            "subscriptions": f"Cancel {f['pick'].value} before {w.day(item.due.value)}." if "pick" in f else "",
            "tight_week": f"Set money aside for tuition on {w.day(item.due.value)}.",
            "grant": f"Apply for the emergency grant by {w.day(item.due.value)}.",
            "meal_plan": ("Use 2 swipes a week instead of dining dollars." if "per" not in f else
                          f"Plan for about {w.dollars(f['cost'].value)} for meals from checking (estimated).")
            }.get(item.kind, "")


def application(check, ds, situation=""):
    """(to, subject, body) for an aid application, in plain words, with what the application needs. Runway never
    sends it. situation: one true sentence about why she's applying, built from the engine (or empty)."""
    o = check.opp
    reqs = [r for r in ds.opp_requirements if r.opp_id == o.row_id]
    prof = ds.profile
    subject = f"Application: {o.name}, {w.STUDENT_NAME}"
    lines = [f"Hello,", "",
             f"I'm {w.STUDENT_NAME} (student ID: [your student ID]), a {prof.enrollment} {prof.class_year} majoring "
             f"in {prof.major}. I'd like to apply for the {o.name}."]
    if situation:
        lines += ["", situation]
    if reqs:
        lines += ["", "I've attached:"] + [f"- {r.item} ({r.details.lower()})" for r in reqs]
    lines += ["", "Please let me know if you need anything else.", "", "Thank you,", w.STUDENT_NAME]
    return AID_EMAIL, subject, "\n".join(lines)


def done_label(item):
    return f"Cancelled {item.fix[1]}" if item.kind == "subscriptions" else DONE_LABELS.get(item.kind, "Done")


# --- what Runway prepares --------------------------------------------------------------------------------
@dataclass
class Action:
    kind: str                    # "email", "calendar", "cancel"
    label: str
    url: str = ""                # mailto: or the cancel page
    data: str = ""               # .ics text, or the email body to copy
    file_name: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class Reminder:
    uid: str
    title: str
    day: date
    at: time | None = None       # None = all-day
    note: str = ""


def email(ds):
    """The financial aid email: (to, subject, body). Never sent by Runway."""
    refund = next((r for r in ds.refunds if r.status == "HELD"), None)
    reqs = [r for r in ds.requirements if r.status not in ("SATISFIED", "RECEIVED")]
    doc = reqs[0].description if reqs else "the missing document"
    term = w.term_name(refund.term) if refund else "this term"
    amount = w.money(refund.amount) if refund else ""
    subject = f"{doc} for {term}, {w.STUDENT_NAME}"
    body = (f"Hello,\n\nI'm {w.STUDENT_NAME} (student ID: [your student ID]). My {term} refund of {amount} is on "
            f"hold because my file is missing the {doc}. I've attached the completed worksheet.\n\nCould you "
            "confirm you've received it, and let me know if anything else is needed to clear the hold and release "
            f"my refund?\n\nThank you,\n{w.STUDENT_NAME}")
    return AID_EMAIL, subject, body


def mailto(to, subject, body):
    """A mailto: link with the subject and body prefilled (RFC 6068: percent-encoded, CRLF line breaks)."""
    q = urllib.parse.urlencode({"subject": subject, "body": body.replace("\r\n", "\n").replace("\n", "\r\n")},
                               quote_via=urllib.parse.quote)
    return f"mailto:{to}?{q}"


def reminder(item):
    """The calendar reminder for one item."""
    f, d = item.facts, item.due.value
    if item.kind == "refund":
        return Reminder("refund", "Send verification form to financial aid", d, REMINDER_TIME,
                        f"Your {w.dollars(f['refund'].value)} refund is on hold until financial aid gets it.")
    if item.kind == "subscriptions":
        name = f["pick"].value
        return Reminder(f"cancel-{name.lower().replace(' ', '-')}", f"Cancel {name} before {w.day(d)}",
                        d - timedelta(days=1), REMINDER_TIME,
                        f"Cancelling saves {w.dollars(f['saves'].value)} this semester.")
    if item.kind == "rent":
        return Reminder("rent", f"Rent due ({w.dollars(f['rent'].value)})", d,
                        note=f"After rent you'll have {w.balance(f['left'].value)} in checking.")
    if item.kind == "run_out":
        what = f"Card payment ({w.dollars(f['payment'].value)})" if "payment" in f else "Money runs out"
        return Reminder("card-payment" if "payment" in f else "run-out", what, d,
                        note=f"Checking goes to {w.balance(f['after'].value)} that day." if "after" in f else "")
    if item.kind == "grant":
        return Reminder("emergency-grant", "Apply for the emergency grant", d, REMINDER_TIME,
                        f"Up to {w.dollars(f['amount'].value)} if approved. Decided in about "
                        f"{f['decision_days'].value} business days.")
    if item.kind == "meal_plan" and "per" in f:
        return Reminder("meals-short", "Meals run short", d, note="Check your meals and points left in Runway.")
    if item.kind == "meal_plan":
        return Reminder("dining-dollars", "Dining dollars run out", d,
                        note="Use swipes for 2 meals a week so both last the semester.")
    if item.kind == "tight_week":
        return Reminder("tuition", f"Tuition payment due ({w.dollars(f['installment'].value)})", d,
                        note=f"Your paycheck before it is only {w.dollars(f['paycheck_net'].value)}.")
    return Reminder(item.kind, item.kind, d)


def _escape(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line):
    """RFC 5545 line folding: at most 75 octets per line, continuation lines start with a space."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur.decode("utf-8"))
            cur = b""
        cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def ics(reminders, now=None):
    """A standard iCalendar (RFC 5545) file with one event per reminder, each with a pop-up alarm. Timed
    reminders are 30 minutes in local (floating) time; all-day ones remind at 9 AM the day before."""
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Runway//Student money check-in//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH"]
    for r in reminders:
        lines += ["BEGIN:VEVENT", f"UID:{r.uid}-{r.day:%Y%m%d}@runway.example", f"DTSTAMP:{stamp}",
                  f"SUMMARY:{_escape(r.title)}"]
        if r.at:
            start = datetime.combine(r.day, r.at)
            lines += [f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{start + timedelta(minutes=30):%Y%m%dT%H%M%S}"]
            trigger = "-PT15M"
        else:
            lines += [f"DTSTART;VALUE=DATE:{r.day:%Y%m%d}", f"DTEND;VALUE=DATE:{r.day + timedelta(days=1):%Y%m%d}"]
            trigger = "-PT15H"
        if r.note:
            lines.append(f"DESCRIPTION:{_escape(r.note)}")
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_escape(r.title)}", f"TRIGGER:{trigger}",
                  "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


def for_item(item, ds):
    """What Runway prepares for one item (1-2 actions; "mark as done" is always there too)."""
    r = reminder(item)
    cal = Action("calendar", "Add to calendar", data=ics([r]), file_name=f"runway-{r.uid}.ics",
                 extra={"title": r.title, "day": r.day})
    if item.kind == "refund":
        to, subject, body = email(ds)
        return [Action("email", "Open in my email app", mailto(to, subject, body), body,
                       extra={"to": to, "subject": subject}), cal]
    if item.kind == "subscriptions":
        name = item.facts["pick"].value
        url, label = CANCEL_PAGES.get(name, ("", ""))
        return ([Action("cancel", label, url, extra={"name": name})] if url else []) + [cal]
    return [cal]


def all_deadlines(items, now=None):
    """One .ics file with every item's reminder ("Add all deadlines to my calendar")."""
    return ics([reminder(it) for it in items], now)


# --- after "mark as done" -------------------------------------------------------------------------------
def done_message(item, ds, after, remaining=0):
    """Runway's short chat message once the student marks an item done: what it changes, from the engine.
    after: the scenario with everything marked done so far (this item included); remaining: items still open."""
    p = engine.project(after, ds, engine.Ledger())
    if p.lasts_through_semester:
        lasts = (f"Your money now lasts all semester. Your lowest point is {w.balance(p.lowest.value)} on "
                 f"{w.day(p.lowest_date.value)}.")
    else:
        lasts = f"Your money now lasts until {w.day(p.first_below_zero.value)}."
    if item.kind == "refund":
        rel = engine.refund_release_date(ds, after)
        return f"Nice. With the form sent, your refund should arrive around {w.day(rel)}. {lasts}"
    if item.kind == "subscriptions":
        return (f"Nice. With {item.fix[1]} cancelled, you keep {w.dollars(item.facts['saves'].value)} this "
                f"semester. {lasts}")
    return f"Got it. {text(item)[0]}: marked done." + (f" {w.things(remaining)} still need you." if remaining
                                                        else " You're all caught up.")
