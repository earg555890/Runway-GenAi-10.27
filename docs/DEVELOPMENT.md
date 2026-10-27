# PocketMoney: developer notes

How to set up, run and check PocketMoney in development. For the overview and the quick demo, see the [README](../README.md). Commands are run from the repo root.

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

`ui/app.py` is short; each part is its own module in `ui/`: `top` (greeting, status sentence), `ask` (question box, coming soon), three tabs `semester` (chart + ways to fix it), `afford` (Afford it?), `found` (Findings, with proof), and `behind` (Behind the scenes: data sources, every calculation via `explain`, and `live_zetaris`). The UI does no money math: every number comes from `engine`.

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

## Ask PocketMoney (the agent)

`agent.py`: `agent.run(question, scenario, history=..., think=False)` yields progress stages, the quick answer, streamed text and a final `Answer`. Per question:

- **PLAN:** one call (`NVIDIA_PLAN_MODEL`, thinking off, JSON). It picks up to 3 tool calls and their arguments, validated strictly in Python (`validate_call`). It gets the last 3 turns of the chat, so follow-ups resolve, and returns the question it answered (`resolved_question`). If it fails, `keyword_plan` takes over.
- **EXECUTE:** the engine does all the math. Results from every call merge into one pack of calculations (C1..) and source records (E1..).
- **QUICK:** a quick answer built from the engine (template + every required fact) is yielded at once.
- **EXPLAIN:** one streamed call, through Meterless Nightshift (the AI provider, `llm_client.py`). Fast mode (default): Lightning, thinking off, then the Think harder model, thinking off. "Think harder": `THINK_MODEL` (Nemotron Ultra, `nvidia/nemotron-3-ultra-550b-a55b`), thinking on, then Lightning, thinking on. On the direct NVIDIA fallback, Think harder uses `NVIDIA_EXPLAIN_MODEL` (Super).
- **CHECK:** the checker covers amounts, dates, citations, format, record IDs, required facts, reason claims (`merchant_accounts`), repetition, cut-off answers (`finish_reason`) and invented budgets. One rewrite; if the answer still fails, the quick answer stays.

General questions (`general_info`) get no facts and no number check, but must not state her numbers. Drafts (email to financial aid, checklist) come from templates and are never sent. The answer records which model wrote it and its timings (`quick_s`, `total_s`).

Tools: `can_afford`, `runway`, `what_if`, `find_leaks`, `refund_status`, `cash_crunches`, `spending_summary`, `find_transactions`, `upcoming_bills`, `work_summary`, `balance_on`, `accounts_today`, `money_ideas`, `general_info`. Spending categories come from one rules table, `normalize.SPENDING_RULES`.

`ANSWER_MODE` in `.env`: `live` (always call), `cached` (reuse a saved answer for the same question and what-ifs: `.cache/answers/` first, then `demo_answers/`), `replay` (only the committed `demo_answers/`, typed out; no key needed). Live answers are saved to `.cache/answers/` (gitignored). With no saved answer and no way to call the models (replay mode, or no `NVIDIA_API_KEY`), a question gets a short message saying live answers need a key.

`demo_answers/` (committed) holds the recorded answers for the 4 suggested questions, with nothing changed and with the "Do these" fixes (refund form + cancel Spotify), plus the extra-shift question. Only answers that pass the number check and were written by the main EXPLAIN model are saved; reasoning traces are trimmed to about 3,000 characters.

```bash
.venv/Scripts/python pregenerate_answers.py   # live: rewrite demo_answers/ (optional filter: pregenerate_answers.py "money last")
.venv/Scripts/python eval_agent.py fast,fast,think 180   # live: 20 questions x 3 runs -> eval_summary.md (+ eval_results.*)
```

Windows launchers in the repo root: `Start PocketMoney.bat` (local data, saved answers first; starts the app on 8501 in a window titled "PocketMoney" only if nothing is listening there, waits for the health check, opens the browser), `Start PocketMoney (Zetaris).bat` (the same with `DATA_BACKEND=zetaris`, after checking that the Zetaris JDBC port answers) and `Stop PocketMoney.bat` (stops whatever serves 8501, and its "PocketMoney" window).

## Checks

```bash
.venv/Scripts/python -m pytest                 # all tests; Zetaris parity tests skip if Zetaris is unreachable
.venv/Scripts/python -m pytest -m "not zetaris" # fast: no network, no Zetaris, no real API calls
.venv/Scripts/python nemotron_smoke_test.py    # live NVIDIA check: chat, tool calling, reasoning on/off
.venv/Scripts/python benchmark_latency.py 3    # live latency comparison of Nemotron models (slow; measures only)
```

The LLM client is `llm_client.py`: `chat()` for normal calls, `chat_json()` for the PLAN call, and `stream_chat()` for the EXPLAIN call. Every call has a 90 s timeout and up to 2 retries on 5xx errors and timeouts.
