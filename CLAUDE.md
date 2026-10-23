# Runway: project brief

Follow this brief for every task.

## How we work

I'm working with a project lead (another Claude, in a separate chat) who plans this project and writes your instructions. I relay messages between you. You can't talk to the project lead directly, so write every status report and question so that I can paste it to them and they can understand it without seeing this session. When you need information, decisions or clarification, ask in the "Questions for the project lead" section instead of guessing.

## Project

"Runway" is an AI agent for college students, built for the GenAI Works Open Agent Hackathon (Track 2: "The Agent That Can Explain Why").

**Submission deadline: Tue Oct 27, 7:45 PM ET.**

## What it does

A student's money is spread across separate sources (checking account, credit card, financial aid award, student account/bursar, lease, work shifts). Runway answers questions like "Can I afford a $400 flight home for Thanksgiving?" (the headline demo question) and "How many weeks will my money last?" It projects the balance forward through the semester, finds money leaks, explains WHY with evidence, and drafts actions (e.g., an email to the financial aid office) that the user approves before anything happens.

**Demo timeline:**
- The demo is set in the **Fall 2026 semester (Aug 24 – Dec 18, 2026)**.
- It uses a fixed demo "today" of **Mon Oct 26, 2026**: `config.DEMO_TODAY`, set in `.env`. `config.SEMESTER_START` and `config.SEMESTER_END` hold the semester dates.
- Never use the real system date for money logic.
- The demo student is **Maya**. Her synthetic data is in `data/maya/` (regenerate with `generate_maya_data.py`), and the planted stories and their evidence are in `data/maya/answer_key.json`.
- **Key "explain why" moment (must survive into the final answer):** cancelling Apple Music saves $0 for checking before Dec 18. Its next charge (Nov 22) is on the card cycle that is paid Jan 7, after the semester. That is why the answer recommends cancelling Spotify, which charges checking directly. The tight margin is intended: with the refund plus Spotify cancelled, Maya bottoms out at $5.81.

## Non-negotiable rules

1. **Never guess or invent** APIs, package names, endpoints, model IDs or credentials. Use the configuration the user provided. If you aren't sure something is real, say so and ask.
2. **The LLM never does arithmetic.** All money math happens in deterministic, tested Python. The LLM plans, picks tools, and writes explanations.
3. **Every claim needs evidence.** Every claim in an answer must be backed by an evidence record: which source, what query, which rows. The UI must be able to show it.
4. **Data sources stay separate.** Never merge them into one table or file. The app accesses every source through a data-access layer with two implementations: Zetaris (the real one) and local files (a fallback for testing and for the demo if Zetaris is down).
5. **Models:** NVIDIA Nemotron through NVIDIA's OpenAI-compatible API, using the configuration provided.
   - **PLAN:** `nvidia/nemotron-3.5-lightning-30b-a3b`, from `config.NVIDIA_PLAN_MODEL`.
   - **EXPLAIN:** `nvidia/nemotron-3.5-super-vl-120b-a12b` (Nemotron 3.5 Super), from `config.NVIDIA_EXPLAIN_MODEL`. Its reasoning trace is what the UI shows.
   - **Base URL:** `config.NVIDIA_BASE_URL`.

   Read these from config, never hardcode them. `nvidia/nemotron-3-super-120b-a12b` is not available to our key (it returns 404); don't use it.
6. **Secrets** live only in `.env` (or the existing config files), which are gitignored. Never print or commit keys.
7. **All data is synthetic.** Never connect real bank accounts.
8. **The agent never sends anything on its own.** Actions are drafts the user approves.
9. **At most 2 LLM calls per user question:**
   - one PLAN call: the model picks which tools to run and with what arguments, as structured JSON;
   - one EXPLAIN call: the model writes the answer from the evidence.

   Everything between them, every query and all the math, runs in deterministic Python with no LLM calls. Never build an open-ended tool-calling loop. The PLAN call runs with thinking off; the EXPLAIN call runs with thinking on, and its reasoning trace is kept so the UI can show it. (Why: the hosted endpoint takes 80–200+ s per round trip.)
10. **Python computes every number the answer could need,** including results like "balance after the purchase", before EXPLAIN.
    - The EXPLAIN prompt forbids introducing any number not in the evidence or computed results.
    - It requires each claim to cite evidence IDs like [E3].
    - After EXPLAIN, a check verifies that every dollar amount and date in the answer appears in the evidence or computed results.
    - On failure, retry once with the offending numbers listed, then show the answer with a visible warning.
11. **Projection rule:**
    - Known items are projected explicitly: rent schedule, paychecks from pay periods/scheduled shifts, payment-plan installments, card autopay from statements, detected monthly subscriptions, aid/refund releases.
    - Everything else is variable spending, projected per account as the semester-to-date daily average of non-recurring purchases under $100.
    - Purchases of $100 or more are one-offs and are not projected.
    - The engine's tests must reproduce the answer key's self-check numbers to the cent. If they can't, change the DATA (`generate_maya_data.py`), never the rule.
