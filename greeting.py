"""The check-in's one friendly line under "Hi Maya. N things need your attention."

The fast model may write it (one call, thinking off, short timeout); the line is checked like any answer, with a
stricter number rule: the cards below it already state every amount and date, so the line may state none. One or
two short sentences, not a copy of an item, no repeats, not cut off. If anything fails, or there is no key, the deterministic line is used. The UI never waits for it."""
import difflib

import agent
import config
import llm_client
from actions import text

MAX_WORDS = 30
TIMEOUT_S = 20

SYSTEM = ("You are Runway, a warm money coach for a stressed college student named Maya. Write ONE short, "
          "encouraging sentence (under 20 words) in your own words that nudges her to start with the first item "
          "below. The cards under your sentence already show every amount and date, so use NO numbers, amounts or "
          "dates, and don't copy the item text. Never claim one item pays for, covers or fixes another. No greeting "
          "word like Hi, no lists.")


def fallback(items):
    if not items:
        return "Nothing needs you right now. Nice work."
    return "Start with the first one. It's the most urgent."


def messages(items):
    lines = [f"{i}. {t}: {s}" for i, (t, s) in enumerate((text(it) for it in items[:3]), start=1)]
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "Items, most urgent first:\n" + "\n".join(lines) + "\n\nWrite the sentence."}]


def check(line, items):
    """Problems with an AI greeting line ([] = fine): no amounts or dates at all (the cards show them), short,
    not a copy of an item, no repeats, not cut off."""
    if not line.strip():
        return ["empty"]
    problems = [f"{x.strip()} is a number; the cards show the numbers" for x, _ in agent.find_amounts(line)]
    problems += [f"{x.strip()} is a date; the cards show the dates" for x, _, _ in agent.find_dates(line)]
    if any(ch.isdigit() for ch in line):
        problems.append("has a number")
    if line.rstrip()[-1] not in ".!":
        problems.append("not a finished sentence")
    if len(line.split()) > MAX_WORDS:
        problems.append("too long")
    if line.count(".") + line.count("!") + line.count("?") > 2:
        problems.append("more than two sentences")
    norm = " ".join(line.lower().split())
    for it in items[:3]:
        for part in text(it):
            if difflib.SequenceMatcher(None, norm, " ".join(part.lower().split())).ratio() >= 0.7:
                problems.append("copies an item")
                break
    return problems + agent.repetition_problems(line) + agent.cutoff_problems(line)


def enabled():
    return config.AI_GREETING and bool(config.NVIDIA_API_KEY) and config.ANSWER_MODE != "replay"


def ai_line(items, llm=llm_client):
    """The model's line if it passes the check, else None. One call, fast model, thinking off."""
    if not items:
        return None
    try:
        res = llm.chat(messages(items), thinking=False, model=config.NVIDIA_PLAN_MODEL, timeout=TIMEOUT_S, retries=0,
                       max_tokens=120)
    except Exception:                       # slow, down, or no key: the fixed line stays
        return None
    line = " ".join((res.text or "").split()).strip().strip('"')
    return line if not check(line, items) else None
