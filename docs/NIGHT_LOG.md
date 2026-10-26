# Night log: unattended run (Oct 25-26)

Written as the work happens. Times are this laptop's clock (EDT). Each part is committed and pushed when it ends.

## Part 0: the lead's answers on Prompt 19 (started 23:02)

- **Budget progress counts everyday purchases only.** `engine.budget_progress` leaves out $100+ one-offs (like the
  suggestion and the forecast) and returns them separately; the Budget tab shows each under its category ("Plus a
  $289 one-off: uBreakiFix"), the table's Left column now comes from the engine (it was a UI subtraction), and the
  chat's budget answers add "Plus $X in one-off purchases of $100 or more, not counted against the budget."
  October: Shopping goes from "$443 over" to "$18 left" (both October Shopping purchases were one-offs:
  Burlington $171.99, uBreakiFix $289.00).
- **Tab labels:** "Semester", "Budget", "Afford it?", "Find money", "Findings". Tests, README and
  docs/DEVELOPMENT.md updated.
- **Decision:** three recorded demo answers said "Look at the ways to fix it in My semester."; only that phrase was
  changed to "...in the Semester tab" (text, quick answer and sections), nothing else in them. The quick-answer
  template says the same.
- Tests: 320 passed, 21 deselected (Zetaris).

## Part A: upload your own bank CSV (started 23:20)

### A1-A4: privacy rule, fake files, importer, storage, engine path (23:20-23:55)
- CLAUDE.md rule 7 now: real data only from files the user uploads; kept in `user_data/` (gitignored, verified with
  `git check-ignore`), never committed, only sent to NVIDIA for answers the user asks for, never in demo answers.
- Three FAKE exports in `tests/fixtures/fake_bank/` (seeded generator, README says fake): A `Date,Description,Amount`
  (MM/DD/YYYY, debits negative, no balance), B `Posting Date,Description,Debit,Credit,Balance` (ISO, "$1,050.00",
  newest first), C `Date,Payee,Amount,Running Balance` (DD-MM-YYYY, negatives in parentheses).
- `importer.py` (rule-based): header row, date column and format (dd/mm vs mm/dd from values over 12), amount or
  debit/credit, balance, description, and the sign (checked against the running balance when there is one).
  Detection: A -> Date / %m/%d/%Y / Amount / negative_out / no balance; B -> Posting Date / %Y-%m-%d / Debit+Credit /
  Balance; C -> Date / %d-%m-%Y / Payee / Amount / Running Balance / negative_out. All three import the same 55 rows
  (total -$788.28, balance $1,200.00 -> $411.72). Unreadable files are rejected in plain words.
- `mydata.py` stores her data in `user_data/mydata/` and reads it through a new named query `mydata_transactions`
  (Zetaris database RUNWAY_MYDATA when DATA_BACKEND=zetaris and registered, else the local file). `load_zetaris.py`
  never touches it.
- Engine: `config.as_of()` runs the engine on her dates (today = her last day; end date = the semester end by
  default); guards where the engine expected card/job/lease/payment-plan data; `recurring_income()` projects her pay
  from deposit history (3+ deposits, steady gap 6-35 days, steady amount) - only when there is no job record, so
  Maya's forecast can't change. Generic merchant keywords (`normalize.MYDATA_RULES`) apply only to uploaded data.
- Decision: City Transit Fare ($2.75 in 3 months) is classified as a monthly bill by the existing 3-month rule (rule
  12); left as is.
- Tests: 320 passed (Maya unchanged).

### A5-A6: My data mode in the app, tests (23:55-00:40)
- Header switch "Demo student (Maya)" / "My data". With no file yet: the import screen (upload, detected mapping with
  dropdowns to fix it, a 6-row preview, a balance box when the file has none, "Plan until" date defaulting to the
  semester end, Import). After import: the whole page runs on her dates (`config.as_of`); "Your data" expander to
  replace or remove the file.
- Works on her data: status card, big numbers, chart, check-in ("Hi. 1 thing needs your attention."), Budget tab
  (months from her first day), leaks, Afford it?, chat. School-only features show "Connect your school data to see
  this." (Find money, Findings, the extra-shift card). Agent tools that need school data (refund_status,
  cash_crunches, work_summary, find_aid, meal_plan) return `agent.NOT_AVAILABLE` without an AI call.
