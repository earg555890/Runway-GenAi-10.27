# Ask Runway: how well it answers

We asked Runway 28 realistic student questions (the original 10, plus 18 new ones: spending, transactions, bills, work hours, a balance on a date, two follow-ups, a multi-step plan, a general question, a vague one, "what should I do this week?", two budget questions, two about grants and scholarships and two about the meal plan), 2 separate times (56 answers in all), using the real NVIDIA Nemotron models. Every answer was graded automatically against numbers that Runway's money engine computes on its own. Follow-ups were asked after the question they follow, in the same chat.

The model never does the math: Runway's engine computes every number, shows a quick answer from those numbers right away, and a checker rejects any AI answer with an amount, date or reason that doesn't match the student's records.

## Fast (Nemotron Lightning, thinking off; the default): 44/56 full answers (2 runs)

- **Picked the right tool(s):** 54/56
- **Gave the right verdict:** 56/56
- **Passed every check** (numbers, dates, reasons, no repeats, not cut off): 56/56
- **Full answers** (all of the above, written by the model with every required fact): 44/56
- Answers that needed one rewrite: 19/56
- Answers where the quick answer stood in for the AI answer: 11/56
- **Quick answer:** 1.61 s median after sending. **Full AI answer:** 4.3 s median.

Not full answers: 0 because of NVIDIA service errors, 12 because of real mistakes:
  - Run 1, "Can I afford new headphones for $150?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer repeats itself ("You didn't say when you'd buy it, so I assumed tomorrow, Tue"); -$144.19 has a minus sign)
  - Run 1, "money stuff is stressing me out": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (Wed Nov 3 has the wrong weekday (it is a Tuesday)), so this is the quick answer built straight from your numbers.)
  - Run 1, "How much is left in my food budget?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (- $281 has a minus sign; write it as "$281 below zero"), so this is the quick answer built straight from your numbers)
  - Run 1, "What happens if I stick to my budget?": picked budget_status with the wrong arguments
  - Run 1, "Will my dining dollars last?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer is not in the ANSWER / WHY / DO THIS format), so this is the quick answer built straight from your numbers)
  - Run 1, "How many meal swipes will I have left at the end of the semester?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer is not in the ANSWER / WHY / DO THIS format), so this is the quick answer built straight from your numbers)
  - Run 2, "How long will my money last?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks ($53 is not in the facts), so this is the quick answer built straight from your numbers.)
  - Run 2, "Can I afford new headphones for $150?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer repeats itself ("You didn't say when you'd buy it, so I assumed tomorrow, Tue"); -$144.19 has a minus sign)
  - Run 2, "What will my balance be on Thanksgiving?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (ACCT-CHK-01 is a record ID; never write record IDs; the answer copied a calculation note ("Projected end-of-day balan)
  - Run 2, "What should I do this week?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer stops mid-sentence), so this is the quick answer built straight from your numbers.)
  - Run 2, "What happens if I stick to my budget?": picked budget_status with the wrong arguments
  - Run 2, "Will my dining dollars last?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer is not in the ANSWER / WHY / DO THIS format; the answer repeats itself ("- You'll have about 40 swipes lef)

## Think harder (Nemotron Super, thinking on): partial run, 25/26 full answers

The Think harder run was stopped after 26 of the 28 questions (the session running it was replaced), so it is not in eval_results.json and is not scored above. From its log:

- **Full answers:** 25/26; every answer passed the checks (26/26).
- 3 answer(s) were written by the Lightning fallback because Super was slow or timing out (one question took 7.5 minutes).
- **Quick answer:** 1.31 s median. **Full AI answer:** 39.7 s median.
- Not full: #24 "What happens if I stick to my budget?" (written by nvidia/nemotron-3.5-lightning-30b-a3b).
- Not asked: "If I apply for the emergency grant, when would the money come?" and "How many meal swipes will I have left at the end of the semester?".

## Run 1 (Fast): 22/28 full answers

