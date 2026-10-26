# Ask Runway live evaluation (latest run, think)

Score: **28/29**

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
