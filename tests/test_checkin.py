"""The check-in: attention items in plain words, the greeting line (fixed or AI, checked), and what Runway
prepares for each item. No network: the AI greeting uses a fake model."""
from types import SimpleNamespace

import pytest

import actions
import engine
import greeting
import normalize


@pytest.fixture(scope="module")
def ds():
    return normalize.load()


@pytest.fixture(scope="module")
def items(ds):
    return engine.attention_items(engine.Scenario(), ds)


def test_item_wording_for_maya(items):
    assert [actions.text(it) for it in items] == [
        ("Send your verification form", "Send it, and your $1,850 refund arrives around Thu, Nov 5."),
        ("Rent is due Sun, Nov 1", "After the $725 rent, you'll have just $13.32 left. Last time, rent before "
                                   "payday cost a $35 fee."),
        ("Card payment on Mon, Nov 9", "The $360 payment takes you to $59.84 below zero."),
        ("A tight week is coming", "A $200 tuition payment is due Fri, Nov 20, $85.30 more than your Wed, Nov 18 "
                                   "paycheck."),
        ("You pay for 2 music apps", "Cancel Spotify before Sat, Nov 14 to keep $23.98 this semester."),
    ]


def test_item_wording_cites_every_number(items):
    pack = SimpleNamespace(cite=lambda c: f"[{c.id}]")
    _, sentence = actions.text(items[0], cite=pack.cite)
    f = items[0].facts
    assert f"$1,850 refund [{f['refund'].id}]" in sentence and f"Thu, Nov 5 [{f['arrives'].id}]" in sentence


class FakeChat:
    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls = text, error, []

    def chat(self, messages, thinking=False, **kwargs):
        self.calls.append((thinking, kwargs.get("model")))
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text)


def test_greeting_ai_line_is_checked_and_falls_back(items):
    good = FakeChat("You've got this. Start with the form and take it one step at a time.")
    assert greeting.ai_line(items, good) == good.text and good.calls == [(False, greeting.config.NVIDIA_PLAN_MODEL)]
    for bad in ("Send the form so your $1,850 arrives Thu, Nov 5.",                 # numbers: the cards show them
                "Send it, and your refund arrives around soon.",                    # copies the first card
                "Start with the form because the refund is " + "really " * 30 + "great.",   # too long
                "Start with the form and then"):                                    # cut off
        assert greeting.ai_line(items, FakeChat(bad)) is None, bad
    assert greeting.ai_line(items, FakeChat(error=TimeoutError())) is None
    assert greeting.fallback(items) == "Start with the first one. It's the most urgent."
    assert greeting.fallback([]) == "Nothing needs you right now. Nice work."


def test_greeting_is_off_in_tests_and_replay(monkeypatch):
    assert not greeting.enabled()                       # conftest: AI_GREETING off
    monkeypatch.setattr(greeting.config, "AI_GREETING", True)
    monkeypatch.setattr(greeting.config, "ANSWER_MODE", "replay")
    assert not greeting.enabled()


# --- what Runway prepares --------------------------------------------------------------------------------

def parse_ics(text):
    """A strict little RFC 5545 reader: CRLF lines of at most 75 octets, folded lines unfolded, BEGIN/END
    balanced. Returns [{property: value}] for each VEVENT (with "ALARMS": [...])."""
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", "")
    raw = text.split("\r\n")[:-1]
    assert all(len(x.encode("utf-8")) <= 75 for x in raw), "line longer than 75 octets"
    lines = []
    for x in raw:
        if x.startswith(" "):
            lines[-1] += x[1:]
        else:
            lines.append(x)
    stack, events, cur, alarm = [], [], None, None
    for x in lines:
        name, _, value = x.partition(":")
        if name == "BEGIN":
            stack.append(value)
            if value == "VEVENT":
                cur = {"ALARMS": []}
            elif value == "VALARM":
                alarm = {}
        elif name == "END":
            assert stack.pop() == value
            if value == "VEVENT":
                events.append(cur)
            elif value == "VALARM":
                cur["ALARMS"].append(alarm)
        else:
            target = alarm if stack[-1] == "VALARM" else cur if stack[-1] == "VEVENT" else {}
            target[name] = (value.replace(r"\n", "\n").replace(r"\,", ",").replace(r"\;", ";")
                            .replace("\\\\", "\\"))
    assert not stack and lines[0] == "BEGIN:VCALENDAR" and "VERSION:2.0" in lines and \
        any(x.startswith("PRODID:") for x in lines)
    return events


