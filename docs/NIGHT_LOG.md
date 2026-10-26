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
