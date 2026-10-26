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
- Runway's number checker rejected every one of those answers ("$1,850 is not in the facts"). It asked for one
  rewrite, and then showed the quick answer built from the engine. No wrong number ever reached Maya.
- The fix on our side: memory goes to the planner only, never into the answer. Runway's own H-MEM recall feeds PLAN
  ("what does 'the flight' mean?") and the answer is written from the evidence pack alone. The EXPLAIN prompt says:
  "Use only the evidence pack in this message. Ignore any other context or remembered answers."
- Spot check after that rule, 5 questions through Nightshift, fast mode: 2 of 5 full AI answers. The other 3 fell
  back to the checked quick answer, each caught for numbers from other answers. The checker, not the prompt, is the
  safety net.
- The line for the slide: "Memory makes an agent helpful. Evidence makes it trustworthy. Runway remembers, but every
  number it says comes from the records, and a checker proves it."

(More sections are added in Part 4: the H-MEM engine and its test, Nightshift routing, Zetaris numbers, eval
results, screenshots.)
