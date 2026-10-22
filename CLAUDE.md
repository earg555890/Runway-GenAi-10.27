# Runway: project brief

Follow this brief for every task.

## How we work

I'm working with a project lead (another Claude, in a separate chat) who plans this project and writes your instructions. I relay messages between you. You can't talk to the project lead directly, so write every status report and question so that I can paste it to them and they can understand it without seeing this session. When you need information, decisions or clarification, ask in the "Questions for the project lead" section instead of guessing.

## Project

"Runway" is an AI agent for college students, built for the GenAI Works Open Agent Hackathon (Track 2: "The Agent That Can Explain Why").

**Submission deadline: Tue Oct 27, 7:45 PM ET.**

## What it does

A student's money is spread across separate sources (checking account, credit card, financial aid award, student account/bursar, lease, work shifts). Runway answers questions like "Can I afford a $400 spring break trip?" and "How many weeks will my money last?" It projects the balance forward through the semester, finds money leaks, explains WHY with evidence, and drafts actions (e.g., an email to the financial aid office) that the user approves before anything happens.

## Non-negotiable rules

1. **Never guess or invent** APIs, package names, endpoints, model IDs or credentials. Use the configuration the user provided. If you aren't sure something is real, say so and ask.
2. **The LLM never does arithmetic.** All money math happens in deterministic, tested Python. The LLM plans, picks tools, and writes explanations.
3. **Every claim needs evidence.** Every claim in an answer must be backed by an evidence record: which source, what query, which rows. The UI must be able to show it.
4. **Data sources stay separate.** Never merge them into one table or file. The app accesses every source through a data-access layer with two implementations: Zetaris (the real one) and local files (a fallback for testing and for the demo if Zetaris is down).
5. **Reasoning model:** `nvidia/nemotron-3.5-super-vl-120b-a12b` (Nemotron 3.5 Super) through NVIDIA's OpenAI-compatible API, using the configuration provided. Read the model name and base URL from config (`config.NVIDIA_MODEL`, `config.NVIDIA_BASE_URL`), never hardcode them.
6. **Secrets** live only in `.env` (or the existing config files), which are gitignored. Never print or commit keys.
7. **All data is synthetic.** Never connect real bank accounts.
8. **The agent never sends anything on its own.** Actions are drafts the user approves.

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

Required at the end of EVERY response, no exceptions:

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
