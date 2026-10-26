# Runway: 4-minute demo video script (live)

The video rules: 3-5 minutes (judges stop at 5), about 70% live product and 30% concept, **no static
screenshots**: questions are typed on camera and the AI answers are generated live. A 30-45 second "under the hood"
segment. No third-party music, no watermarks, no logos or trademarks we don't own. Upload to YouTube (unlisted),
Vimeo or Google Drive ("anyone with the link"), or an MP4 under 300 MB.

How we record: **live mode** (`ANSWER_MODE=live`), **fast mode** (Think harder off), questions **typed** in the chat.
Maya's synthetic data only. Never show "My data" mode, `.env`, keys or a terminal with keys (rule 7).
Start everything with **`Start Runway (Live demo).bat`** (see the checklist below).

Numbers below are what the app showed in a full rehearsal on Oct 26 (live, fast mode, Zetaris). The engine's numbers
never change; the AI's wording can, so read what is on screen rather than these lines word for word.

## The script

| Time | Click / do | On screen | Say |
|---|---|---|---|
| **0:00-0:15** The problem | Pitch deck slide 1 (or the app header if there are no slides). | The problem slide. | "Students drop out over a few hundred dollars. Not because they overspend. Because they can't see what's coming." |
| **0:15-0:28** Maya | Slide 2. | Maya and her eight money sources. | "Meet Maya, a sophomore. Her money lives in eight places: checking, a credit card, financial aid, her student account, her lease, her work shifts, her meal plan and the school's aid list. No one app sees all of it." |
| **0:28-0:40** The solution | Slide 3. Then switch to the browser with Runway open. | Runway: an AI agent that explains why. | "Runway is an AI agent that reads all eight, projects her money to the end of the semester, explains why, and drafts the fix. She approves every action." |
| **0:40-0:55** Open Runway | The app is open at the top (light mode). Point at the status card, the check-in, then scroll to the chart. | **"Your money runs out in 2 weeks, on Mon, Nov 9."** Check-in: "Hi Maya. 6 things need your attention." The chart turns red after Nov 9; lowest point $1,462 below zero. | "Runway speaks first. Her money runs out on November 9th, when a $360 card payment is due. The check-in ranks what matters. The chart shows every day to December." |
| **0:55-1:20** The flight question | Click the chat box and **type**: `Can I afford a $400 flight home for Thanksgiving if I book it Nov 10?` Press Enter. Let it stream. | Stages: "Understanding your question..." then the quick answer at once, then the AI answer streaming in over it ("Writing your answer..."). It may say **"Double-checking the numbers..."** and write it again: that's the checker. Final: **"Yes, if you do 2 things."** Send the verification form (the $1,850 refund arrives around Thu, Nov 5); cancel Spotify ($23.98). Lowest point $5.81 on Mon, Nov 2. | "Can she fly home? She types the question. Nemotron plans which tools to run. Our engine does all the math, so she gets a quick answer in about a second. Then Nemotron writes the full answer. A checker rejects any number that isn't in her records. The answer: yes, if she does two things." |
| **1:20-1:30** Proof and "Do these" | Click the proof chip **"2 · $1,850"**. Point at the **Do these** button (don't click it). | The proof table: the refund row from her student account. The **Do these** button beside DO THIS. | "Every number has proof. This one comes from her student account. One click on 'Do these' would try both fixes in her forecast." |
| **1:30-1:42** The Apple Music insight | Point at the small note under DO THIS (proof chip **"5 · $0.00"** if you like). | "Cancelling Apple Music saves $0.00 this semester: Apple Music is billed to the credit card, and that card bill is paid after the semester ends." | "Here's what a budget app gets wrong. Cancelling Apple Music saves her zero dollars this semester. It's on her card, and that bill is paid in January. Spotify charges checking directly, so that's the one to cancel. Her lowest point is $5.81. Tight, but she makes it." |
| **1:42-1:58** The timing moment | **Type**: `Can I afford a $400 flight home for Thanksgiving?` Enter. | **"Not right now."** Lowest point $394 below zero on Mon, Nov 2. Note: "You didn't say when you'd buy it, so I assumed tomorrow, Tue, Oct 27." | "Same flight, no date. Now it's 'not right now'. Booking tomorrow comes before the refund arrives. Runway says what it assumed. Timing is the whole story." |
| **1:58-2:12** A follow-up | **Type**: `what about Nov 17 instead?` Enter. | Under her message: "Answering: Can I afford a $400 flight home for Thanksgiving if I book it Nov 17 instead?" Answer: **"Yes, if you do 2 things."** | "She can just follow up. Runway knows she means the flight, and answers for November 17th." |
| **2:12-2:30** Form sent: the forecast turns | Scroll up to the check-in card **"Send your verification form"**. Open **Email** for a second (the draft to financial aid; don't send). Then click **Form sent**. | The status card turns to **"You're covered all semester."** The chart goes blue. Runway says in the chat: "Nice. With the form sent, your refund should arrive around Wed, Nov 4. Your money now lasts all semester. Your lowest point is $5.81 on Mon, Nov 2." | "Runway drafts the email to financial aid. Maya sends it herself; Runway never sends anything. She marks the form as sent. The whole forecast updates instantly, with no AI call. She's covered all semester." |
| **2:30-2:45** Shift planner | Click the **Semester** tab, scroll to **Shift planner**. Click **+4h this Saturday**, then **+4h next Saturday**. | "These 2 shifts add $115 and you're covered all semester." Sat, Oct 31 adds $57.35, paid Tue, Nov 3. Sat, Nov 7 adds $57.35, paid Wed, Nov 18. | "Thinking about extra shifts? Each one shows what it adds after withholding, and when it's actually paid. The second Saturday is paid on November 18th." |
| **2:45-2:57** Budget | Click the **Budget** tab. Point at the sentence and the donut. Click **Suggest a budget**. | "So far in October, you spent $1,757. Most went to Rent ($725) and Shopping ($461)." Suggested amounts appear. | "Budget shows where October went, and suggests a budget from her real spending." |
| **2:57-3:10** Find money | Click the **Find money** tab. Point at **Student Emergency Grant**, then switch on **If approved**. | "Student Emergency Grant · Up to $500 · Apply anytime. If approved, it arrives around Mon, Nov 2." "Nothing here is certain until it's approved." | "Find money matches her to school aid. This grant could arrive November 2nd. It only counts if she switches on 'if approved'. Runway never treats a maybe as money." |
| **3:10-3:22** Under the hood: the plan and the checks | Scroll up to the flight answer. Open **How Runway thought about this**, switch on **Details for nerds**. Then switch to the second browser tab (the Think harder answer, see the checklist) and point at **Nemotron's reasoning**. | "Written by: Nemotron Lightning", "Number check: all 4 dollar amounts and 2 dates match your records", "Required facts: 4 of 4 written by the model". The plan JSON: `{"tool": "can_afford", "args": {"cost": "400.00", "item": "flight home", "account": "checking", "date": "2026-11-10"}}`. In tab 2: Nemotron Super's reasoning. | "Under the hood. Nemotron's first call writes this plan: which tool, which arguments. Python validates it, runs the tools and does every calculation. Nemotron's second call writes the answer, and the checker verifies every number. With 'Think harder', Nemotron Super shows its reasoning." |
| **3:22-3:40** Zetaris, live | Back in tab 1, open **Behind the scenes** at the bottom. Point at the 8 sources, then click **Run live on Zetaris**. Talk while the timer runs. | "Maya's 8 data sources ... federated by Zetaris." The timer "Running on Zetaris... 12.4 s", then "Zetaris answered in 18.2 s: 13 rows from card and checking." and the SQL across `RUNWAY_CHECKING` and `RUNWAY_CARD`. | "Each source stays separate: eight databases on Zetaris. This button runs one federated query, live, across her checking account and her credit card to find charges that repeat every month. No cache. Here are the rows." |
| **3:40-3:50** The code | Switch to the editor: `agent.py`, function `run()` (line 2471). Scroll from `# PLAN` (line 2508) through `# EXECUTE` (2543) to `# EXPLAIN + CHECK` (2566). | The code: one PLAN call, the tools in plain Python, one EXPLAIN call, then the check. | "The whole agent is this loop. One plan call, then deterministic tools, then one explain call, then the check. No open-ended tool loop. Two model calls per question." |
| **3:50-4:00** Results and roadmap | Back to the browser, scroll to the top: the status card says she's covered. | "You're covered all semester." | "We tested Runway on 29 questions, three times, with the real models. All 87 answers it showed passed the checks. Think harder wrote 28 of 29 in full. Next: bank connections with consent, school integrations, and a mobile app. Runway: know if you'll make it, and why." |

### If something goes wrong while recording

- **A live answer is slow** (no text after about 10 seconds): keep recording and keep talking. The quick answer is
  already on screen, and it's real: it's built from the engine's numbers and passes the same checks. Say "the quick
  answer is already here; the full answer is still being written". If it takes more than 20 seconds, re-take that
  beat.
- **The answer falls back to the quick answer** (a grey note says the AI answer didn't pass the checks, or a model
  wasn't available): keep it. That's the checker doing its job, and every number is still correct and proven. Say
  "the checker caught a problem, so Runway kept the answer built from her numbers". If you'd rather show the AI
  answer, click **New chat** and re-take the beat.
- **"Double-checking the numbers..."** appears: keep recording. That's the one allowed rewrite (rule 10). In the
  rehearsal the Nov 10 flight question needed it every time, and it added about 2 seconds.
- **NVIDIA is down** (the check in `Start Runway (Live demo).bat` says NOT READY, or answers keep falling back): wait
  a few minutes and run `.venv\Scripts\python demo_check.py` again. As a last resort, record with `ANSWER_MODE=cached`
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
      1. checks the NVIDIA endpoint with one real question (`demo_check.py`) and prints READY or NOT READY;
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
- [ ] **Tab 2 for the reasoning beat:** open a second tab on http://localhost:8501, switch on **Think harder**, and
      type `How long will my money last?`. It takes about a minute. Open **How Runway thought about this** there so
      **Nemotron's reasoning** is visible. Leave the tab ready and go back to tab 1.
- [ ] Tab 1: reload so the chat is empty, nothing is marked done, no what-ifs are on, Think harder is **off**.
- [ ] In the editor, open `agent.py` at line 2471 (`def run(`), font size large enough for 1080p.
- [ ] One practice pass of the typed questions (then reload). Live answers take about 3-8 s each in fast mode.
- [ ] Don't click Send in any email app. Don't show `.env`, keys or a terminal with keys. My data mode stays off.
- [ ] No music, or only music we made or have rights to. No watermarks. Show only our own app, slides and code.
- [ ] After recording: watch it once in full; check it's 3-5 minutes and every number is readable. Upload as
      YouTube unlisted (or Vimeo, or Drive "anyone with the link"), or export an MP4 under 300 MB.
- [ ] After the demo: `Start Runway.bat` (or `Stop Runway.bat`) puts Runway back in cached mode.

## Judge tour (1 page)

1. **Top of the page:** the status card ("Your money runs out in 2 weeks, on Mon, Nov 9.") and the check-in. Try
   **Remind**, **Email** and **Form sent** on the first card: the forecast changes at once. **Undo** puts it back.
2. **Chat:** click the suggested questions. The flight question with a date says "Yes, if you do 2 things"; without
   a date it says "Not right now". Click a proof chip to see where each number came from. Type a follow-up
   ("what about Nov 17 instead?") if a key is set.
3. **What-if panel:** turn fixes on and off; the chart and numbers update instantly, with no AI call.
4. **Shift planner** (Semester tab): add Saturday shifts and see each one's pay and payday.
5. **Budget tab:** where the money went, **Suggest a budget**, **Use my budget in my forecast**.
6. **Afford it?** tab: add a purchase and see how it changes the semester.
7. **Find money tab:** the school's grants ("if approved" switches), then "Found online - check before applying"
   (web results with links; amounts only when the page states them).
8. **Findings tab:** the money leaks, with the Apple Music vs Spotify timing explained.
9. **Behind the scenes** (bottom): the 8 data sources, **Run live on Zetaris** (needs Zetaris), the AI's plan and
   reasoning ("How Runway thought about this" > "Details for nerds"), and the log of what Runway drafted and what
   was approved.
10. **Results:** `eval_summary.md` has the 29-question evaluation against the real NVIDIA models.