- Privacy: in My data mode answers are never read from or written to the answer cache (always live), and the AI
  greeting and AI budget summary are off (no AI call she didn't ask for). Switching modes clears what-ifs, budget,
  done items and the chat.
- Zetaris check (live, once): the fake file B registered as RUNWAY_MYDATA.transactions (55 rows, 14.4 s), read back
  identical to the local file (4.9 s); the fake database was dropped afterwards.
- Decisions: "today" in My data mode = the last day in her file; the AI greeting/summary are off for her data;
  switching modes resets the session's what-ifs and chat.
- Tests: tests/test_mydata.py (16): detection for all 3 layouts, same rows from all 3, money/sign handling incl. a
  file where purchases are positive (sign found from the balance), plain rejections, recurring + projection
  (her pay Oct 30 / Nov 13 / Nov 27 / Dec 11 at $612.40; runs out Sun Nov 1), typed balance, the agent's
  "needs your school data" answer, no caching of her answers, every tab in My data mode, the import screen, Maya
  mode unchanged after using My data, nothing in user_data/ tracked or unignored. Full suite: 336 passed.

## Part B: live scholarship web search (00:40-01:30)
- Provider: **Firecrawl keyless search** (`POST https://api.firecrawl.dev/v2/search`, no Authorization header).
  Checked against Firecrawl's docs, then tested live: it worked without a key, so Exa (EXA_API_KEY) was not
  needed and isn't used. An optional `FIRECRAWL_API_KEY` in .env is sent as a bearer token for higher limits.
  One request per query also returns each result page's text (`scrapeOptions` markdown), used for checking.
- `websearch.py`: 3 queries from the school profile only (Maya: "scholarships for college sophomores",
  "emergency grants for college students", "scholarships for biology majors"; generic phrases in My data mode, no
  private data). Each result: title, site, link, and an amount/deadline **only if that exact text is on the
  fetched page** (string match), else "see website". Amounts under $100 or followed by million/billion/k are
  ignored; directory pages (more than 4 amounts or 2 deadlines) get "see website". An optional fast-model
  suggestion is kept only if it is on the page (not used by the app by default: no extra AI calls).
- Saved set recorded live tonight: `demo_answers/web_scholarships.json` (found 2026-10-25 23:24, 9 results; most
  say "see website"; Scholarship America shows deadline "December 15, 2026"; HELPS Program Microgrant "$1000").
  Cache: `.cache/websearch/results.json` (fresh for 24 h).
- Find money tab: new section "Found online - check before applying" under the school's list. Shows the last
  results at once (cache, else saved set) with "Found Sun, Oct 25 at 11:24 PM with Firecrawl..." and "Runway
  didn't check who can apply, and none of these are in your forecast." A "Search online now" button runs a live
  search in a background thread (the page never waits; failures keep the old results). Replay mode: saved set
  only, no button; no saved set -> a note instead of the section. Also shown in My data mode.
- Chat tool `search_scholarships` ("Find me scholarships online"; planner example + keyword fallback "online" +
  scholarship/grant/aid). Stated amounts/deadlines and the search date become engine records so the number check
  passes; required fact "check before applying"; new checker `web_claim_problems` rejects "you qualify / you are
  eligible / you will get" in these answers.
- Decision: not added to the suggested-question buttons (keeps the demo's suggested set and its saved answers
  unchanged); it is reachable by typing.
- Tests: tests/test_websearch.py (11, all mocked, no network): page-text-only amounts/deadlines, a model claiming
  "$5,000" that isn't on the page -> dropped, directory pages, dedupe + cache, timeouts fall back (None if nothing),
  replay never searches, the committed saved set, the chat answer ("Check before applying", stated amount and
  deadline, "see website"), the "you qualify" check, planner routing, and the Find money tab rendering the saved
  set without any live search. Full suite: 347 passed.

## Part C: full evaluation (01:30-)
- eval_agent.py: 28 questions (the 21 from before, the 2 budget, 1 aid and 1 meal-plan questions added with
  Prompts 18-19, plus 2 new: "If I apply for the emergency grant, when would the money come?" (find_aid) and "How
  many meal swipes will I have left at the end of the semester?" (meal_plan)). action_plan was already in ("What
  should I do this week?"). Web search and My data are not in the scored eval (tested in pytest, all mocked).
- Started `eval_agent.py fast,fast,think 240` in the background (DATA_BACKEND=local, log .cache/eval_night.log).

## Part D: judge-ready finish (in progress)
- D1 demo answers: replayed all 15 saved answers and re-ran the current checker on each saved text (fake model
  returning the saved text, no network). 14/15 unchanged and passing. The extra-shift answer ("What if I pick up
  a 5 hour shift on Nov 7?") passes the number check but now misses 2 required facts added later (sending the
  form + the refund date; covered all semester with lowest $5.81), so it is regenerated after the eval (Think
  harder, `pregenerate_answers.py "5 hour shift"`).
- README: 8 Zetaris databases by name, 21 named queries, the federated query, My data paragraph, Found online
  paragraph, the data/privacy note, the new roadmap (aggregator, school integrations, verified scholarship
  databases, mobile app; one sentence each on why 1 and 2 weren't built in 6 days).
- D2 fresh clone: cloned https://github.com/earg555890/Hackathon1 (9e9593c) into C:\rc; installing per README.

## Part E: demo script
- docs/DEMO_SCRIPT.md: the 7 timed beats (0:00-3:00) as a table of click / on screen / say, with the real
  numbers from the app (runs out Mon, Nov 9; yes if 2 things; Apple Music $0.00; $5.81; "Not right now"; Form sent
  -> above zero all semester, ending around $437; $1,757 in October; $500 grant Mon, Nov 2 if approved; spring
  scholarship $0.00 this semester; dining dollars Sun, Nov 22), a recording checklist and a 1-page judge tour.

### Part C findings so far (fast runs 1 and 2: 22/28 full answers each)
- Every miss was a real model mistake caught by the checker (the quick answer stood in); 0 NVIDIA service errors.
- Repeated pattern 1 (fixed): on the meal-plan questions the fast model sometimes writes the whole answer on ONE
  line ("ANSWER: ... WHY: - ... DO THIS: 1. ..."), which the format check rejected (3 of 4 meal answers).
  Fix: `agent.unflatten()` puts a one-line answer back on separate lines before the checks, words unchanged (a new
  item starts only after a finished sentence, so "Nov 22." is not read as item 22). Test added. Re-ran only the 2
  meal questions twice: the format failures are gone; 2/4 full answers, the other 2 failed on a different real
  mistake (the same fact stated in ANSWER and again in WHY; the rewrite repeated it). Not fixed: it is the model
  repeating itself and the checker is right to reject it.
- Repeated pattern 2 (not fixed, logged): "Can I afford new headphones for $150?" (no date) failed in both runs. The
  model puts "You didn't say when you'd buy it, so I assumed tomorrow" in both WHY and NOTE, and writes
  "-$144.19" with a minus sign. Deduplicating the note would not be enough (the minus sign still fails), and changing
  the prompt is not a small safe change the night before the deadline. The quick answer ("Not right now") is right.
- One-offs (once each): a wrong weekday ("Wed Nov 3"), "- $281" with a minus sign, "October 2" not in the facts, "$53"
  not in the facts, a record ID (ACCT-CHK-01), a cut-off answer, and one budget plan that picked category "food"
  for "What happens if I stick to my budget?" (expected no category).
- D1 correction: the "stale" extra-shift demo answer was a false alarm from my re-check method (feeding back the
  stored resolved plan args includes form_date, which switches on the form what-if and adds 2 facts). In the real
  pipeline it needs 3 facts. It was regenerated anyway (Think harder, passes every check, 3/3 facts written by the
  model, no rewrite) and committed; the other 14 saved answers are unchanged and pass the current checks.
- Run 3 (Think harder) was stopped at 26/28 questions (25 full answers so far; the NVIDIA Super endpoint was
  slow, one question took 7.5 min and was answered by the Lightning fallback) when a new session took over. Its
  answers are only in the local log (.cache/eval_night.log); eval_results.json / .md hold the two complete fast
  runs (22/28 each). eval_summary.md was not regenerated (it still shows the earlier 20-question results).

## Session Oct 26: Parts 0-5
### Part 0
- eval_summary.md regenerated from the two complete fast runs (44/56 full answers) with a clearly marked note on
  the partial Think harder run (26 of 28 asked, 25 full answers, 3 written by the Lightning fallback).
### Part 1: fast-mode answer quality
- Repetition repair: when the ONLY check problem is a repeated or near-identical sentence, `agent.remove_repeats()`
  drops the later copy (same rule as the check, first kept, no words added or changed; a bullet or NOTE left empty
  is dropped), then the full check runs again. If it passes, the answer is used with `retries["repaired"] =
  "removed duplicate line"`, shown in "How Runway thought about this" and counted in the eval.
- Headphones: the EXPLAIN rules now say to write the assumption ONCE, in NOTE only, and that a negative fact value
  is a balance "below zero". New check `assumption_place_problems` fails an answer with the assumption in ANSWER,
  WHY or DO THIS. The rewrite request now spells out the "$144 below zero" wording and where the assumption goes.
  Tests use the exact failing texts from the overnight eval (tests/test_answer_repairs.py).
- Targeted re-run (fast, twice): headphones, "Will my dining dollars last?", "How many meal swipes...".
  Before (overnight runs 1-2): 0/6 full answers. After: 5/6. The one miss: headphones run 1 copied a calculation
  note ("-$1,612.37") - the checker caught it and the quick answer stood in. No answer needed the repair in this run.
### Part 2: whole-app polish
- Screenshots with headless Chrome over the DevTools protocol (no new packages; the extension wasn't connected):
  every tab + the check-in, light/dark, laptop (1440) / phone (390), base / "Form sent" / two planned shifts.
  56 before (screenshots/before/) and 56 after (screenshots/final/), both gitignored.
- Found and fixed: a fake test result ("Sophomore Science Award, example.org, $2,500") showing in Find money: an
  early web-search test (before the cache-path fix) had written the app's real cache. Deleted the cache file; a
  conftest guard now points every test at a temp cache and blocks the web search.
- One product: Findings cards use the same card title/text as the check-in and Find money (they were large h4s);
  one section heading size (h4) in Semester, Budget and Find money; one action-button size in card rows; the "If
  approved" switch centered on the button line; Budget inputs in reading order on phones (row by row).
- Duplicates: the check-in no longer has a "Card payment on Mon, Nov 9" card - the status card right above says it.
  Maya now has 6 items; if the run-out was the only item (My data mode) the heading says "See the ways to fix it
  below." (not "You're all caught up").
- Readability: split the long sentences found by a scan of every visible sentence (Find money intro, "...after the
  semester. So it adds $0.00 this semester.", the tight-week card, the online-results caption).
- README: check-in paragraph (6 items) and two refreshed images (status + check-in, Semester with the planner).
