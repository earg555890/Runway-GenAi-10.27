# Ask Runway: how well it answers

We asked Runway 20 realistic student questions (the original 10, plus 10 new ones: spending, transactions, bills, work hours, a balance on a date, two follow-ups, a multi-step plan, a general question and a vague one), 3 separate times (60 answers in all), using the real NVIDIA Nemotron models. Every answer was graded automatically against numbers that Runway's money engine computes on its own. Follow-ups were asked after the question they follow, in the same chat.

The model never does the math: Runway's engine computes every number, shows a quick answer from those numbers right away, and a checker rejects any AI answer with an amount, date or reason that doesn't match the student's records.

## Fast (Nemotron Lightning, thinking off; the default): 38/40 full answers (2 runs)

- **Picked the right tool(s):** 39/40
- **Gave the right verdict:** 39/40
- **Passed every check** (numbers, dates, reasons, no repeats, not cut off): 39/40
- **Full answers** (all of the above, written by the model with every required fact): 38/40
- Answers that needed one rewrite: 6/40
- Answers where the quick answer stood in for the AI answer: 2/40
- **Quick answer:** 0.77 s median after sending. **Full AI answer:** 2.44 s median.

Not full answers: 0 because of NVIDIA service errors, 2 because of real mistakes:
  - Run 2, "What bills are due next week?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer repeats itself ("Rent of $725 is due on Sun Nov 1.")), so this is the quick answer built straight from you)
  - Run 2, "Help me get through the semester": picked no tool

## Think harder (Nemotron Super, thinking on): 20/20 full answers (1 run)

- **Picked the right tool(s):** 20/20
- **Gave the right verdict:** 20/20
- **Passed every check** (numbers, dates, reasons, no repeats, not cut off): 20/20
- **Full answers** (all of the above, written by the model with every required fact): 20/20
- Answers that needed one rewrite: 1/20
- Answers where the quick answer stood in for the AI answer: 0/20
- **Quick answer:** 0.76 s median after sending. **Full AI answer:** 51.8 s median.

## Run 1 (Fast): 20/20 full answers

| # | Question | Tools / right? | Verdict / right? | Checks passed | Required facts by model | Written by | Retries (plan+rewrite) | Quick answer s | Full answer s | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+1 | 0.84 | 6.18 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.6 | 1.98 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 0.41 | 1.36 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | all 3 | Nemotron Lightning | 0+0 | 1.72 | 3.05 | PASS |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.65 | 3.99 | PASS |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.91 | 2.37 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | all 0 | - | 0+0 | - | 0.53 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.42 | 2.16 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.48 | 1.56 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.9 | 2.36 | PASS |
| 11 | How much did I spend on each category in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+1 | 0.77 | 2.96 | PASS |
| 12 | How much did I spend at Kroger? | find_transactions / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.67 | 1.6 | PASS |
| 13 | What bills are due next week? | upcoming_bills / yes | - / yes | yes | all 1 | Nemotron Lightning | 0+0 | 0.86 | 1.85 | PASS |
| 14 | How many hours did I work in October? | work_summary / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 1.67 | 2.44 | PASS |
| 15 | What will my balance be on Thanksgiving? | balance_on / yes | - / yes | yes | all 1 | Nemotron Lightning | 0+0 | 1.42 | 3.03 | PASS |
| 16 | What can I do to make money before this? *(follow-up)* | money_ideas / yes | runs_out / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.73 | 1.87 | PASS |
| 17 | what about Nov 17 instead? *(follow-up)* | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+0 | 0.71 | 5.14 | PASS |
| 18 | Help me get through the semester | runway, money_ideas, find_leaks / yes | runs_out / yes | yes | all 9 | Nemotron Lightning | 0+0 | 0.48 | 2.96 | PASS |
| 19 | What is FAFSA verification? | general_info / yes | - / yes | yes | all 0 | Nemotron Lightning | 0+0 | - | 1.36 | PASS |
| 20 | money stuff is stressing me out | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.73 | 2.7 | PASS |

## Run 2 (Fast): 18/20 full answers

