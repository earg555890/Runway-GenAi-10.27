# Ask Runway: how well it answers

We asked Runway 20 realistic student questions (the original 10, plus 10 new ones: spending, transactions, bills, work hours, a balance on a date, two follow-ups, a multi-step plan, a general question and a vague one), 3 separate times (60 answers in all), using the real NVIDIA Nemotron models. Every answer was graded automatically against numbers that Runway's money engine computes on its own. Follow-ups were asked after the question they follow, in the same chat.

The model never does the math: Runway's engine computes every number, shows a quick answer from those numbers right away, and a checker rejects any AI answer with an amount, date or reason that doesn't match the student's records.

## Fast (Nemotron Lightning, thinking off; the default): 30/40 full answers (2 runs)

- **Picked the right tool(s):** 40/40
- **Gave the right verdict:** 40/40
- **Passed every check** (numbers, dates, reasons, no repeats, not cut off): 40/40
- **Full answers** (all of the above, written by the model with every required fact): 30/40
- Answers that needed one rewrite: 20/40
- Answers where the quick answer stood in for the AI answer: 10/40
- **Quick answer:** 0.86 s median after sending. **Full AI answer:** 3.49 s median.

Not full answers: 0 because of NVIDIA service errors, 10 because of real mistakes:
  - Run 1, "How long will my money last?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer repeats itself ("A $360 credit card payment is due Mon, Nov 9, when you'll ha")), so this is the quick ans)
  - Run 1, "Where is my money leaking?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (Apple Music does not charge checking (it is billed to the credit card)), so this is the quick answer built straight f)
  - Run 1, "What if I pick up a 5 hour shift on Nov 7?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer repeats itself ("The extra shift adds $71.69 to your Wed, Nov 18 paycheck.")), so this is the quick answer)
  - Run 1, "Can I put a $120 concert ticket on my credit card on Nov 20?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (Nov 20 is not a refund date), so this is the quick answer built straight from your numbers.)
  - Run 1, "am I ok?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer repeats itself ("A $360 credit card payment is due Mon, Nov 9, when you'll ha")), so this is the quick ans)
  - Run 1, "money stuff is stressing me out": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer repeats itself ("A $360 credit card payment is due Mon, Nov 9, when you'll ha")), so this is the quick ans)
  - Run 2, "am I ok?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer repeats itself ("A $360 credit card payment is due Mon, Nov 9, when you'll ha")), so this is the quick ans)
  - Run 2, "Is there a week coming up where money gets really tight?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (Nov 20 is not a paycheck date), so this is the quick answer built straight from your numbers.)
  - Run 2, "What bills are due next week?": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer stops mid-sentence), so this is the quick answer built straight from your numbers.)
  - Run 2, "money stuff is stressing me out": the AI answer didn't pass the checks, so the quick answer stood in (The AI answer didn't pass Runway's checks (the answer repeats itself ("A $360 credit card payment is due Mon, Nov 9, when you'll ha")), so this is the quick ans)

## Think harder (Nemotron Super, thinking on): 20/20 full answers (1 run)

- **Picked the right tool(s):** 20/20
- **Gave the right verdict:** 20/20
- **Passed every check** (numbers, dates, reasons, no repeats, not cut off): 20/20
- **Full answers** (all of the above, written by the model with every required fact): 20/20
- Answers that needed one rewrite: 2/20
- Answers where the quick answer stood in for the AI answer: 0/20
- **Quick answer:** 0.86 s median after sending. **Full AI answer:** 32.78 s median.

## Run 1 (Fast): 14/20 full answers

| # | Question | Tools / right? | Verdict / right? | Checks passed | Required facts by model | Written by | Retries (plan+rewrite) | Quick answer s | Full answer s | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+1 | 1.1 | 3.81 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | all 2 | a template | 0+1 | 0.84 | 17.74 | FAIL |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | all 4 | a template | 0+1 | 0.86 | 3.74 | FAIL |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | all 3 | a template | 0+1 | 0.85 | 3.79 | FAIL |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | all 3 | Nemotron Lightning | 0+1 | 0.84 | 4.27 | PASS |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | all 3 | a template | 0+1 | 1.6 | 4.25 | FAIL |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | all 0 | - | 0+0 | - | 0.39 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | all 2 | a template | 0+1 | 0.69 | 5.34 | FAIL |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.83 | 4.31 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 1.0 | 2.46 | PASS |
| 11 | How much did I spend on each category in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+1 | 0.97 | 3.49 | PASS |
| 12 | How much did I spend at Kroger? | find_transactions / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 1.0 | 2.02 | PASS |
| 13 | What bills are due next week? | upcoming_bills / yes | - / yes | yes | all 1 | Nemotron Lightning | 0+0 | 1.09 | 2.28 | PASS |
| 14 | How many hours did I work in October? | work_summary / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+1 | 0.97 | 3.25 | PASS |
| 15 | What will my balance be on Thanksgiving? | balance_on / yes | - / yes | yes | all 1 | Nemotron Lightning | 0+1 | 0.89 | 4.67 | PASS |
| 16 | What can I do to make money before this? *(follow-up)* | money_ideas / yes | runs_out / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.52 | 1.5 | PASS |
| 17 | what about Nov 17 instead? *(follow-up)* | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+1 | 1.12 | 5.05 | PASS |
| 18 | Help me get through the semester | runway, money_ideas, find_leaks / yes | runs_out / yes | yes | all 9 | Nemotron Lightning | 0+0 | 0.7 | 2.82 | PASS |
| 19 | What is FAFSA verification? | general_info / yes | - / yes | yes | all 0 | Nemotron Lightning | 0+0 | - | 1.28 | PASS |
| 20 | money stuff is stressing me out | runway / yes | runs_out / yes | yes | all 2 | a template | 0+1 | 0.56 | 4.42 | FAIL |

