# Runway

An AI agent for college students: projects their money forward through the semester across separate sources, explains why with evidence, and drafts actions for them to approve. Built for the GenAI Works Open Agent Hackathon (Track 2).

## Setup

Requires Python 3.11+ and Java 8+ (for the Zetaris JDBC driver). Developed on Windows on ARM with Python 3.14 (x64 build) and Temurin JDK 21.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
cp .env.example .env                                       # then fill in the values
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

`ui/app.py` is short; each section is its own module in `ui/` (header, sidebar, hero, chart, whatif, findings, explain, live_zetaris, ask). The UI does no money math: every number comes from `engine`.

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

## Checks

```bash
.venv/Scripts/python -m pytest                 # all tests; Zetaris parity tests skip if Zetaris is unreachable
.venv/Scripts/python -m pytest -m "not zetaris" # fast: no network, no Zetaris, no real API calls
.venv/Scripts/python nemotron_smoke_test.py    # live NVIDIA check: chat, tool calling, reasoning on/off
.venv/Scripts/python benchmark_latency.py 3    # live latency comparison of Nemotron models (slow; measures only)
```

The LLM client is `llm_client.py`: `chat()` for normal calls, `chat_json()` for the PLAN call, and `stream_chat()` for the EXPLAIN call. Every call has a 90 s timeout and up to 2 retries on 5xx errors and timeouts.
