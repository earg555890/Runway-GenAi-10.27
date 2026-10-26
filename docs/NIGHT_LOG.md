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
