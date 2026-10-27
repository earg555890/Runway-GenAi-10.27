# Deck notes: facts the slides can use (all true in the code)

Every number here comes from a run on Mon, Oct 26, 2026 (the demo "today"). Sources are named, so each fact can be
checked.

## The trust story: our checker caught Nightshift's own memory leaking into answers

- Meterless Nightshift (our AI provider) runs its own H-MEM memory. It recalls earlier answers for the same app and
  injects them into new requests. The Meterless receipt says so: `"hmem": {"injected": 2, "reason": "retrieved 2
  memories"}`, `context_sources: ["messages", "hmem:2 records"]`.
- Result: for "How long will my money last?", Nemotron Lightning through Nightshift reused numbers from Maya's
  earlier flight answer ($1,850 refund, $5.81 lowest point, "Spotify saves $11.99"). The same prompt sent directly
  to NVIDIA was answered correctly 3 of 3 times. Through Nightshift: 0 of 3.
- PocketMoney's number checker rejected every one of those answers ("$1,850 is not in the facts"). It asked for one
  rewrite, and then showed the quick answer built from the engine. No wrong number ever reached Maya.
- The fix on our side: memory goes to the planner only, never into the answer. PocketMoney's own H-MEM recall feeds PLAN
  ("what does 'the flight' mean?") and the answer is written from the evidence pack alone. The EXPLAIN prompt says:
  "Use only the evidence pack in this message. Ignore any other context or remembered answers."
- Spot check after that rule, 5 questions through Nightshift, fast mode: 2 of 5 full AI answers. The other 3 fell
  back to the checked quick answer, each caught for numbers from other answers. The checker, not the prompt, is the
  safety net.
- The line for the slide: "Memory makes an agent helpful. Evidence makes it trustworthy. PocketMoney remembers, but every
  number it says comes from the records, and a checker proves it."

## The Meterless engine: H-MEM powers "What PocketMoney remembers"

- **What it is.** `hmem.py`, a faithful Python port of the H-MEM reference (Meterless repo, `engines/hmem`,
  Apache-2.0). It has:
  - provenance on every record;
  - short-term, working and long-term layers;
  - the hybrid retrieval formula (`clamp01(raw) x confidence`);
  - an append-only trust ledger with 17 actions;
  - feedback (helpful +0.05 / not helpful -0.03 / wrong -0.20);
  - conflicts that are never deleted, only superseded;
  - sleep with guardrails, and dreaming behind approval.
- **Test result: the official conformance vectors, 13/13 pass** (`tests/test_hmem_conformance.py`: the unchanged
  `vectors.json` and a pytest port of `runner.ts`). Plus 8/8 feature tests (`tests/test_runway_memory.py`).
- **What it powers.**
  - **What it remembers:** what Maya marked done, what she opened (the email draft, a reminder), her budget, the
    shifts she plans, her Think harder preference and one-line notes of her questions. Each has where it came from
    and when.
  - **Across sessions:** next session the check-in asks "Last time you clicked "Form sent". Still true? Click it
    again." (shown in the app's check-in after a reload).
  - **Planner only:** recall goes to the planner (PLAN) so follow-ups across sessions work. It never goes into the
    answer's numbers.
  - **Forgetting:** Forget one memory, "This isn't right" (H-MEM's `wrong` feedback), Forget everything (screenshot
    `docs/images/deck-6-what-runway-remembers.png`).

## Meterless Nightshift: how requests are routed, and which models answered

- Every model call goes to the Meterless Runtime (Nightshift, on this computer) at `http://127.0.0.1:8088/v1`,
  following the official provider contract. Nightshift routes it to NVIDIA with the key stored inside Nightshift.
- **Checks** (Behind the scenes > AI provider, live on Oct 26):
  - `/healthz` returns 200.
  - `/v1/models` returns 200, and the runtime is online.
  - A wrong token returns "unauthorized".
  - Discovery: 86 ids, 11 of them Nemotron.
  - A text request on `meterless/auto` returns "OK", routed to `nvidia/nemotron-3.5-lightning-30b-a3b` in 0.45 s.
