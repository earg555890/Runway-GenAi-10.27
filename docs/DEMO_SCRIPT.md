# Runway: demo video script (live, 3:45)

The official rules: **1-4 minutes**, about 70% live product and 30% concept, **no static screenshots**: questions
are typed on camera and the AI answers are generated live. A 30-45 second "under the hood" segment. No third-party
music, no watermarks, no logos or trademarks we don't own. Upload to YouTube (unlisted), Vimeo or Google Drive
("anyone with the link"), or an MP4 under 300 MB. Track: **The Agent That Can Explain Why**.

How we record: **live mode** (`ANSWER_MODE=live`), **fast mode** (Think harder off), questions **typed** in the chat.
Every answer goes through **Meterless Nightshift** to **NVIDIA Nemotron**; the data comes from **Zetaris**.
The live demo launcher sets the fast-answer model to **Nemotron Ultra, thinking off**
(`FAST_EXPLAIN_MODEL=nvidia/nemotron-3-ultra-550b-a55b`); Nemotron Lightning still plans every question. Why: Nightshift
injects its own memories of earlier answers into each request, and Ultra ignores them better. In the Oct 26 spot
check of 5 questions through Nightshift, Ultra wrote 5/5 full answers in **about 2-13 s** each (Lightning: 2/5).
So expect each typed answer to take about 2-13 s: the quick answer shows in about 1 s, then the full answer streams.
Maya's synthetic data only. Never show "My data" mode, `.env`, keys or a terminal with keys (rule 7).
Start everything with **`Start Runway (Live demo).bat`** (see the checklist below).

Numbers below are what the app showed in rehearsals on Oct 26 (live, fast mode, Zetaris). The engine's numbers
never change; the AI's wording can, so read what is on screen rather than these lines word for word.

## The script (3:42)

