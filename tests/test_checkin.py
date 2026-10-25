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
    good = FakeChat("You've got this. Start with the form, then take the rest one step at a time.")
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
