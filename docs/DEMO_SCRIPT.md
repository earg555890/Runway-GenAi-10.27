# Runway: 3-minute demo script (draft)

A draft for the video. Change the spoken lines freely; keep the numbers, which come straight from the app.
Record in **replay mode** (no keys, recorded answers), on **Maya's data only**. Never show the "My data" mode with
a real file (rule 7).

Start: `ANSWER_MODE=replay` and `DATA_BACKEND=local` in `.env`, then `streamlit run ui/app.py`, open
http://localhost:8501. For the Zetaris beat (2:25), run with `DATA_BACKEND=zetaris` and Zetaris up instead (see the
checklist).

## The script

| Time | Click / do | On screen | Say |
|---|---|---|---|
| **0:00-0:20** The problem | Nothing yet: the app is open at the top, Maya mode. Slowly scroll the header. | Header "Maya", today Mon, Oct 26, 2026. | "This is Maya, a sophomore. Her money is in eight places: checking, a credit card, financial aid, her student account, her lease, her work shifts, the school's aid list and her meal plan. No one app sees all of it. So she can't answer the one question that matters: will I make it to December?" |
| **0:20-0:45** Open Runway | Point at the status card, then the check-in cards, then scroll to the chart. | "Your money runs out in 2 weeks, on Mon, Nov 9." Check-in: "Hi Maya. 7 things need your attention." The balance chart dips below $0 in red. | "Runway answers before she asks. Her money runs out Monday, November 9th, when a $360 card payment is due. The check-in shows what matters most, ranked by money at stake per day. And the chart shows her balance, day by day, to the end of the semester." |
| **0:45-1:10** The flight question | In the chat, click the suggested question **"Can I afford a $400 flight home for Thanksgiving if I book it Nov 10?"** Wait for the answer. Open **Show proof** for a second. | "Yes, if you do 2 things": send the verification form (the held $1,850 refund then arrives around Thu, Nov 5) and cancel Spotify. Proof rows with the source of each number. | "She asks Runway about the flight home. The answer is yes, if she does two things. Every number comes from her own records, and the proof shows which source each one came from. The AI never does the math. Our engine does, and a checker rejects any answer with a number that doesn't match." |
| **1:10-1:20** The Apple Music insight | Point at the line about Apple Music (or open "Cancelling Apple Music won't help this semester. Why?"). | Cancelling Apple Music saves $0.00 before Dec 18: its next charge, Nov 22, is on the card bill paid Jan 7. | "Here's the part a budget app gets wrong. Cancelling Apple Music saves her zero dollars this semester. Its next charge lands on a card bill she pays in January. Spotify charges checking directly, so that's the one to cancel. With both fixes, her lowest point is $5.81. Tight, but she makes it." |
| **1:20-1:30** The timing moment | Click **"Can I afford a $400 flight home for Thanksgiving?"** (no date). | "Not right now." With no date, Runway assumes tomorrow, before the refund arrives, and says so. | "Same flight, no date. Now the answer is 'not right now', because booking tomorrow comes before the refund. Timing is the whole story." |
| **1:30-2:00** Real actions | In the check-in card for the verification form, click **Remind** (a calendar file downloads), then **Email** (show the draft to finaid@stateu.example, don't send), then **Form sent**. | The status card and chart update: no longer below zero, ending the semester around $437. Runway's chat message says what changed. | "Runway drafts the actions, and Maya approves each one. A reminder for her calendar. An email to financial aid, ready to send from her own email app. Runway never sends anything by itself. When she marks the form as sent, the forecast updates right away: she stays above zero all semester. And Runway tells her what changed." |
| **2:00-2:10** Budget | Click the **Budget** tab. Point at the sentence and the donut. Click **Suggest a budget**. | "So far in October, you spent $1,757. Most went to Rent ($725) and Shopping ($461)." Suggested budget amounts. | "The budget starts from what's actually left after rent and bills, and suggests one from her usual spending." |
| **2:10-2:25** Find money and meal plan | Click **Find money**. Point at the $500 emergency grant and its **If approved** switch, then the $1,000 spring scholarship. Then click **Semester** and point at the meal plan card. | Emergency grant: applying Tue, Oct 27 it would arrive Mon, Nov 2, before she runs out. Spring scholarship: pays in January, so $0.00 this semester. "Found online - check before applying" below. Meal plan: dining dollars run out around Sun, Nov 22; move 2 meals a week to swipes. | "Find money checks the school's grants against her profile. The emergency grant could arrive November 2nd, but only if approved, so it's never counted as certain money. The spring scholarship helps zero this semester: same timing lesson. And her meal plan tip: move two meals a week to swipes, and both last to December." |
| **2:25-2:45** Behind the scenes | Open **Behind the scenes**. Click **Run live on Zetaris** and let the timer run. Then show the reasoning in "How Runway thought about this" on a Think harder answer. | The federated SQL across RUNWAY_CHECKING and RUNWAY_CARD with a live timer and the rows. The 8 sources. Nemotron's reasoning. Eval score: **SCORE_PLACEHOLDER**. | "Under the hood: each source is its own database on Zetaris, eight in all. This query runs live across her checking and card to find charges that repeat. NVIDIA Nemotron plans which tools to run, and explains the answer. Here's its reasoning. We tested it on 28 real questions, three times: SCORE_PLACEHOLDER_SPOKEN." |
| **2:45-3:00** Impact and roadmap | Scroll back to the top: the status card now says she makes it. | The green status card. | "Students drop out over a few hundred dollars. Runway shows them the problem weeks early, explains why, and drafts the fix. Next: bank connections with consent, school integrations, verified scholarship databases, and a mobile app. Runway: know if you'll make it, and why." |

## Recording checklist

- [ ] `.env`: `ANSWER_MODE=replay`, `DATA_BACKEND=local` (or `zetaris` for the 2:25 beat, with the Zetaris
      bundle healthy: `./verify.sh` in the bundle folder, and `python load_zetaris.py` done). No real data loaded.
- [ ] Restart the app after changing `.env`. Start from a fresh session (reload the page): nothing marked done,
      no what-ifs on, the chat empty.
- [ ] Light mode (browser and Streamlit theme). Browser zoom 110-125% so text is readable in the video.
- [ ] Window about 1440 x 900 (or 1280 x 800). Close other tabs, hide bookmarks, turn off notifications.
- [ ] Do one practice pass: the suggested questions answer instantly from recorded answers.
- [ ] Don't click Send in any email app. Don't show `.env`, keys or the terminal with keys.
- [ ] My data mode stays off in the video.

## Judge tour (1 page)

1. **Top of the page:** the status card ("Your money runs out in 2 weeks, on Mon, Nov 9.") and the check-in. Try
   **Remind**, **Email** and **Form sent** on the first card: the forecast changes at once. **Undo** puts it back.
2. **Chat:** click the suggested questions. The flight question with a date says "Yes, if you do 2 things"; without
   a date it says "Not right now". Open **Show proof** to see where each number came from. Type a follow-up
   ("what about Nov 17 instead?") if a key is set.
3. **What-if panel:** turn fixes on and off; the chart and numbers update instantly, with no AI call.
4. **Budget tab:** where the money went, **Suggest a budget**, **Use my budget in my forecast**.
5. **Afford it?** tab: add a purchase and see how it changes the semester.
6. **Find money tab:** the school's grants ("if approved" switches), then "Found online - check before applying"
   (web results with links; amounts only when the page states them).
7. **Findings tab:** the money leaks, with the Apple Music vs Spotify timing explained.
8. **Behind the scenes** (bottom): the 8 data sources, **Run live on Zetaris** (needs Zetaris), the AI's plan and
   reasoning, and the log of what Runway drafted and what was approved.
9. **Results:** `eval_summary.md` has the 28-question evaluation against the real NVIDIA models.