| # | Question | Tools / right? | Verdict / right? | Checks passed | Required facts by model | Written by | Retries (plan+rewrite) | Quick answer s | Full answer s | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+1 | 1.18 | 3.83 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.62 | 2.48 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+1 | 0.7 | 3.38 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.9 | 2.22 | PASS |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | all 3 | Nemotron Lightning | 0+0 | 4.82 | 6.66 | PASS |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | all 3 | Nemotron Lightning | 0+0 | 1.06 | 6.27 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | all 0 | - | 0+0 | - | 0.54 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.62 | 1.8 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.67 | 3.43 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.89 | 2.25 | PASS |
| 11 | How much did I spend on each category in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+1 | 1.42 | 3.74 | PASS |
| 12 | How much did I spend at Kroger? | find_transactions / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.65 | 1.93 | PASS |
| 13 | What bills are due next week? | upcoming_bills / yes | - / yes | yes | all 1 | a template | 0+1 | 1.27 | 4.36 | FAIL |
| 14 | How many hours did I work in October? | work_summary / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 1.11 | 2.85 | PASS |
| 15 | What will my balance be on Thanksgiving? | balance_on / yes | - / yes | yes | all 1 | Nemotron Lightning | 0+0 | 0.9 | 2.13 | PASS |
| 16 | What can I do to make money before this? *(follow-up)* | money_ideas / yes | runs_out / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.59 | 1.63 | PASS |
| 17 | what about Nov 17 instead? *(follow-up)* | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+0 | 0.93 | 5.04 | PASS |
| 18 | Help me get through the semester | runway, money_ideas, find_leaks / NO | runs_out / NO | NO | all 0 | a template | 0+0 | - | 0.41 | FAIL |
| 19 | What is FAFSA verification? | general_info / yes | - / yes | yes | all 0 | Nemotron Lightning | 0+0 | - | 1.25 | PASS |
| 20 | money stuff is stressing me out | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.66 | 1.99 | PASS |

## Run 3 (Think harder): 20/20 full answers

| # | Question | Tools / right? | Verdict / right? | Checks passed | Required facts by model | Written by | Retries (plan+rewrite) | Quick answer s | Full answer s | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Super | 0+0 | 1.24 | 27.06 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 0.47 | 57.88 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+1 | 1.68 | 236.17 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | all 3 | Nemotron Super | 0+0 | 0.76 | 56.82 | PASS |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | all 3 | Nemotron Super | 0+0 | 0.84 | 93.28 | PASS |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | all 3 | Nemotron Super | 0+0 | 0.82 | 30.6 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | all 0 | - | 0+0 | - | 0.5 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.52 | 170.41 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | all 3 | Nemotron Super | 0+0 | 0.71 | 38.32 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | all 2 | Nemotron Super | 0+0 | 0.54 | 38.06 | PASS |
| 11 | How much did I spend on each category in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Super | 0+0 | 0.82 | 57.28 | PASS |
| 12 | How much did I spend at Kroger? | find_transactions / yes | - / yes | yes | all 2 | Nemotron Super | 0+0 | 0.66 | 25.81 | PASS |
| 13 | What bills are due next week? | upcoming_bills / yes | - / yes | yes | all 1 | Nemotron Super | 0+0 | 0.87 | 62.3 | PASS |
| 14 | How many hours did I work in October? | work_summary / yes | - / yes | yes | all 3 | Nemotron Super | 0+0 | 0.82 | 51.8 | PASS |
| 15 | What will my balance be on Thanksgiving? | balance_on / yes | - / yes | yes | all 1 | Nemotron Super | 0+0 | 0.73 | 31.67 | PASS |
| 16 | What can I do to make money before this? *(follow-up)* | money_ideas / yes | runs_out / yes | yes | all 3 | Nemotron Super | 0+0 | 0.6 | 73.34 | PASS |
| 17 | what about Nov 17 instead? *(follow-up)* | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Super | 0+0 | 0.89 | 43.79 | PASS |
| 18 | Help me get through the semester | runway, money_ideas, find_leaks / yes | runs_out / yes | yes | all 9 | Nemotron Super | 0+0 | 0.6 | 67.08 | PASS |
| 19 | What is FAFSA verification? | general_info / yes | - / yes | yes | all 0 | Nemotron Super | 0+0 | - | 12.02 | PASS |
| 20 | money stuff is stressing me out | runway / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 0.63 | 27.54 | PASS |
