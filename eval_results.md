# Ask Runway live evaluation (latest run, fast)

Score: **17/20**

| # | Question | Tools / right? | Verdict / right? | Checks passed | Required facts by model | Written by | Retries (plan+rewrite) | Quick answer s | Full answer s | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+0 | 0.94 | 2.53 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Lightning | 0+0 | 0.47 | 2.15 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+1 | 0.66 | 19.34 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.69 | 1.97 | PASS |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | all 3 | Nemotron Lightning | 0+1 | 0.75 | 3.78 | PASS |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.86 | 2.06 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | all 0 | - | 0+0 | - | 0.5 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | all 2 | a template | 0+1 | 0.42 | 3.69 | FAIL |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.5 | 4.99 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | all 2 | a template | 0+1 | 0.51 | 3.46 | FAIL |
| 11 | How much did I spend on each category in October? | spending_summary / yes | - / yes | yes | all 4 | Nemotron Lightning | 0+0 | 1.17 | 2.22 | PASS |
| 12 | How much did I spend at Kroger? | find_transactions / yes | - / yes | yes | all 2 | Nemotron Lightning | 0+0 | 3.5 | 4.77 | PASS |
| 13 | What bills are due next week? | upcoming_bills / yes | - / yes | yes | all 1 | Nemotron Lightning | 0+0 | 0.92 | 1.96 | PASS |
| 14 | How many hours did I work in October? | work_summary / yes | - / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.8 | 1.79 | PASS |
| 15 | What will my balance be on Thanksgiving? | balance_on / yes | - / yes | yes | all 1 | Nemotron Lightning | 0+0 | 0.75 | 2.77 | PASS |
| 16 | What can I do to make money before this? *(follow-up)* | money_ideas / yes | runs_out / yes | yes | all 3 | Nemotron Lightning | 0+0 | 0.63 | 2.04 | PASS |
| 17 | what about Nov 17 instead? *(follow-up)* | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Lightning | 0+0 | 0.94 | 2.22 | PASS |
| 18 | Help me get through the semester | runway, money_ideas, find_leaks / yes | runs_out / yes | yes | all 9 | Nemotron Lightning | 0+0 | 0.77 | 3.0 | PASS |
| 19 | What is FAFSA verification? | general_info / yes | - / yes | yes | all 0 | Nemotron Lightning | 0+0 | - | 1.23 | PASS |
| 20 | money stuff is stressing me out | runway / yes | runs_out / yes | yes | all 2 | a template | 0+1 | 0.38 | 4.81 | FAIL |
