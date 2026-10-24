# Runway: developer notes

How to set up, run and check Runway in development. For the overview and the quick demo, see the [README](../README.md). Commands are run from the repo root.

## Setup

Requires Python 3.11+ and Java 8+ (for the Zetaris JDBC driver). Developed on Windows on ARM with Python 3.14 (x64 build) and Temurin JDK 21.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
cp .env.example .env                                       # works as-is in replay mode; add keys for live use
```

`.env` holds the NVIDIA API key, model ID and base URL, and the Zetaris JDBC URL, user, password, jar path and `JAVA_HOME`. It is gitignored.

Zetaris itself runs separately in Docker (see the Zetaris bundle's README); it must be up for the Zetaris data path.

## Demo data

```bash
.venv/Scripts/python generate_maya_data.py   # rewrite data/maya/ (fixed seed) and run the history checks
.venv/Scripts/python load_zetaris.py         # load data/maya into Zetaris: one Lightning database per source (safe to rerun)
```

The app reads data only through `data_access.py`: named queries (`data_access.catalog()`), each with a Lightning SQL template and an equivalent local implementation. `DATA_BACKEND=local` (default) reads the CSVs; `DATA_BACKEND=zetaris` queries Zetaris over JDBC, with results cached in `.cache/zetaris/` (`ZETARIS_CACHE=on`). Every result carries an evidence record (query, sources, tables, SQL, params, row IDs, backend, duration).

## Run the app

```bash
.venv/Scripts/python -m streamlit run ui/app.py                          # backend from .env (DATA_BACKEND, default local)
DATA_BACKEND=local   .venv/Scripts/python -m streamlit run ui/app.py     # Git Bash: local CSVs
DATA_BACKEND=zetaris .venv/Scripts/python -m streamlit run ui/app.py     # Git Bash: Zetaris (Docker bundle must be up)
```

PowerShell: `$env:DATA_BACKEND="zetaris"; .venv\Scripts\python -m streamlit run ui/app.py` (use `"local"` for the CSVs). Opens at http://localhost:8501. The first Zetaris load runs every engine query (about a minute on this laptop) and fills the query cache; later loads come from the cache. If Zetaris fails, the app falls back to the local files and says so.

`ui/app.py` is short; each part is its own module in `ui/`: `top` (greeting, status sentence), `ask` (question box, coming soon), three tabs `semester` (chart + ways to fix it), `afford` (Can I afford it?), `found` (What we found, with proof), and `behind` (Behind the scenes: data sources, every calculation via `explain`, and `live_zetaris`). The UI does no money math: every number comes from `engine`.

## Money engine

`normalize.py` turns the query results into typed records: one date type for every source's date format, and one sign convention (money out is negative). It also normalizes merchant names and classifies every transaction with rules (`MERCHANT_RULES`). `engine.py` does all the money math in plain, tested Python, with no LLM:

```python
import engine
engine.project()                                                    # daily checking projection, "nothing changes"
engine.project(engine.Scenario(refund_released=True, cancel_subscriptions=("Spotify",)))   # what-if
engine.can_afford("400.00", "2026-11-10")                           # yes / no / yes_if + smallest set of fixes
engine.find_leaks(); engine.refund_status(); engine.cash_crunches()
```

Each number is a `Computed` record (`C#`: label, value, unit, how, inputs = row IDs and other `C#` ids) that the EXPLAIN step can cite.

## Ask Runway (the agent)

`agent.py`: `agent.run(question, scenario)` yields progress stages, streamed text and a final `Answer`. Per question: one PLAN call (`NVIDIA_PLAN_MODEL`, thinking off, JSON) picks one engine tool, validated strictly in Python; the engine does all the math; one EXPLAIN call (`NVIDIA_EXPLAIN_MODEL`, thinking on, streamed) writes the answer from a small pack of calculations (C1..) and source records (E1..); a checker matches every dollar amount, date and citation against the pack and allows one rewrite. Drafts (email to financial aid, checklist) come from templates and are never sent. If a model is down or slow, fallbacks take over: keyword planning for PLAN; for EXPLAIN, Nemotron Super, then Nemotron Lightning (thinking on), then a template answer built from the numbers. The answer records which model wrote it.

`ANSWER_MODE` in `.env`: `live` (always call), `cached` (reuse a saved answer for the same question and what-ifs: `.cache/answers/` first, then `demo_answers/`), `replay` (only the committed `demo_answers/`, typed out; no key needed). Live answers are saved to `.cache/answers/` (gitignored). With no saved answer and no way to call the models (replay mode, or no `NVIDIA_API_KEY`), a question gets a short message saying live answers need a key.

`demo_answers/` (committed) holds the recorded answers for the 4 suggested questions, with nothing changed and with the "Do these" fixes (refund form + cancel Spotify), plus the extra-shift question. Only answers that pass the number check and were written by the main EXPLAIN model are saved; reasoning traces are trimmed to about 3,000 characters.

```bash
.venv/Scripts/python pregenerate_answers.py   # live: rewrite demo_answers/ (optional filter: pregenerate_answers.py "money last")
.venv/Scripts/python eval_agent.py 3 240      # live: 10 questions x 3 runs, 240 s apart -> eval_summary.md (+ eval_results.*)
```

## Checks

```bash
.venv/Scripts/python -m pytest                 # all tests; Zetaris parity tests skip if Zetaris is unreachable
.venv/Scripts/python -m pytest -m "not zetaris" # fast: no network, no Zetaris, no real API calls
.venv/Scripts/python nemotron_smoke_test.py    # live NVIDIA check: chat, tool calling, reasoning on/off
.venv/Scripts/python benchmark_latency.py 3    # live latency comparison of Nemotron models (slow; measures only)
```

The LLM client is `llm_client.py`: `chat()` for normal calls, `chat_json()` for the PLAN call, and `stream_chat()` for the EXPLAIN call. Every call has a 90 s timeout and up to 2 retries on 5xx errors and timeouts.
