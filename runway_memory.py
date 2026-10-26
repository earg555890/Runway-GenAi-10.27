"""What Runway remembers about Maya across sessions, on the H-MEM engine (hmem.py).

Every memory has provenance (where it came from, when, and the action that created it) and every change is in
H-MEM's append-only trust ledger. Stored locally in .cache/memory/ (gitignored). Remembered:

    done items       "Marked done: Form sent (Send your verification form)."           long_term, from the check-in
    intents          "Drafted the email to financial aid (verification form)."         working, from a draft or reminder
    budget           "Monthly budget: Groceries $185, Eating out $96, ..."             long_term preference, supersedes
    planned shifts   "Plans extra shifts: Sat, Oct 31 (4 hours), Sat, Nov 7 (4 h)."    working, supersedes
    preferences      "Prefers Think harder answers."                                   long_term preference
    conversations    "Asked "Can I afford ...?" Runway: "Yes, if you do 2 things.""    short_term summary, no AI call

Memories are recalled into PLAN only (so follow-ups across sessions work), never into the answer itself: numbers in
an answer always come from the evidence pack. Memories never change the forecast on their own; the check-in asks
("Last time you said you'd send the form. Did you?") and the student decides. Never used for her own data (My data
mode, rule 7).
"""
import time

import config
import hmem

DIR = config.PROJECT_ROOT / ".cache" / "memory"
DOMAINS = {   # Runway's domains for H-MEM's multi-pass classification (AGENTS.md section 5: tune per domain)
    "school": ["aid", "refund", "form", "verification", "grant", "scholarship", "tuition", "bursar", "worksheet"],
    "money": ["budget", "rent", "card", "spotify", "subscription", "groceries", "eating", "shopping", "flight",
              "afford", "balance", "money", "spending"],
    "work": ["shift", "shifts", "hours", "paycheck", "job", "saturday"],
    "personal": ["prefer", "prefers", "like", "dislike"],
}
PLAN_TOP_N = 3
PLAN_THRESHOLD = 0.15   # tuned for Runway (AGENTS.md section 13: tune per domain); the spec default is 0.35


def now_ms():
    return int(time.time() * 1000)


def when_words(ms):
    t = time.localtime(ms / 1000)
    return time.strftime("%a, %b %d, %I:%M %p", t).replace(" 0", " ")


class RunwayMemory:
    def __init__(self, persist_dir=None, clock=now_ms):
        self.engine = hmem.HMEM(clock=clock, persist_dir=persist_dir or DIR, actor="runway",
                                domain_keywords=DOMAINS)

    # --- writing -------------------------------------------------------------------------------------------
    def _add(self, content, source, label, *, type="factual", layer="working", tags=(), origin="manual",
             supersede_tag=None, chat_id=None):
        old = self._current(supersede_tag) if supersede_tag else None
        if old and old.content == content:
            return old
        rec = self.engine.add(content=content, source=source, type=type, layer=layer, tags=list(tags),
                              chat_id=chat_id, supersedes=old.id if old else None,
                              provenance={"origin": origin, "learnedAt": self.engine.clock(), "label": label})
        if old:
            self.engine.store.update(old.id, supersededBy=rec.id)   # kept and penalized, never deleted
        return rec

    def _current(self, tag):
        live = [m for m in self.engine.store.all() if tag in m.tags and not m.superseded_by]
        return max(live, key=lambda m: m.timestamp) if live else None

    def remember_done(self, kind, label, title):
        return self._add(f"Marked done: {label} ({title}).", "checkin:done",
                         f"You clicked “{label}” in the check-in", layer="long_term",
                         tags=["checkin", "done", f"item:{kind}"])

    def remember_undone(self, kind, label, title):
        done = [m for m in self.engine.store.all() if f"item:{kind}" in m.tags and "done" in m.tags
                and not m.superseded_by]
        rec = self._add(f"Undid: {label} ({title}).", "checkin:undo", f"You clicked Undo on “{label}”",
                        tags=["checkin", "undone", f"item:{kind}"])
        for m in done:
            self.engine.store.update(m.id, supersededBy=rec.id)
        return rec

    def remember_intent(self, kind, what):
        return self._add(f"{what}.", "checkin:draft", f"Runway prepared this and you opened it",
                         tags=["checkin", "intent", f"item:{kind}"])

    def remember_budget(self, amounts):
        parts = [f"{c} ${v:,}" for c, v in amounts.items() if v]
        if not parts:
            return None
        return self._add("Monthly budget: " + ", ".join(parts) + ".", "budget", "You set this in the Budget tab",
                         type="preference", layer="long_term", tags=["budget"], supersede_tag="budget")

    def remember_shifts(self, shifts, day_words):
        text = ("Plans extra shifts: " + ", ".join(f"{day_words(s.date)} ({float(s.hours):g} hours)" for s in shifts)
                + ".") if shifts else "No extra shifts planned."
        return self._add(text, "shift_planner", "You set this in the shift planner", tags=["shifts"],
                         supersede_tag="shifts")

    def remember_preference(self, text, key):
        return self._add(text, "settings", "You changed this setting", type="preference", layer="long_term",
                         tags=["preference", f"pref:{key}"], supersede_tag=f"pref:{key}")

    def remember_conversation(self, question, answer_line, chat_id=None):
        """A short summary of one question and Runway's answer line (no AI call: model-free capture, 4.3)."""
        return self._add(f"Asked “{question}” Runway: “{answer_line}”", "chat",
                         "From your chat with Runway", type="general", layer="short_term", tags=["chat"],
                         origin="model_response", chat_id=chat_id)

    # --- reading -------------------------------------------------------------------------------------------
    def items(self):
        """Current memories, newest first (superseded ones are kept in the engine but not shown)."""
        return sorted((m for m in self.engine.store.all() if not m.superseded_by),
                      key=lambda m: (-m.timestamp, m.id))

    def recall(self, question, top_n=PLAN_TOP_N):
        """H-MEM retrieval for PLAN: the canonical ranking and the domain-grouped reinjection block, with trace."""
        return self.engine.query(question, top_n=top_n)

    def done_before(self, kind, since_ms):
        """The latest 'marked done' memory for a check-in item from an earlier session, if still current."""
        hits = [m for m in self.items() if f"item:{kind}" in m.tags and "done" in m.tags and m.timestamp < since_ms]
        return hits[0] if hits else None

    def intent_before(self, kind, since_ms):
        """The latest draft/reminder memory for a check-in item from an earlier session."""
        hits = [m for m in self.items() if f"item:{kind}" in m.tags and "intent" in m.tags and m.timestamp < since_ms]
        return hits[0] if hits else None

    def ledger_size(self):
        return len(self.engine.ledger.all())

    # --- forgetting ----------------------------------------------------------------------------------------
    def forget(self, memory_id):
        self.engine.store.delete(memory_id, "forgotten by the student")

    def mark_wrong(self, memory_id):
        self.engine.feedback(memory_id, "wrong")

    def forget_all(self):
        for m in list(self.engine.store.all()):
            self.engine.store.delete(m.id, "forget everything")
