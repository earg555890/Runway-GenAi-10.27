# Runway

**An AI money agent for college students that tells you how long your money lasts, and explains why, with proof.**

Built for the GenAI Works Open Agent Hackathon, Track 2: "The Agent That Can Explain Why".

## The problem

A student's money is split across six places that never talk to each other: a bank account, a credit card, a financial aid award, the school's student account (bursar), a lease and a part-time job. Each one looks fine on its own. Together they hide surprises: a refund held for a missing form, rent landing the day before payday, an overdraft fee, a card bill that falls due right after a big purchase. Students find out when the money is already gone.

## What Runway does

Runway connects the six sources, projects the checking balance day by day to the end of the semester, and answers plain questions. Every answer shows its proof.

The demo student is Maya (fictional). Today is Mon, Oct 26, 2026; the semester ends Fri, Dec 18.

| Suggested question | What Runway answers |
|---|---|
| Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | **Yes, if you do 2 things:** send the verification form (releases a held $1,850 refund around Thu, Nov 5) and cancel Spotify. Cancelling Apple Music saves $0.00, because its next charge is paid on a card bill due after the semester. |
| How long will my money last? | **Your money runs out on Mon, Nov 9**, when a $360 card payment is due. |
| Where is my money leaking? | Two music subscriptions and a $35 overdraft fee from rent, and which of them is worth cancelling. |
| Can I afford a $400 flight home for Thanksgiving? | **Not right now:** with no date, Runway assumes tomorrow, before the refund arrives, and says so. |

- **What-if panel:** turn fixes on and off (send the form, cancel a subscription, pick up an extra shift) and the balance chart and numbers update instantly, with no AI call.
- **Drafted actions:** a ready-to-send email to the financial aid office and a to-do list. Runway never sends anything; you copy and send it yourself.

## Watch the demo

Video: *coming soon* (link to be added)

## Try it in 2 minutes

No keys needed. This runs the full app on the included data, with the recorded AI answers for the suggested questions. Needs Python 3.11 or newer and git.

**macOS / Linux**

```bash
git clone REPO_URL_HERE runway && cd runway
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/streamlit run ui/app.py
```

**Windows (PowerShell)**

```powershell
git clone REPO_URL_HERE runway; cd runway
py -m venv .venv; .venv\Scripts\pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\streamlit run ui/app.py
```

Then open http://localhost:8501 and click a suggested question. Typed questions need a key (below).

**Live answers (NVIDIA key):** put your key from [build.nvidia.com](https://build.nvidia.com) in `.env` as `NVIDIA_API_KEY=...` and set `ANSWER_MODE=cached` (saved answers first, then live) or `ANSWER_MODE=live`. Restart the app.

**Zetaris:** start the Zetaris Docker bundle, fill in the `ZETARIS_*` settings and `JAVA_HOME` in `.env`, load the data with `python load_zetaris.py`, then run with `DATA_BACKEND=zetaris`. The first load runs every query on Zetaris (about a minute on our laptop) and caches the results. More in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## How it works

```mermaid
flowchart LR
    Q[Student's question] --> P["PLAN<br/>Nemotron Lightning<br/>picks one tool, as JSON"]
    P --> D["Named queries via Zetaris<br/>across 6 separate sources"]
    D --> E["Money engine<br/>plain Python, tested to the cent"]
    E --> X["EXPLAIN<br/>Nemotron Super<br/>writes from the evidence"]
    X --> C["Check<br/>every number, date and<br/>required fact"]
    C --> A[Answer with proof]
```

Trust rules:

- **All math is in code.** The AI never adds, subtracts or projects anything; the engine computes every number before the AI writes a word.
- **Every number is cited.** Each sentence points to a calculation or a source record, and the app shows the rows behind it.
- **A checker reads every answer.** Each dollar amount and date must match the computed results, and the answer must include the facts that matter (like the run-out date). On a miss, the AI gets one rewrite; if a fact is still missing, Runway adds it from the numbers and records that.
- **No internal IDs leak into answers.** Record IDs stay in the proof view, not in the text.
- **It degrades gracefully.** At most two AI calls per question. If Nemotron Super is down, Nemotron Lightning writes; if both are down, a template built from the numbers answers. If Zetaris is down, the app runs on the local copy of the data and says so.

## Sponsor technology

- **Zetaris:** federated data access over JDBC (Lightning SQL). Each source is its own Lightning database (6 in all), read through 16 named queries. One federated query spans two of those databases, the checking account and the credit card, to find charges that repeat every month. The app has a "Run live on Zetaris" button that runs it uncached, with a timer and the SQL.
- **NVIDIA Nemotron:** two models. PLAN (`nvidia/nemotron-3.5-lightning-30b-a3b`, thinking off) picks the tool and its arguments as JSON. EXPLAIN (`nvidia/nemotron-3.5-super-vl-120b-a12b`, thinking on) writes the answer, and its reasoning trace is shown in the app.

## Results

We asked Runway 10 realistic student questions, 3 times each, with the live models: **30/30 full answers**. Right tool, right verdict, every amount and date matching the records, and every required fact written by the model, with no rewrites. Details: [eval_summary.md](eval_summary.md).

## Data

All data is synthetic. Maya Rivera is fictional, and no real bank, card, school or employer account is connected. Her files are in `data/maya/`, generated by `generate_maya_data.py`.

## Roadmap

1. **Upload your own bank export.** A CSV or statement upload, mapped onto the same six sources.
2. **Bank connections with consent, through an aggregator.** Not built in a 6-day hackathon: it needs the aggregator's approval, a security review, and real consent and privacy work.
3. **School portal integrations, through university partnerships.** Not built yet: there are no standard APIs for financial aid or bursar accounts, so each school needs its own agreement.

---

Developer notes (setup, tests, evaluation, Zetaris loading): [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