def test_calendar_files_parse_back(items):
    from datetime import datetime, timezone
    now = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)
    events = parse_ics(actions.all_deadlines(items, now))
    got = {e["SUMMARY"]: e for e in events}
    assert list(got) == ["Send verification form to financial aid", "Rent due ($725)", "Card payment ($360)",
                         "Tuition payment due ($200)", "Cancel Spotify before Sat, Nov 14"]
    form = got["Send verification form to financial aid"]
    assert (form["DTSTART"], form["DTEND"]) == ("20261027T090000", "20261027T093000")      # Tue, Oct 27, 9:00 AM
    assert got["Cancel Spotify before Sat, Nov 14"]["DTSTART"] == "20261113T090000"        # the day before
    assert got["Rent due ($725)"]["DTSTART;VALUE=DATE"] == "20261101"
    assert got["Rent due ($725)"]["DESCRIPTION"] == "After rent you'll have $13.32 in checking."
    assert got["Card payment ($360)"]["DTSTART;VALUE=DATE"] == "20261109"
    for e in events:
        assert e["UID"].endswith("@runway.example") and e["DTSTAMP"] == "20261026T140000Z"
        assert e["ALARMS"] and e["ALARMS"][0]["ACTION"] == "DISPLAY" and e["ALARMS"][0]["TRIGGER"].startswith("-PT")
    assert len({e["UID"] for e in events}) == len(events)
    refund = parse_ics(actions.ics([actions.reminder(items[0])]))[0]
    assert refund["DESCRIPTION"] == "Your $1,850 refund is on hold until financial aid gets it."     # "\," unescaped
    one = actions.for_item(items[0], normalize.load())[1]
    assert one.kind == "calendar" and one.file_name == "runway-refund.ics" and len(parse_ics(one.data)) == 1


def test_long_lines_are_folded():
    long = actions.Reminder("x", "A" * 200, items_day(), note="é" * 100)
    text = actions.ics([long])
    assert parse_ics(text)[0]["SUMMARY"] == "A" * 200 and parse_ics(text)[0]["DESCRIPTION"] == "é" * 100


def items_day():
    from datetime import date
    return date(2026, 11, 1)


def test_email_is_a_mailto_link_with_subject_and_body(ds, items):
    from urllib.parse import parse_qs, unquote, urlsplit
    email, cal = actions.for_item(items[0], ds)
    assert email.kind == "email" and email.label == "Open in my email app" and cal.kind == "calendar"
    u = urlsplit(email.url)
    assert u.scheme == "mailto" and unquote(u.path) == "finaid@stateu.example"
    q = parse_qs(u.query)
    assert q["subject"] == ["2026-27 Verification Worksheet (Dependent) for Fall 2026, Maya Rivera"]
    assert q["body"][0] == email.data.replace("\n", "\r\n")                    # CRLF line breaks (RFC 6068)
    assert "+" not in u.query and " " not in email.url                        # spaces are %20, not +
    assert "My Fall 2026 refund of $1,850.00 is on hold" in email.data
    assert actions.AID_EMAIL.endswith(".example")                             # reserved, obviously fictional


def test_cancel_links_are_the_official_pages(ds, items):
    subs = next(it for it in items if it.kind == "subscriptions")
    cancel, cal = actions.for_item(subs, ds)
    assert (cancel.kind, cancel.url) == ("cancel", "https://www.spotify.com/account/subscription/manage/")
    assert actions.CANCEL_PAGES["Apple Music"][0] == "https://support.apple.com/en-us/118399"
    assert cal.kind == "calendar"
    assert [a.kind for a in actions.for_item(next(it for it in items if it.kind == "rent"), ds)] == ["calendar"]


def test_done_messages_come_from_the_engine(ds, items):
    form, spotify = items[0], next(it for it in items if it.kind == "subscriptions")
    sent = engine.Scenario(refund_released=True, refund_submit_date=actions.config.DEMO_TODAY)
    assert actions.done_message(form, ds, sent) == (
        "Nice. With the form sent, your refund should arrive around Wed, Nov 4. Your money now lasts all semester. "
        "Your lowest point is $5.81 on Mon, Nov 2.")
    only_spotify = engine.Scenario(cancel_subscriptions=("Spotify",))
    assert actions.done_message(spotify, ds, only_spotify) == (
        "Nice. With Spotify cancelled, you keep $23.98 this semester. Your money now lasts until Mon, Nov 9.")
    rent = items[1]
    assert actions.done_message(rent, ds, engine.Scenario(), 3) == \
        "Got it. Rent is due Sun, Nov 1: marked done. 3 things still need you."
    assert actions.done_message(rent, ds, engine.Scenario(), 0).endswith("You're all caught up.")


def test_greeting_rejects_false_links_between_items(items):
    for bad in ("Tackle the form first so your refund lands before rent hits.",       # seen live: refund is after rent
                "Start with the form, then your card payment is easy.",
                "Send the form because it covers everything."):
        assert greeting.ai_line(items, FakeChat(bad)) is None, bad
    assert greeting.ai_line(items, FakeChat("You've got this. Start with the form.")) is not None
