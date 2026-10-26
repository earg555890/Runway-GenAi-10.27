"""Fast-mode answer quality fixes, with the exact failing texts from the overnight eval (Oct 25-26):
the repetition repair (drop a repeated line, change no words), the assumption only in NOTE, and minus-sign
balances as a check failure with a clear rewrite message."""
import pytest

import agent
import engine
import normalize
from test_agent import FakeLLM

HEADPHONES_Q = "Can I afford new headphones for $150?"
HEADPHONES_PLAN = ('{"calls": [{"tool": "can_afford", "args": {"item": "headphones", "cost": 150, '
                   '"account": "checking"}}]}')

# Nemotron Lightning's first answer to the headphones question in the overnight eval (verbatim).
HEADPHONES_BAD = """ANSWER: Not right now [C1].
WHY:
- Your lowest point would be $144 below zero [C4] on Mon, Nov 2.
- Even with every available fix (refund released, Spotify) it is -$144.19 on Mon Nov 2, 2026.
- You didn't say when you'd buy it, so I assumed tomorrow, Tue, Oct 27.
NOTE: You didn't say when you'd buy it, so I assumed tomorrow, Tue, Oct 27. Cancelling Apple Music saves $0.00 [C7] this semester: Apple Music is billed to the credit card, and that card bill is paid after the semester ends.
DO THIS:
1. Wait for the refund to release on Thu Nov 5, 2026.
2. Cancel Spotify to save $23.98 [C8] before the semester ends.
NOTE: You didn't say when you'd buy it, so I assumed tomorrow, Tue, Oct 27."""

# Its second answer to "How many meal swipes will I have left at the end of the semester?" (the repeat failure).
MEAL_REPEAT = """ANSWER: Your dining dollars run out around Sun, Nov 22 [C10]. You'll have about 40 swipes left on Fri, Dec 18 [C11]. Checking pays $0.00 for meals [C12].
WHY:
- Dining dollars left after use so far is $117.00 [C3].
- You'll have about 40 swipes left on Fri, Dec 18 [C11].
- Your dining dollars run out around Sun, Nov 22 [C10].
DO THIS:
1. Check your dining-dollar balance before each campus meal.
NOTE: Assumes no new dining-dollar purchases this semester."""


@pytest.fixture(scope="module")
def ds():
    return normalize.load("local")


def test_remove_repeats_keeps_the_first_and_changes_no_words():
    fixed = agent.remove_repeats(MEAL_REPEAT)
    assert agent.repetition_problems(MEAL_REPEAT) and not agent.repetition_problems(fixed)
    assert fixed.splitlines() == [line for line in MEAL_REPEAT.splitlines()
                                  if line not in ("- You'll have about 40 swipes left on Fri, Dec 18 [C11].",
                                                  "- Your dining dollars run out around Sun, Nov 22 [C10].")]
    assert set(fixed.split()) <= set(MEAL_REPEAT.split())                       # nothing added or reworded


def test_remove_repeats_drops_a_repeated_note_and_sentence():
    text = ("ANSWER: Not right now [C1].\nWHY:\n- Your lowest point is $144 below zero [C4].\n"
            "- Rent is due Sun, Nov 1 [C5]. Your lowest point is $144 below zero [C4].\n"
            "NOTE: Your lowest point is $144 below zero.")
    assert agent.remove_repeats(text) == ("ANSWER: Not right now [C1].\nWHY:\n- Your lowest point is $144 below "
                                          "zero [C4].\n- Rent is due Sun, Nov 1 [C5].")


def _run(llm, ds, q=HEADPHONES_Q):
    return list(agent.run(q, engine.Scenario(), ds=ds, mode="live", llm=llm, typing_s=0))[-1][1]


def test_repeat_only_failures_are_repaired_without_a_rewrite(ds, tmp_path, monkeypatch):
    monkeypatch.setattr(agent.config, "ANSWER_CACHE_DIR", tmp_path)
    plan = '{"calls": [{"tool": "meal_plan", "args": {}}]}'
    llm = FakeLLM(plans=[plan], answers=[MEAL_REPEAT])
    a = _run(llm, ds, "How many meal swipes will I have left at the end of the semester?")
    assert a.retries.get("repaired") == "removed duplicate line" and not a.retries.get("explain_rewrite")
    assert a.explain_source == "llm" and a.check["ok"]
    assert a.text.count("40 swipes left") == 1
    assert [c for c in llm.calls if c[0] == "explain"] == [("explain", False)]          # no second EXPLAIN call


def test_the_overnight_headphones_answer_fails_with_clear_messages(ds, tmp_path, monkeypatch):
    monkeypatch.setattr(agent.config, "ANSWER_CACHE_DIR", tmp_path)
    llm = FakeLLM(plans=[HEADPHONES_PLAN], answers=[HEADPHONES_BAD, HEADPHONES_BAD])
    a = _run(llm, ds)
    assert a.explain_source == "template" and a.text.startswith("ANSWER: Not right now")   # the quick answer stays
    assert not a.retries.get("repaired")                                       # more than a repeat: no repair
    rewrite = llm.messages[1][1][-1]["content"]
    assert "-$144.19 has a minus sign" in rewrite
    assert "write every balance below zero as \"$144 below zero\"" in rewrite
    assert "the assumption is outside NOTE" in rewrite
    assert "keep it only as the NOTE line" in rewrite


def test_assumption_only_in_note_passes(ds, tmp_path, monkeypatch):
    monkeypatch.setattr(agent.config, "ANSWER_CACHE_DIR", tmp_path)
    good = ("ANSWER: Not right now [C1].\nWHY:\n- Your lowest point would be $144 below zero [C4] on Mon, Nov 2.\n"
            "- Cancelling Spotify saves $23.98 [C8] this semester.\nDO THIS:\n1. Try a later date, after your refund "
            "arrives.\nNOTE: You didn't say when you'd buy it, so I assumed tomorrow, Tue, Oct 27.")
    llm = FakeLLM(plans=[HEADPHONES_PLAN], answers=[good])
    a = _run(llm, ds)
    assert a.explain_source == "llm" and a.check["ok"], a.check
    assert not a.retries.get("explain_rewrite") and a.text.count("I assumed tomorrow") == 1


def test_prompt_rules():
    assert "write it ONCE, in NOTE only" in agent.EXPLAIN_SYSTEM
    assert "is a balance below zero" in agent.EXPLAIN_SYSTEM
