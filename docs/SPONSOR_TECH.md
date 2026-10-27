# Sponsor technology in PocketMoney

PocketMoney is an AI money agent for college students (track: **The Agent That Can Explain Why**). It answers "Can I
afford a $400 flight home?" and "How long will my money last?" from a student's separate money sources. Every
number comes from tested code, and every claim cites its evidence. Here is how each sponsor technology is used.

## Zetaris: the data layer

- **What it does in PocketMoney.** A student's money lives in eight separate places. PocketMoney registers each one as its
  own Zetaris Lightning database: `RUNWAY_CHECKING`, `RUNWAY_CARD`, `RUNWAY_AID`, `RUNWAY_BURSAR`, `RUNWAY_LEASE`,
  `RUNWAY_SHIFTS`, `RUNWAY_OPPORTUNITIES` and `RUNWAY_MEALPLAN`. One FILESTORE table per file
  (`load_zetaris.py`). The sources are never merged into one table.
- **How the app reads it.** Over JDBC (Lightning SQL, `zetaris_db.py`), only through 21 named queries
  (`data_access.py`); the app never runs ad-hoc SQL. Every answer's evidence records which source, which query and
  which rows, and the UI shows them ("Show proof" chips, "Details for nerds" with the SQL).
- **Federated query.** `federated_recurring_charges` runs one statement across `RUNWAY_CHECKING` and `RUNWAY_CARD`
  (JOIN + UNION ALL + GROUP BY ... HAVING) to find charges that repeat every month. That's how PocketMoney finds the
  two music subscriptions, one on checking and one on the card. The "Run live on Zetaris" button runs it uncached
  with a visible timer (about 18 s warm on our ARM laptop, where the containers run under emulation).
- **Speed and reliability.** At startup PocketMoney warms a disk cache with every query the demo needs; evidence still
  says `zetaris-cached` with the original timing. A parity test (`tests/test_data_access.py::test_zetaris_parity`)
  checks that every named query returns the same rows on Zetaris as on the local copies. If Zetaris is down, the
  app keeps working on the local files and says so.

## Meterless: Nightshift as the AI provider, and the H-MEM engine

### Nightshift: the primary AI provider

- Every model call goes through **Meterless Nightshift** (the Meterless Runtime, OpenAI-compatible, on this
  computer). The NVIDIA key lives inside Nightshift (Setup > Providers), not in PocketMoney.
- PocketMoney follows the official provider contract (Meterless Runtime 0.90.0, `docs/agent-ready/add-meterless-provider.md`):
  - Authorization: Bearer with the Runtime token; the `rt-local` placeholder is rejected.
  - `meterless-app: runway` on every request, and `meterless-scope: user` on chat.
  - URLs are normalised to `<host>/v1`, never `/v1/v1`.
  - Status comes from `GET /v1/models`: 401/403 means "unauthorized", 200 with meterless ids means "online".
  - Auto Detect tries ports 8088, 8090, 8787 and 11434.
  - Timeout of 180 s.
- **Checks shown in the app** (Behind the scenes > AI provider), from the live run on Oct 26:
  - `/healthz` returns 200.
  - `/v1/models` returns 200, and the runtime is online.
  - A wrong token shows "unauthorized", not "offline".
  - Discovery lists 11 Nemotron ids.
  - A plain text request on `meterless/auto` returns "OK", routed to Nemotron Lightning.