## Run 2 (Fast): 16/20 full answers

| # | Question | Tools / right? | Verdict / right? | Checks passed | Required facts by model | Written by | Retries (plan+rewrite) | Quick answer s | Full answer s | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+1 | 1.25 | 3.77 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.53 | 2.41 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 0.57 | 1.84 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.98 | 2.14 | PASS |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.75 | 2.23 | PASS |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | all 3 | Nemotron Lightning | 0+0 | 1.17 | 4.02 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | all 0 | - | 0+0 | - | 0.46 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | all 2 | a template | 0+1 | 0.44 | 3.21 | FAIL |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+1 | 0.61 | 3.66 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | all 2 | a template | 0+1 | 0.49 | 2.75 | FAIL |
| 11 | How much did I spend on each category in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+1 | 0.96 | 3.78 | PASS |
| 12 | How much did I spend at Kroger? | find_transactions / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.63 | 1.69 | PASS |
| 13 | What bills are due next week? | upcoming_bills / yes | - / yes | yes | all 1 | a template | 0+1 | 1.73 | 3.96 | FAIL |
| 14 | How many hours did I work in October? | work_summary / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.93 | 2.14 | PASS |
| 15 | What will my balance be on Thanksgiving? | balance_on / yes | - / yes | yes | all 1 | Nemotron Lightning | 0+0 | 1.03 | 2.05 | PASS |
| 16 | What can I do to make money before this? *(follow-up)* | money_ideas / yes | runs_out / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.63 | 1.96 | PASS |
| 17 | what about Nov 17 instead? *(follow-up)* | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+1 | 1.02 | 4.61 | PASS |
| 18 | Help me get through the semester | runway, money_ideas, find_leaks / yes | runs_out / yes | yes | all 9 | Nemotron Lightning | 0+0 | 0.5 | 2.57 | PASS |
| 19 | What is FAFSA verification? | general_info / yes | - / yes | yes | all 0 | Nemotron Lightning | 0+0 | - | 1.64 | PASS |
| 20 | money stuff is stressing me out | runway / yes | runs_out / yes | yes | all 2 | a template | 0+1 | 0.57 | 4.09 | FAIL |

## Run 3 (Think harder): 20/20 full answers

| # | Question | Tools / right? | Verdict / right? | Checks passed | Required facts by model | Written by | Retries (plan+rewrite) | Quick answer s | Full answer s | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Super | 0+0 | 1.01 | 24.28 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 2.68 | 32.78 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | all 4 | Nemotron Super | 0+0 | 0.63 | 20.53 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | all 3 | Nemotron Super | 0+0 | 0.78 | 29.32 | PASS |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | all 3 | Nemotron Super | 0+0 | 0.72 | 37.2 | PASS |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | all 3 | Nemotron Super | 0+1 | 1.1 | 76.29 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | all 0 | - | 0+0 | - | 0.53 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 0.54 | 39.82 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | all 3 | Nemotron Super | 0+0 | 3.75 | 83.29 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | all 2 | Nemotron Super | 0+0 | 0.64 | 26.2 | PASS |
| 11 | How much did I spend on each category in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Super | 0+0 | 1.05 | 77.81 | PASS |
| 12 | How much did I spend at Kroger? | find_transactions / yes | - / yes | yes | all 2 | Nemotron Super | 0+0 | 0.86 | 24.49 | PASS |
| 13 | What bills are due next week? | upcoming_bills / yes | - / yes | yes | all 1 | Nemotron Super | 0+0 | 0.93 | 32.59 | PASS |
| 14 | How many hours did I work in October? | work_summary / yes | - / yes | yes | all 3 | Nemotron Super | 0+0 | 0.89 | 52.17 | PASS |
| 15 | What will my balance be on Thanksgiving? | balance_on / yes | - / yes | yes | all 1 | Nemotron Super | 0+0 | 0.62 | 19.01 | PASS |
| 16 | What can I do to make money before this? *(follow-up)* | money_ideas / yes | runs_out / yes | yes | all 3 | Nemotron Super | 0+0 | 0.59 | 43.57 | PASS |
| 17 | what about Nov 17 instead? *(follow-up)* | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Super | 0+0 | 1.95 | 29.33 | PASS |
| 18 | Help me get through the semester | runway, money_ideas, find_leaks / yes | runs_out / yes | yes | all 9 | Nemotron Super | 0+1 | 0.65 | 159.71 | PASS |
| 19 | What is FAFSA verification? | general_info / yes | - / yes | yes | all 0 | Nemotron Super | 0+0 | - | 14.02 | PASS |
| 20 | money stuff is stressing me out | runway / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 0.6 | 51.48 | PASS |
