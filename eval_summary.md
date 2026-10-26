# Ask Runway: how well it answers

We asked Runway 29 realistic student questions (the original 10, plus 19 new ones: spending, transactions, bills, work hours, a balance on a date, two follow-ups, a multi-step plan, a general question, a vague one, "what should I do this week?", two budget questions, two about grants and scholarships, two about the meal plan and the shift planner), 3 separate times (87 answers in all), using the real NVIDIA Nemotron models. Every answer was graded automatically against numbers that Runway's money engine computes on its own. Follow-ups were asked after the question they follow, in the same chat.

The model never does the math: Runway's engine computes every number, shows a quick answer from those numbers right away, and a checker rejects any AI answer with an amount, date or reason that doesn't match the student's records.

## Fast (Nemotron Lightning, thinking off; the default): 48/58 full answers (2 runs)

- **Picked the right tool(s):** 54/58
- **Gave the right verdict:** 56/58
- **Passed every check** (numbers, dates, reasons, no repeats, not cut off): 58/58
- **Full answers** (all of the above, written by the model with every required fact): 48/58
- Answers that needed one rewrite: 10/58
- Answers repaired (removed duplicate line, no words changed): 1/58
- Answers where the quick answer stood in for the AI answer: 8/58
- **Quick answer:** 0.83 s median after sending. **Full AI answer:** 2.95 s median.

Not full answers: 3 because of NVIDIA service errors, 7 because of real mistakes:
  - Run 1, "Can I afford new headphones for $150?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer copied a calculation note ("Without fixes the lowest balance is -$1,612.37; wi"); say it in plain words; -)
  - Run 1, "Is there a week coming up where money gets really tight?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (Mon, Nov 16 is not a date in the facts), so this is the quick answer built straight from your numbers.)
  - Run 1, "What will my balance be on Thanksgiving?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer copied a calculation note ("is the projected end-of-day balance on Thu Nov 26,"); say it in plain words), )
  - Run 1, "What happens if I stick to my budget?": picked budget_status with the wrong arguments
  - Run 2, "Can I afford new headphones for $150?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer copied a calculation note ("Without fixes the lowest balance is -$1,612.37; ev"); say it in plain words; -)
  - Run 2, "What will my balance be on Thanksgiving?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (-$284.80 has a minus sign; write it as "$284.80 below zero"), so this is the quick answer built straight from your nu)
  - Run 2, "What happens if I stick to my budget?": picked budget_status with the wrong arguments

## Think harder (Nemotron Super, thinking on): 28/29 full answers (1 run)

- **Picked the right tool(s):** 28/29
- **Gave the right verdict:** 29/29
- **Passed every check** (numbers, dates, reasons, no repeats, not cut off): 29/29
- **Full answers** (all of the above, written by the model with every required fact): 28/29
- Answers that needed one rewrite: 1/29
- Answers repaired (removed duplicate line, no words changed): 0/29
- Answers where the quick answer stood in for the AI answer: 0/29
- **Quick answer:** 1.01 s median after sending. **Full AI answer:** 59.07 s median.

Not full answers: 0 because of NVIDIA service errors, 1 because of real mistakes:
  - Run 3, "What happens if I stick to my budget?": picked budget_status with the wrong arguments

## After the fix (targeted re-run, not part of the scores above)