- **Which model answered.** Every Nightshift response carries a signed `meterless.compute_receipt.v1`. PocketMoney
  records the receipt id and the routed model for every call. It shows them in "How PocketMoney thought about this"
  ("Written by: Nemotron Lightning (nvidia/nemotron-3.5-lightning-30b-a3b) through Meterless Nightshift, receipt
  rcpt_...") and writes them to the per-question trace (`logs/traces.jsonl`; example: `docs/example_trace.json`).
- If Nightshift itself is unreachable, PocketMoney can fall back to NVIDIA directly. That answer is labelled
  "fallback".

### H-MEM: PocketMoney's memory (the Meterless engine)

- **Implementation.** `hmem.py` is a faithful Python port of the H-MEM reference (`engines/hmem`, Apache-2.0). It
  covers:
  - the canonical record, with a mandatory source and provenance;
  - short-term, working and long-term layers, and enrichment;
  - the hybrid retrieval formula (`score = clamp01(raw) x confidence`);
  - domain-grouped reinjection with a trace;
  - the exact feedback deltas;
  - the 17-action append-only trust ledger;
  - preview-first sleep with guardrails;
  - the 0.70 conflict gate, where the loser is marked superseded, never deleted;
  - dreaming behind human approval;
  - model-free mining.
- **Test.** The official conformance suite: the unchanged `vectors.json` and a pytest port of `runner.ts`
  (`tests/test_hmem_conformance.py`). **13/13 pass.** Plus 8 tests for the product feature
  (`tests/test_runway_memory.py`).
- **The feature it powers: "What PocketMoney remembers".**
  - **What it remembers.** What the student marked done, what she opened (the email draft to financial aid, a
    reminder), her budget, the shifts she plans, her Think harder preference, and one-line notes of past
    questions.
  - **Provenance.** Each memory says where it came from and when, and every change is in the ledger.
  - **Across sessions.** In a new session the check-in asks: "Last time you clicked "Form sent". Still true? Click
    it again."
  - **Recall goes to the planner only.** Follow-ups across sessions work ("the flight"), but the answer itself is
    written from the evidence alone.
  - **Forgetting.** The student can forget one memory, mark it "not right" (H-MEM's `wrong` feedback), or forget
    everything.

## NVIDIA Nemotron, through Nightshift

- **PLAN:** `nvidia/nemotron-3.5-lightning-30b-a3b`, thinking off. It reads the question (and the last three
  turns, plus recalled memories) and picks 1-3 tools and their arguments as JSON. Python validates the plan before
  any tool runs.
- **EXPLAIN (fast, the default):** the same Lightning model with thinking off writes the answer in a few seconds,
  in the ANSWER / WHY / DO THIS / NOTE format, citing each number.
- **The live demo's fast model:** Nemotron Ultra, thinking off (`FAST_EXPLAIN_MODEL`), because it ignores
  Nightshift's injected memories better: 5/5 full answers in 2-13 s on a 5-question spot check, against 2/5 for
  Lightning.
- **EXPLAIN (Think harder):** `nvidia/nemotron-3-ultra-550b-a55b`, thinking on. On Maya's flight question it
  passed every check on the first try, in 94.7 s, and its reasoning trace is shown in the app.
- **The model never does math.** The engine computes every number first. Then a checker verifies every amount,
  date, merchant, card/checking claim and "saves $X" in the model's answer. A miss gets one rewrite; if that fails
  too, the quick answer built from the engine is shown.

## Cursor

Cursor was the development environment for the whole build. PocketMoney's code was written by Claude Code running in Cursor's integrated PowerShell terminal; Cursor was used to open and run the project, watch Claude Code's changes and progress live, read and review the generated files, and run the app and tests. Cursor's own AI features (Composer, Grok) were not used for code generation.

## What's unique about how we used them

- **Trust is enforced, not requested.** Zetaris keeps the sources separate and auditable. Nightshift tells us
  exactly which model answered, with a receipt. H-MEM's ledger records every memory change. PocketMoney's checker
  proves every number. The UI can show all four.
- **A real-world catch.** Nightshift runs its own H-MEM memory and injected earlier answers into new requests (the
  receipt says `"hmem": injected 2`). Nemotron then reused the flight question's numbers in other answers. PocketMoney's
  checker rejected every one of them, so no wrong number reached the student. That's why PocketMoney's own memory
  feeds only the planner, never the answer.
- **Timing, not just totals.** The Zetaris federated query and the engine together explain why cancelling Apple
  Music saves $0.00 this semester: it's billed to the card, and that bill is paid in January. Spotify, on
  checking, is the one to cancel.