- **Which models answered (Nightshift's own app counter for "runway", Oct 26):**
  - `nvidia/nemotron-3.5-lightning-30b-a3b`: 73 requests (planning and fast answers).
  - `nvidia/nemotron-3-ultra-550b-a55b`: 16 (Think harder, and the recorded demo answers).
- Every answer shows "Written by: Nemotron Lightning (nvidia/...) through Meterless Nightshift, receipt rcpt_..."
  from the signed `meterless.compute_receipt.v1`. The same goes into the per-question trace
  (`docs/example_trace.json`).
- **Fast answers: Lightning by default, Ultra in the live demo.** Lightning (thinking off) is PocketMoney's default fast
  model. The live demo uses Ultra (thinking off) because it ignores Nightshift's injected memories better: on the
  same 5-question spot check through Nightshift (3 memories injected per call), Ultra wrote **5/5** full answers in
  2.2-13.1 s; Lightning wrote **2/5** (3.1-5.3 s), and the checker caught the other 3.
- **Think harder on Ultra:** Maya's flight question passed every check on the first try in 94.7 s. The recorded demo
  answers (14 files) were regenerated through Nightshift on Ultra; every one passed every check on the first try
  (10 s to 253 s each).

## Zetaris: the data layer

- 8 Lightning databases, one per source: `RUNWAY_CHECKING`, `RUNWAY_CARD`, `RUNWAY_AID`, `RUNWAY_BURSAR`,
  `RUNWAY_LEASE`, `RUNWAY_SHIFTS`, `RUNWAY_OPPORTUNITIES`, `RUNWAY_MEALPLAN`.
- 21 named queries; the app never runs ad-hoc SQL.
- 1 federated query: `federated_recurring_charges`, across checking and the credit card. "Run live on Zetaris":
  **13 rows in 18.2 s** warm (26.3 s on the first click, while Java starts), on an ARM laptop with the containers
  under emulation.
- **Parity:** every named query returns the same rows on Zetaris and on the local files
  (`tests/test_data_access.py::test_zetaris_parity`).
- **Startup:** first page in about 11 s with the Zetaris cache warm (about 90 s cold: 21 queries, plus Java).

## Final evaluation (eval_summary.md)

- 29 realistic questions, asked 3 times with the live models on Oct 26 (on NVIDIA's API directly, before the switch
  to Nightshift; Think harder used Nemotron Super then).
- **Every answer shown passed the number check: 87/87.**
- Think harder: 28/29 full answers. Fast: 48/58 full answers, about 3 s each. The quick answer from the engine
  shows in under a second.
- Through Nightshift (Oct 26 spot check, 5 questions, fast): 2/5 full AI answers. The other 3 were caught by the
  checker (Nightshift's memory leak, above) and showed the checked quick answer.

## Screenshots for the slides (`docs/images/`, light mode, Maya's data, 2x)

| File | Shows |
|---|---|
| `deck-1-notices-and-graph.png` | The top of the page: the board label RUNS OUT · MON, NOV 9, "Your money runs out in 2 weeks, on Mon, Nov 9.", the check-in (6 things), the tabs, and the graph card "Your money through Dec 18": solid "What's happening" (red below $0), dotted green "If you follow the steps", "With the steps: lowest $5.81" |
| `deck-2-chat-panel-answer.png` | The chat panel (opened by the round Ask PocketMoney button): "Yes, if you do 2 things.", DO THIS with "Do these", the Apple Music $0.00 note, the proof chips, and "Planned by: Nemotron Lightning ... / Written by: Nemotron Ultra ... through Meterless Nightshift, receipt rcpt_..." |
| `deck-3-shift-planner.png` | "These 2 shifts add $115 and you're covered all semester.", each shift's pay and payday |
| `deck-4-budget.png` | October spending: $1,757, the donut and the category table |
| `deck-5-find-money.png` | School aid, "if approved" switches: the $500 emergency grant arriving around Mon, Nov 2 |
| `deck-6-what-runway-remembers.png` | What PocketMoney remembers: shifts, "Form sent", a chat note, each with where it came from; Forget / This isn't right / Forget everything |