| Time | Click / do | On screen | Say |
|---|---|---|---|
| **0:00-0:10** The problem | Pitch deck slide 1 (or the app header if there are no slides). | The problem slide. | "Students drop out over a few hundred dollars. Not because they overspend. Because they can't see what's coming." |
| **0:10-0:20** Maya | Slide 2. | Maya and her eight money sources. | "Meet Maya. Her money lives in eight places: checking, a credit card, financial aid, her student account, her lease, her job, her meal plan and the school's aid list." |
| **0:20-0:30** The solution | Slide 3. Then switch to the browser with Runway open. | Runway: an AI agent that explains why. | "Runway reads all eight, projects her money to December, explains why, and drafts the fix. She approves every action." |
| **0:30-0:44** Open Runway | The app at the top (light mode): the navy Runway band, then the status card and the check-in. Scroll a little to the graph card. | Board label **RUNS OUT · MON, NOV 9** and "Your money runs out in 2 weeks, on Mon, Nov 9." "Hi Maya. 6 things need your attention." The graph "Your money through Dec 18": a solid line that turns red after Nov 9, and a dotted green line, "If you follow the steps", with "With the steps: lowest $5.81". | "Runway speaks first. Her money runs out November 9th, when a $360 card payment is due. The solid line is what's happening. The dotted line is what happens if she follows the steps." |
| **0:44-1:06** The flight question | Click the round **Ask Runway** button (bottom-left). In the panel, click the box and **type**: `Can I afford a $400 flight home for Thanksgiving if I book it Nov 10?` Enter. Let it stream. Then click the proof chip **"2 · $1,850"** and point at **Do these** (don't click it). | The chat panel: "Understanding your question...", the quick answer at once, then the answer streaming in (about 9 s with Ultra). **"Yes, if you do 2 things."** Proof chips; the refund row from her student account. | "She asks from anywhere in the app. Nemotron plans which tools to run. Our engine does all the math, so a quick answer shows in about a second. Then Nemotron writes the full answer, and a checker rejects any number that isn't in her records. Yes, if she does two things. Every number has proof." |
| **1:06-1:15** The Apple Music insight | Point at the note under DO THIS. | "Cancelling Apple Music saves $0.00 this semester: Apple Music is billed to the credit card, and that card bill is paid after the semester ends." | "Here's what a budget app gets wrong. Cancelling Apple Music saves zero this semester: that card bill is paid in January. Spotify hits checking, so cancel that one." |
| **1:15-1:27** The timing moment | In the panel, **type**: `Can I afford a $400 flight home for Thanksgiving?` Enter. | **"Not right now."** Lowest point $394 below zero on Mon, Nov 2. "You didn't say when you'd buy it, so I assumed tomorrow, Tue, Oct 27." | "Same flight, no date. Not right now: tomorrow comes before the refund. Runway says what it assumed." |
| **1:27-1:36** A follow-up | **Type**: `what about Nov 17 instead?` Enter. | "Answering: Can I afford a $400 flight home for Thanksgiving if I book it Nov 17 instead?" **"Yes, if you do 2 things."** | "She can just follow up. Runway knows she means the flight." |
| **1:36-1:50** Under the hood: Nightshift | Still in the panel: open **How Runway thought about this** on the first answer, switch on **Details for nerds**. | "Planned by: Nemotron Lightning ... through Meterless Nightshift, receipt rcpt_..."; "Written by: Nemotron Ultra (nvidia/nemotron-3-ultra-550b-a55b) through Meterless Nightshift, receipt rcpt_..."; the number check; the plan JSON and every model call with its routed model. | "Under the hood. Every request goes through Meterless Nightshift to NVIDIA Nemotron: Lightning plans, Ultra writes. The receipt shows which model answered. Here's the plan, which Python validates before any tool runs." |
| **1:50-2:04** Form sent | Close the panel (**X**). In the check-in card **"Send your verification form"**, open **Email** for a second (don't send), then click **Form sent**. | **"You're covered all semester."**, board label **COVERED · DEC 18**. The graph: the solid line stays above $0 (blue) all semester; the dotted line now only adds cancelling Spotify. | "Runway drafts the email; Maya sends it herself. She marks the form as sent, and the whole forecast updates instantly, with no AI call." |
| **2:04-2:14** Shift planner | **Semester** tab, scroll to **Shift planner**: click **+4h this Saturday**, then **+4h next Saturday**. | "These 2 shifts add $115 and you're covered all semester." Sat, Oct 31 adds $57.35, paid Tue, Nov 3. Sat, Nov 7 adds $57.35, paid Wed, Nov 18. | "Extra shifts show what each one adds after withholding, and when it's actually paid." |
| **2:14-2:22** Budget | **Budget** tab. Point at the sentence and the donut. | "So far in October, you spent $1,757. Most went to Rent ($725) and Shopping ($461)." | "Budget shows where October went." |
| **2:22-2:32** Find money | **Find money** tab. Point at **Student Emergency Grant**, switch on **If approved**. | "Student Emergency Grant · Up to $500 · Apply anytime. If approved, it arrives around Mon, Nov 2." | "Find money matches her to school aid. It only counts if she switches on 'if approved'. A maybe is never money." |
| **2:32-2:40** The provider checks | Scroll to **Behind the scenes** (bottom), open it > **AI provider**. | The checks table: Connection HTTP 200; Authorization online; a wrong token shows unauthorized; model discovery; text requests, each with its routed model and receipt. | "Runway checks Nightshift the official way: connection, authorization, model discovery, and a real request." |
| **2:40-3:00** Zetaris, live | Scroll to **Run live on Zetaris**, click it. Talk while the timer runs (about 18 s). | The timer "Running on Zetaris... 12.4 s", then "Zetaris answered in 18.2 s: 13 rows from card and checking." and the SQL across `RUNWAY_CHECKING` and `RUNWAY_CARD`. | "The data layer is Zetaris: eight separate databases. This federated query runs live across her checking and her card, to find charges that repeat every month. No cache." |
| **3:00-3:08** The code | Editor: `agent.py`, `run()` at line 2506. Scroll `# PLAN` (2548), `# EXECUTE` (2585), `# EXPLAIN + CHECK` (2608). | One PLAN call, the tools in plain Python, one EXPLAIN call, then the check. | "The whole agent is this loop: plan, deterministic tools, explain, check. Two model calls per question." |
| **3:08-3:30** Memory (Meterless H-MEM) | Back to the browser. Click **Ask Runway**, open **What Runway remembers** at the bottom of the panel. Close the panel, **reload the page** (a new session) and point at the first check-in card. | The memories, each with where it came from: "Marked done: Form sent (Send your verification form).", "Plans extra shifts: Sat, Oct 31 (4 hours), Sat, Nov 7 (4 hours).", short notes of her questions. After the reload, on the form card: **"Last time you clicked "Form sent". Still true? Click it again."** | "Runway remembers, with Meterless H-MEM. Every memory says where it came from, and she can forget it. Next session, Runway picks up where she left off. Memory helps the planner understand her. The numbers still come only from her records." |
| **3:30-3:42** Close | Scroll to the top. | The status card. | "Every answer Runway showed in our 29-question test passed the number check. Next: bank connections with consent, school integrations, a mobile app. Runway: know if you'll make it, and why." |

The chat lives behind the round **Ask Runway** button (bottom-left, on every tab); the panel covers the page while it's open, so close it (X) before clicking on the page. The memory beat reloads the page, so it comes last. "What Runway remembers" fills
up during the demo; the checklist clears it before recording.

### If something goes wrong while recording

- **A live answer is slow:** answers usually take about 2-13 s with Ultra. While it writes, keep talking (the beat's
  spoken line fits that wait). The quick answer is already on screen, and it's real: it's built from the engine's
  numbers and passes the same checks. If the full answer takes more than about 20 s, re-take that beat.
- **The answer falls back to the quick answer** (a grey note says the AI answer didn't pass the checks, or a model
  wasn't available): keep it. That's the checker doing its job, and every number is still correct and proven. Say
  "the checker caught a problem, so Runway kept the answer built from her numbers". If you'd rather show the AI
  answer, click **New chat** and re-take the beat.
- **"Double-checking the numbers..."** appears: keep recording. That's the one allowed rewrite (rule 10); it adds a
  few seconds. With Ultra as the fast model no rewrite was needed in the 5-question spot check, but it can happen.
- **Nightshift or NVIDIA is down** (the check in `Start Runway (Live demo).bat` says NOT READY, or answers keep
  falling back): check that Nightshift is open (and its Runtime token in `.env` is current), wait a few minutes and
  run `.venv\Scripts\python demo_check.py` again. As a last resort, record with `ANSWER_MODE=cached`
  (`Start Runway.bat`). Those are real earlier answers typed out, so say so on screen ("recorded earlier").
- **Zetaris is slow or down:** the button shows the error or the timer passes 60 s. Cut the Zetaris beat to the
  8-sources list and say "federated by Zetaris". The app keeps working on the cached Zetaris results.
- **A click goes wrong** (wrong tab, toggle left on): use **Start over** on the Semester tab or reload the page
  (a reload clears the chat and every what-if), then re-take from the start of that beat.

## Recording checklist

- [ ] **Restart the laptop** first (frees memory; the Zetaris containers run under emulation on this ARM laptop).
- [ ] Open **only** Docker Desktop, Runway (via the launcher), one browser window and the code editor with
      `agent.py`. Close chat apps, mail and other browser windows. Hide the bookmarks bar.
- [ ] **Turn off notifications:** Windows Focus / Do not disturb on. Mute the phone.
- [ ] Docker Desktop: the Zetaris containers are running (`./verify.sh` in `C:\Users\Evana\zetaris-platform`).
- [ ] Double-click **`Start Runway (Live demo).bat`**. It:
      1. checks Meterless Nightshift (connection, authorization, discovery) and asks one real question
         through it (`demo_check.py`), printing the model that answered and READY or NOT READY;
      2. stops any Runway already running on 8501;
      3. uses Zetaris if it's up (else Maya's local files, with a message);
      4. moves the saved answers aside, so every answer is really generated live;
      5. starts Runway in live mode and opens the browser.
- [ ] **Warm the Zetaris cache and the JVM:** wait for the first page (about 10 s with the Zetaris cache, up to
      90 s if it's cold). Then open **Behind the scenes** and click **Run live on Zetaris** once (the first click
      starts Java; after that it takes about 18 s). Reload the page afterwards.
- [ ] **Light mode:** browser and Streamlit theme (menu ⋮ > Settings > choose the light theme).
- [ ] **Readable at 1080p:** browser window 1920 x 1080 (full screen), zoom **125%** (Ctrl +). Check that the
      chat text and the status card are easy to read in a test recording.
- [ ] **Meterless Nightshift is open** (Windows edition), with NVIDIA in Setup > Providers. The launcher's check
      prints "Nightshift: ... online" and the model that answered.
- [ ] **Clear the memory:** open **What Runway remembers** and click **Forget everything** (rehearsals leave
      memories, and the memory beat should start from this recording's own actions).
- [ ] Reload so the chat is empty, nothing is marked done, no what-ifs are on, Think harder is **off**.
- [ ] In the editor, open `agent.py` at line 2506 (`def run(`), font size large enough for 1080p.
- [ ] One practice pass of the typed questions (then reload). Live answers take about 2-13 s each (fast mode, Ultra).
      The launcher's check prints "written by Nemotron Ultra ... through Meterless Nightshift" and READY.
- [ ] Don't click Send in any email app. Don't show `.env`, keys or a terminal with keys. My data mode stays off.
- [ ] No music, or only music we made or have rights to. No watermarks. Show only our own app, slides and code.
- [ ] After recording: watch it once in full; check it's **under 4 minutes** (aim for 3:45) and every number is
      readable. Upload as
      YouTube unlisted (or Vimeo, or Drive "anyone with the link"), or export an MP4 under 300 MB.
- [ ] After the demo: `Start Runway.bat` (or `Stop Runway.bat`) puts Runway back in cached mode.

## Judge tour (1 page)

1. **Top of the page:** the status card ("Your money runs out in 2 weeks, on Mon, Nov 9.") and the check-in. Try
   **Remind**, **Email** and **Form sent** on the first card: the forecast changes at once. **Undo** puts it back.
2. **Chat:** click the round **Ask Runway** button (bottom-left, on every tab) and pick a suggested question. The flight question with a date says "Yes, if you do 2 things"; without
   a date it says "Not right now". Click a proof chip to see where each number came from. Type a follow-up
   ("what about Nov 17 instead?") if a key is set.
3. **What-if panel:** turn fixes on and off; the chart and numbers update instantly, with no AI call.
4. **Shift planner** (Semester tab): add Saturday shifts and see each one's pay and payday.
5. **Budget tab:** where the money went, **Suggest a budget**, **Use my budget in my forecast**.
6. **Afford it?** tab: add a purchase and see how it changes the semester.
7. **Find money tab:** the school's grants ("if approved" switches), then "Found online - check before applying"
   (web results with links; amounts only when the page states them).
8. **Findings tab:** the money leaks, with the Apple Music vs Spotify timing explained.
9. **What Runway remembers** (at the bottom of the chat panel): what she marked done, her budget and shifts, and notes from past
   chats (Meterless H-MEM), each with where it came from; Forget, "This isn't right", Forget everything. Reload the
   page: the check-in says "Last time you clicked ..." for anything she did in an earlier session.
10. **Behind the scenes** (bottom): the 8 data sources, the AI provider checks (Meterless Nightshift), **Run live on
   Zetaris** (needs Zetaris), the AI's plan and
   reasoning ("How Runway thought about this" > "Details for nerds"), and the log of what Runway drafted and what
   was approved.
11. **Results:** `eval_summary.md` has the 29-question evaluation against the real NVIDIA models.