| # | Question | Tools / right? | Verdict / right? | Checks passed | Required facts by model | Written by | Retries (plan+rewrite) | Quick answer s | Full answer s | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+1 | 1.58 | 5.26 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 9.22 | 11.13 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 0.55 | 2.11 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | all 3 | Nemotron Lightning | 0+1 | 4.28 | 7.65 | PASS |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | all 3 | a template | 0+1 | 0.89 | 19.34 | FAIL |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.98 | 2.55 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | all 0 | - | 0+0 | - | 0.95 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.47 | 2.4 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.72 | 2.81 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.78 | 5.3 | PASS |
| 11 | How much did I spend on each category in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 1.0 | 2.04 | PASS |
| 12 | How much did I spend at Kroger? | find_transactions / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.67 | 1.93 | PASS |
| 13 | What bills are due next week? | upcoming_bills / yes | - / yes | yes | all 1 | Nemotron Lightning | 0+0 | 1.07 | 2.15 | PASS |
| 14 | How many hours did I work in October? | work_summary / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.94 | 3.15 | PASS |
| 15 | What will my balance be on Thanksgiving? | balance_on / yes | - / yes | yes | all 1 | Nemotron Lightning | 0+0 | 0.7 | 2.16 | PASS |
| 16 | What can I do to make money before this? *(follow-up)* | money_ideas / yes | runs_out / yes | yes | all 3 | Nemotron Lightning | 0+0 | 1.61 | 2.88 | PASS |
| 17 | what about Nov 17 instead? *(follow-up)* | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+1 | 1.4 | 4.55 | PASS |
| 18 | Help me get through the semester | runway, money_ideas, find_leaks / yes | runs_out / yes | yes | all 9 | Nemotron Lightning | 0+0 | 0.63 | 2.97 | PASS |
| 19 | What is FAFSA verification? | general_info / yes | - / yes | yes | all 0 | Nemotron Lightning | 0+0 | - | 1.86 | PASS |
| 20 | money stuff is stressing me out | runway / yes | runs_out / yes | yes | all 2 | a template | 0+1 | 0.64 | 3.99 | FAIL |
| 21 | What should I do this week? | action_plan / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+1 | 0.73 | 10.15 | PASS |
| 22 | Where did my money go in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 0.86 | 2.19 | PASS |
| 23 | How much is left in my food budget? | budget_status / yes | - / yes | yes | all 2 | a template | 0+1 | 0.71 | 6.99 | FAIL |
| 24 | What happens if I stick to my budget? | budget_status / NO | - / yes | yes | all 2 | a template | 0+1 | 0.69 | 4.3 | FAIL |
| 25 | Are there any grants or scholarships I qualify for? | find_aid / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+1 | 0.82 | 4.07 | PASS |
| 26 | Will my dining dollars last? | meal_plan / yes | - / yes | yes | all 3 | a template | 0+1 | 0.86 | 3.72 | FAIL |
| 27 | If I apply for the emergency grant, when would the money come? | find_aid / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 1.11 | 2.57 | PASS |
| 28 | How many meal swipes will I have left at the end of the semester? | meal_plan / yes | - / yes | yes | all 3 | a template | 0+1 | 0.65 | 2.95 | FAIL |

## Run 2 (Fast): 22/28 full answers

| # | Question | Tools / right? | Verdict / right? | Checks passed | Required facts by model | Written by | Retries (plan+rewrite) | Quick answer s | Full answer s | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+1 | 3.94 | 7.12 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | all 2 | a template | 0+1 | 2.18 | 5.92 | FAIL |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+1 | 1.86 | 5.26 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | all 3 | Nemotron Lightning | 0+0 | 6.2 | 7.87 | PASS |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | all 3 | a template | 0+1 | 2.83 | 12.23 | FAIL |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | all 3 | Nemotron Lightning | 0+0 | 3.62 | 9.24 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | all 0 | - | 0+0 | - | 1.46 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 1.5 | 3.24 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 1.96 | 4.27 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 2.37 | 7.1 | PASS |
| 11 | How much did I spend on each category in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 3.28 | 5.59 | PASS |
| 12 | How much did I spend at Kroger? | find_transactions / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 2.78 | 4.82 | PASS |
| 13 | What bills are due next week? | upcoming_bills / yes | - / yes | yes | all 1 | Nemotron Lightning | 0+0 | 3.17 | 4.28 | PASS |
| 14 | How many hours did I work in October? | work_summary / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 3.04 | 4.31 | PASS |
| 15 | What will my balance be on Thanksgiving? | balance_on / yes | - / yes | yes | all 1 | a template | 0+1 | 2.66 | 8.34 | FAIL |
| 16 | What can I do to make money before this? *(follow-up)* | money_ideas / yes | runs_out / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.84 | 3.03 | PASS |
| 17 | what about Nov 17 instead? *(follow-up)* | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+0 | 1.72 | 3.5 | PASS |
| 18 | Help me get through the semester | runway, money_ideas, find_leaks / yes | runs_out / yes | yes | all 9 | Nemotron Lightning | 0+0 | 1.4 | 3.85 | PASS |
| 19 | What is FAFSA verification? | general_info / yes | - / yes | yes | all 0 | Nemotron Lightning | 0+0 | - | 3.3 | PASS |
| 20 | money stuff is stressing me out | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 1.71 | 3.45 | PASS |
| 21 | What should I do this week? | action_plan / yes | - / yes | yes | all 2 | a template | 0+1 | 2.87 | 9.84 | FAIL |
| 22 | Where did my money go in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 3.01 | 4.45 | PASS |
| 23 | How much is left in my food budget? | budget_status / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 3.07 | 4.7 | PASS |
| 24 | What happens if I stick to my budget? | budget_status / NO | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 2.25 | 8.24 | FAIL |
| 25 | Are there any grants or scholarships I qualify for? | find_aid / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 2.43 | 7.97 | PASS |
| 26 | Will my dining dollars last? | meal_plan / yes | - / yes | yes | all 3 | a template | 0+1 | 1.66 | 8.14 | FAIL |
| 27 | If I apply for the emergency grant, when would the money come? | find_aid / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+1 | 2.41 | 15.12 | PASS |
| 28 | How many meal swipes will I have left at the end of the semester? | meal_plan / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 2.07 | 4.14 | PASS |
