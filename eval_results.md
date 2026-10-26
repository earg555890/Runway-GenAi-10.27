# Ask Runway live evaluation (latest run, fast)

Score: **22/28**

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
