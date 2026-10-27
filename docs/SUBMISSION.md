# HackOS submission: Runway

Everything below is ready to paste into the HackOS submission form. Nothing has been submitted.
**Deadline: Tue, Oct 27, 2026, 23:45 UTC (7:45 PM ET).**

## Pre-submit checklist

Status: **done**, **to do (user)**, or **to do (Claude Code)**. Evidence is in brackets.

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Demo video, 1-4 minutes, uploaded (YouTube unlisted, Vimeo, Drive "anyone with the link", or MP4 < 300 MB) | to do (user) | Script ready: `docs/DEMO_SCRIPT.md` (3:42, live, typed questions, under-the-hood beat) |
| 2 | Slide deck covers the 8 required points | to do (user / project lead) | Facts for the deck: `docs/DECK_NOTES.md`, screenshots in `docs/images/` |
| 3 | Repository public, with README (setup, usage, dependencies) | to do (user): make https://github.com/earg555890/Runway-GenAi-10.27 public | README: Dependencies, Setup (sample and full mode), sample inputs and outputs |
| 4 | Sponsor explanation covers Zetaris, Meterless and NVIDIA | done | `docs/SPONSOR_TECH.md` (pasted below), including how Cursor was used |
| 5 | Zetaris as the data layer | done | 8 Lightning databases, 21 named queries, a federated query, a parity test (`tests/test_data_access.py`) |
| 6 | A Meterless Engine working, with a passing test | done | H-MEM (`hmem.py`), official conformance vectors 13/13 (`tests/test_hmem_conformance.py`), feature tests 8/8 (`tests/test_runway_memory.py`) |
| 7 | Meterless Nightshift as the primary AI provider | done | `AI_PROVIDER=meterless` is the default (`config.py`), checks in Behind the scenes, routed model and receipt on every answer |
| 8 | One track | done | "The Agent That Can Explain Why" in README, metadata.json, DEMO_SCRIPT.md, this file |
| 9 | Pre-existing components declared | done | Below |
| 10 | Runs from a clean clone with no manual steps | done | Fresh clone of 6a50c21 from GitHub, no `.env`, no keys: sample mode on; tests 433 passed, 21 skipped (Zetaris); app first page 4.1 s; the flight question replayed "Yes, if you do 2 things", written by Nemotron Ultra through Meterless Nightshift (receipt rcpt_req_hovpd7lc) |
| 11 | No keys committed or on screen | done for the repo; to do (user) for the video | `.env` gitignored (`git check-ignore -v .env`); the NVIDIA key is in Nightshift, not the project; the user removes `NVIDIA_API_KEY` from `.env` |
| 12 | Sample inputs and outputs included | done | README "Sample inputs and outputs" (real recorded answers) |
| 13 | Logs show how the agent reached its output | done | `logs/traces.jsonl` per question; committed example `docs/example_trace.json` |
| 14 | Submitted before Oct 27, 23:45 UTC | to do (user) | |

## Form fields

**Project name:** Runway

**One-sentence description:** Runway is an AI money agent for college students: it reads their separate money
sources (checking, credit card, financial aid, student account, lease, job, meal plan and the school's aid list),
answers questions like "Can I afford a $400 flight home for Thanksgiving?" with a day-by-day forecast to the end
of the semester, and explains why, with proof for every number.

**Short description:**
A student's money is split across places that never talk to each other, so surprises like a refund held for a
missing form, or rent due the day before payday, show up when the money is already gone. Runway keeps each source
separate in Zetaris and projects the checking balance day by day with plain, tested Python. NVIDIA Nemotron,
through Meterless Nightshift, plans which tools to run and writes the answer. A checker rejects any number that
isn't in the records. Runway drafts the fixes (an email to financial aid, calendar reminders) for the student to
approve, and remembers what she did with Meterless H-MEM. It explains timing, too: cancelling Apple Music saves
$0.00 this semester because that card bill is paid in January, so cancel Spotify instead. With her college set, it
finds jobs near campus and the school's published costs online (check before applying), and shows what a job would
change: when its first paycheck lands and whether that's before the money runs out.

**Track:** The Agent That Can Explain Why

**Team:**
- Evan Arghirescu (solo, primary contact)
- HackOS email: evan.arghirescu1@gmail.com
- GitHub: earg555890
- Role: product, agent orchestration, Zetaris and Meterless integration, UI

**GitHub URL:** https://github.com/earg555890/Runway-GenAi-10.27 (**make it public before submitting**)

**Demo video:** [LINK TO ADD]

**Slide deck:** [LINK OR FILE TO ADD]

**Sponsor technology explanation:** paste the text of `docs/SPONSOR_TECH.md`. The short version, if the form has a
character limit:

> Zetaris is Runway's data layer: each of the student's eight money sources is its own Lightning database
> (RUNWAY_CHECKING, RUNWAY_CARD, RUNWAY_AID, RUNWAY_BURSAR, RUNWAY_LEASE, RUNWAY_SHIFTS, RUNWAY_OPPORTUNITIES,
> RUNWAY_MEALPLAN), read over JDBC through 21 named queries, plus a federated query across checking and the credit
> card that finds recurring charges. A "Run live on Zetaris" button runs it uncached with a timer. Meterless
> Nightshift is the primary AI provider: every model call follows the Meterless Runtime 0.90.0 contract (Bearer
> token, meterless-app header, discovery from /v1/models), and each answer shows the routed model and the Meterless
> receipt. The Meterless H-MEM engine powers "What Runway remembers": what the student did, her budget, planned
> shifts and past questions, with provenance and an audit ledger, recalled into the planner across sessions. It is a
> Python port of the reference that passes the official conformance vectors (13/13). NVIDIA Nemotron, through
> Nightshift: Lightning plans the tools (JSON) and writes fast answers; Ultra writes "Think harder" answers with a
> visible reasoning trace. The model never does math: the engine computes every number, and a checker verifies every
> amount, date and reason before the answer is shown. Unique: our checker caught Nightshift's own memory injecting
> old answers into new requests, so Runway's memory feeds only the planner, never the numbers. Cursor was the development environment for
> the whole build: Claude Code ran in Cursor's integrated terminal; Cursor's own AI features were not used for code
> generation.

**Pre-existing components:** None of Runway's code or data existed before the hackathon. Git history: the first
commit is b207526, 2026-10-22 18:59 UTC (after Oct 22, 00:00 UTC); all 79 commits are by Evan Arghirescu, and every
tracked file was created on or after 2026-10-22 19:09 UTC. Used as-is (not written by us):
- Open-source Python libraries: Streamlit, openai (the OpenAI-compatible client), JayDeBeApi (JDBC), pytest.
- Sponsor tools: the Zetaris platform (local Docker bundle, v2.4.3.1) and its JDBC driver; Meterless Nightshift
  (Windows edition); NVIDIA Nemotron models.
- From the Meterless repository (Apache-2.0, published Oct 19): `hmem.py` is our Python port of the H-MEM reference
  implementation (`engines/hmem/reference`), and `tests/fixtures/hmem_conformance/vectors.json` is the official
  conformance vectors file, copied unchanged with a notice.
- The demo student (Maya) and all her data are synthetic, generated by our `generate_maya_data.py`.

**Prize split:** n/a (solo)