12. **Classification is rule-based, never the LLM.** Categories: income, rent, recurring_bill (utility share, payment plan and similar), subscription (small fixed monthly digital services), card_payment (a transfer between Maya's own accounts; never count it as spending), fee, one_off ($100 or more, non-recurring), variable (everything else). Merchant keywords live in one place: `normalize.MERCHANT_RULES`.
13. **The engine takes a scenario as input** (`engine.Scenario`; defaults = "nothing changes"), so the UI's what-if panel can recompute the projection instantly with no LLM call.

## Sponsor tech

This is part of the judging score, so keep it visible:

- **Zetaris:** federated data access over JDBC (Lightning SQL), not MCP. There is no Zetaris MCP; don't build one.
- **NVIDIA Nemotron:** reasoning
- **Meterless (optional):** persistent memory

## Zetaris notes

- **Install:** local Docker Compose bundle at `C:\Users\Evana\zetaris-platform` (v2.4.3.1, hackathon build). Don't change or remove it or its config. Check health with `./verify.sh` in that folder; web UI at http://localhost:3000.
- **JDBC:** URL `jdbc:zetaris:lightning@localhost:10000`, driver class `com.zetaris.lightning.jdbc.LightningDriver`, jar in the bundle's `jdbc/` folder. Needs Java (Temurin 21 installed). Connect with `zetaris_db.query(sql)`; all values come from `.env` through `config.py`.
- **Lightning SQL quirks:**
  - One statement per call.
  - Plain `SHOW DATABASES` / `SHOW TABLES` are rejected. Use `SHOW NAMESPACES IN ...` / `SHOW TABLES IN <db>`.
  - Values come back as strings for CSV tables, so cast in SQL or parse in Python.
- **Registering files as tables:** one Lightning database per source, then one FILESTORE table per file:
  ```sql
  CREATE LIGHTNING DATABASE <DB> DESCRIBE BY "<description>" OPTIONS ()
  CREATE LIGHTNING FILESTORE TABLE <table> FROM <DB> FORMAT csv OPTIONS (path "<path>", header "true")
  ```
  - **Local files work.** Copy them into the driver container's shared data folder and use the container path: `docker cp file.csv zetaris-driver-1:/home/zetaris/customer-data/shared/<folder>/file.csv`, then `path "/home/zetaris/customer-data/shared/<folder>/file.csv"`. In Git Bash, set `MSYS_NO_PATHCONV=1` first, or it rewrites `/home/...` into a Windows path.
  - **Descriptions** (`DESCRIBE BY`) may only contain letters, digits, spaces and `_ . - ,`. Brackets are rejected.
  - **Sample data:** `NY_TAXI` and `TPCDS_DB` were registered the same way, from a public S3 bucket.
- **Other statements that work:** `SHOW LIGHTNING DATABASES`, `SHOW TABLES IN <DB>`, `DROP LIGHTNING DATABASE TABLE <DB>.<table>`, `DROP LIGHTNING DATABASE <DB>` (drop its tables first). Spark SQL functions work too: `to_date(col, 'MM/dd/yyyy')`, `UNION ALL`, joins, subqueries, `GROUP BY ... HAVING`. Empty CSV cells come back as NULL.
- **Loading and access:** `load_zetaris.py` loads `data/maya`. The app reads only through the named queries in `data_access.py`, never ad-hoc SQL.
- **Demo path (approved):** both.
  - At app startup, warm the Zetaris cache with every query the three demo questions need (`normalize.queries()` lists the engine's), so answers are fast. Evidence still shows `zetaris-cached` with the original timing.
  - A "Run live on Zetaris" button in the UI runs the federated query uncached, with a visible timer: the "this is Zetaris" moment. (UI comes later.)
- **Database naming (approved):** one Lightning database per source: `RUNWAY_CHECKING`, `RUNWAY_CARD`, `RUNWAY_AID`, `RUNWAY_BURSAR`, `RUNWAY_LEASE`, `RUNWAY_SHIFTS`. `RUNWAY_TEST` (5-row throwaway) still exists; drop it in the task that registers the real demo sources.
- **Speed:** this laptop is ARM (Snapdragon), so the Intel/AMD images run under emulation.
  - Small local tables: about 1.5–4 s per query.
  - S3 sample tables: tens of seconds or more.
  - Registering a table: about 10 s.

  Use local files for development and tests, use Zetaris for the real demo path, and never let a Zetaris query block the UI.

## Stack

Python 3.11+, Streamlit for the UI, pytest for tests. Keep dependencies minimal.

## Working style

- Small steps. Propose a plan before large changes.
- Write tests for all money math.
- Keep the README updated with how to run the project.
- Only do the task you were given; suggest extra work in the report instead of doing it.

## Status report

Required at the end of EVERY response, no exceptions. Put the whole report inside one fenced ```text block so the user can copy it in one go and paste it to the project lead. Make it self-contained: no "see above", and include any SQL, file names, numbers or errors in the report itself.

```
## Status report for the project lead
- Task: what I was asked to do
- Done: what I actually did, with file names
- Verified: how I checked it works (commands run, test results), or "not verified" and why
- Decisions/assumptions: anything I chose or guessed that should be checked
- Problems: errors, blockers, or things that didn't work ("none" if none)
- Questions for the project lead: anything I need decided or explained ("none" if none)
- Needs from the user: keys, files, accounts, or actions only the human can do
- Suggested next step
```