In the fast runs above, 3 answers were counted as "NVIDIA service errors". They weren't outages: the planner (Nemotron
Lightning) wrote the shift what-if plan with two closing brackets swapped (`]}` for `}]`), twice in a row, so Runway
matched the question by keywords instead. Runway now repairs one swapped pair of brackets before checking the plan.
We then asked only the two shift questions again ("What if I pick up a 5 hour shift on Nov 7?" and "What if I work
4 hours this Saturday and next Saturday?"):

- **Fast, twice:** 4/4 full answers; the planner gave a valid plan every time.
- **Think harder, once:** the shift planner question was a full answer. The 5-hour shift question got a valid plan,
  but NVIDIA's Super model returned a server error (InternalServerError) and Lightning failed too, so the quick
  answer from the engine stood in.

## Run 1 (Fast): 24/29 full answers

| # | Question | Tools / right? | Verdict / right? | Checks passed | Required facts by model | Written by | Retries (plan+rewrite) | Quick answer s | Full answer s | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+0 | 1.1 | 2.29 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.57 | 2.12 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 0.52 | 5.41 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | all 3 | Nemotron Lightning | 0+1 | 2.49 | 7.7 | PASS (repaired) |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | all 3 | a template | 0+1 | 0.87 | 5.49 | FAIL |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | all 3 | Nemotron Lightning | 0+0 | 1.0 | 2.69 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | all 0 | - | 0+0 | - | 0.48 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.55 | 6.3 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.67 | 3.12 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | all 2 | a template | 0+1 | 0.49 | 6.12 | FAIL |
| 11 | How much did I spend on each category in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 0.85 | 2.03 | PASS |
| 12 | How much did I spend at Kroger? | find_transactions / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.81 | 2.18 | PASS |
| 13 | What bills are due next week? | upcoming_bills / yes | - / yes | yes | all 1 | Nemotron Lightning | 0+0 | 0.9 | 2.19 | PASS |
| 14 | How many hours did I work in October? | work_summary / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 1.29 | 2.84 | PASS |
| 15 | What will my balance be on Thanksgiving? | balance_on / yes | - / yes | yes | all 1 | a template | 0+1 | 0.64 | 9.49 | FAIL |
| 16 | What can I do to make money before this? *(follow-up)* | money_ideas / yes | runs_out / yes | yes | all 3 | Nemotron Lightning | 0+0 | 1.31 | 2.95 | PASS |
| 17 | what about Nov 17 instead? *(follow-up)* | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+0 | 1.15 | 2.79 | PASS |
| 18 | Help me get through the semester | runway, money_ideas, find_leaks / yes | runs_out / yes | yes | all 9 | Nemotron Lightning | 0+0 | 0.71 | 4.46 | PASS |
| 19 | What is FAFSA verification? | general_info / yes | - / yes | yes | all 0 | Nemotron Lightning | 0+0 | - | 1.51 | PASS |
| 20 | money stuff is stressing me out | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.46 | 1.92 | PASS |
| 21 | What should I do this week? | action_plan / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.79 | 2.86 | PASS |
| 22 | Where did my money go in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 0.81 | 2.85 | PASS |
| 23 | How much is left in my food budget? | budget_status / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.58 | 2.44 | PASS |
| 24 | What happens if I stick to my budget? | budget_status / NO | - / yes | yes | all 2 | a template | 0+1 | 0.81 | 4.99 | FAIL |
| 25 | Are there any grants or scholarships I qualify for? | find_aid / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 0.56 | 2.21 | PASS |
| 26 | Will my dining dollars last? | meal_plan / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.48 | 2.03 | PASS |
| 27 | If I apply for the emergency grant, when would the money come? | find_aid / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.78 | 3.03 | PASS |
| 28 | How many meal swipes will I have left at the end of the semester? | meal_plan / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.56 | 3.9 | PASS |
| 29 | What if I work 4 hours this Saturday and next Saturday? | what_if / NO | runs_out / NO | yes | all 3 | a template | 0+1 | 3.38 | 12.14 | FAIL |

## Run 2 (Fast): 24/29 full answers

| # | Question | Tools / right? | Verdict / right? | Checks passed | Required facts by model | Written by | Retries (plan+rewrite) | Quick answer s | Full answer s | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+1 | 1.34 | 11.28 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.66 | 2.33 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 2.11 | 4.28 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | all 3 | a template | 0+1 | 2.47 | 9.01 | FAIL |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | all 3 | a template | 0+1 | 0.83 | 14.67 | FAIL |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | all 3 | Nemotron Lightning | 0+0 | 7.32 | 9.09 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | all 0 | - | 0+0 | - | 0.48 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.49 | 11.39 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.62 | 3.07 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.92 | 2.32 | PASS |
| 11 | How much did I spend on each category in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 1.13 | 2.7 | PASS |
| 12 | How much did I spend at Kroger? | find_transactions / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.64 | 2.24 | PASS |
| 13 | What bills are due next week? | upcoming_bills / yes | - / yes | yes | all 1 | Nemotron Lightning | 0+0 | 0.9 | 2.66 | PASS |
| 14 | How many hours did I work in October? | work_summary / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.8 | 2.23 | PASS |
| 15 | What will my balance be on Thanksgiving? | balance_on / yes | - / yes | yes | all 1 | a template | 0+1 | 0.94 | 9.06 | FAIL |
| 16 | What can I do to make money before this? *(follow-up)* | money_ideas / yes | runs_out / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.76 | 2.47 | PASS |
| 17 | what about Nov 17 instead? *(follow-up)* | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+0 | 1.2 | 3.66 | PASS |
| 18 | Help me get through the semester | runway, money_ideas, find_leaks / yes | runs_out / yes | yes | all 9 | Nemotron Lightning | 0+0 | 2.05 | 13.03 | PASS |
| 19 | What is FAFSA verification? | general_info / yes | - / yes | yes | all 0 | Nemotron Lightning | 0+0 | - | 2.15 | PASS |
| 20 | money stuff is stressing me out | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.62 | 2.36 | PASS |
| 21 | What should I do this week? | action_plan / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 4.54 | 9.92 | PASS |
| 22 | Where did my money go in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 0.98 | 2.45 | PASS |
| 23 | How much is left in my food budget? | budget_status / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.8 | 2.08 | PASS |
| 24 | What happens if I stick to my budget? | budget_status / NO | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.67 | 2.84 | FAIL |
| 25 | Are there any grants or scholarships I qualify for? | find_aid / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 6.67 | 12.84 | PASS |
| 26 | Will my dining dollars last? | meal_plan / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 1.21 | 6.52 | PASS |
| 27 | If I apply for the emergency grant, when would the money come? | find_aid / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 1.4 | 4.02 | PASS |
| 28 | How many meal swipes will I have left at the end of the semester? | meal_plan / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.64 | 2.46 | PASS |
| 29 | What if I work 4 hours this Saturday and next Saturday? | what_if / NO | runs_out / NO | yes | all 3 | Nemotron Lightning | 0+0 | 2.6 | 4.04 | FAIL |

## Run 3 (Think harder): 28/29 full answers

| # | Question | Tools / right? | Verdict / right? | Checks passed | Required facts by model | Written by | Retries (plan+rewrite) | Quick answer s | Full answer s | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Super | 0+0 | 1.58 | 77.54 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 83.15 | 215.76 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | all 4 | Nemotron Super | 0+0 | 0.71 | 34.34 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | all 3 | Nemotron Super | 0+0 | 7.43 | 98.58 | PASS |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | all 3 | Nemotron Super | 0+0 | 2.28 | 39.76 | PASS |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | all 3 | Nemotron Super | 0+0 | 1.76 | 43.29 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | all 0 | - | 0+0 | - | 0.59 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 0.58 | 36.29 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | all 3 | Nemotron Super | 0+0 | 2.79 | 18.89 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | all 2 | Nemotron Super | 0+0 | 0.7 | 16.57 | PASS |
| 11 | How much did I spend on each category in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Super | 0+0 | 1.11 | 113.68 | PASS |
| 12 | How much did I spend at Kroger? | find_transactions / yes | - / yes | yes | all 2 | Nemotron Super | 0+0 | 34.21 | 59.07 | PASS |
| 13 | What bills are due next week? | upcoming_bills / yes | - / yes | yes | all 1 | Nemotron Super | 0+0 | 2.04 | 35.27 | PASS |
| 14 | How many hours did I work in October? | work_summary / yes | - / yes | yes | all 3 | Nemotron Super | 0+0 | 0.85 | 34.17 | PASS |
| 15 | What will my balance be on Thanksgiving? | balance_on / yes | - / yes | yes | all 1 | Nemotron Super | 0+0 | 0.78 | 61.4 | PASS |
| 16 | What can I do to make money before this? *(follow-up)* | money_ideas / yes | runs_out / yes | yes | all 3 | Nemotron Super | 0+0 | 0.71 | 37.9 | PASS |
| 17 | what about Nov 17 instead? *(follow-up)* | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+0 | 1.01 | 378.37 | PASS |
| 18 | Help me get through the semester | runway, money_ideas, find_leaks / yes | runs_out / yes | yes | all 9 | Nemotron Super | 0+0 | 4.65 | 65.83 | PASS |
| 19 | What is FAFSA verification? | general_info / yes | - / yes | yes | all 0 | Nemotron Lightning | 0+0 | - | 72.14 | PASS |
| 20 | money stuff is stressing me out | runway / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 0.64 | 51.39 | PASS |
| 21 | What should I do this week? | action_plan / yes | - / yes | yes | all 2 | Nemotron Super | 0+0 | 1.11 | 63.06 | PASS |
| 22 | Where did my money go in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Super | 0+0 | 0.78 | 23.18 | PASS |
| 23 | How much is left in my food budget? | budget_status / yes | - / yes | yes | all 2 | Nemotron Super | 0+0 | 0.68 | 78.65 | PASS |
| 24 | What happens if I stick to my budget? | budget_status / NO | - / yes | yes | all 2 | Nemotron Super | 0+0 | 0.84 | 148.82 | FAIL |
| 25 | Are there any grants or scholarships I qualify for? | find_aid / yes | - / yes | yes | all 4 | Nemotron Super | 0+1 | 1.01 | 108.53 | PASS |
| 26 | Will my dining dollars last? | meal_plan / yes | - / yes | yes | all 3 | Nemotron Super | 0+0 | 0.88 | 26.21 | PASS |
| 27 | If I apply for the emergency grant, when would the money come? | find_aid / yes | - / yes | yes | all 3 | Nemotron Super | 0+0 | 1.1 | 49.5 | PASS |
| 28 | How many meal swipes will I have left at the end of the semester? | meal_plan / yes | - / yes | yes | all 3 | Nemotron Super | 0+0 | 0.96 | 65.2 | PASS |
| 29 | What if I work 4 hours this Saturday and next Saturday? | what_if / yes | runs_out / yes | yes | all 4 | Nemotron Super | 0+0 | 1.95 | 49.07 | PASS |
