# Ask Runway: how well it answers

We asked Runway 10 realistic student questions, 3 separate times (30 answers in all), using the real NVIDIA Nemotron models. Every answer was graded automatically against numbers that Runway's money engine computes on its own.

- **Picked the right tool:** 30/30
- **Gave the right verdict** (yes / no / yes-if; money runs out or not): 30/30
- **Every dollar amount and date matched the student's records:** 30/30
- **Full answers** (all of the above, and the model itself wrote every required fact): 30/30
- Answers that needed one rewrite after the check: 0/30
- Answers where the model still left out a required fact, so Runway added a plain line built from the numbers: 0/30

Every answer was a full answer.

Who wrote the answers: Nemotron Super 27 (the off-topic question gets a fixed reply and needs no writer).
Typical time to write an answer: 25.11 s (median). Planning takes about a second.

The model never does the math: Runway's engine computes every number, and a checker rejects any amount or date the model didn't take from the student's records.

## Run 1: 10/10 full answers

| # | Question | Tool / right? | Verdict / right? | Check passed | Required facts by model | Written by | Retries (plan+rewrite) | PLAN s | EXPLAIN s | Total s | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Super | 0+0 | 0.77 | 35.78 | 36.57 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 0.5 | 15.48 | 15.99 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | all 4 | Nemotron Super | 0+0 | 0.59 | 16.81 | 17.41 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 1.18 | 14.09 | 15.27 | PASS |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | all 3 | Nemotron Super | 0+0 | 0.74 | 22.37 | 23.13 | PASS |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | all 3 | Nemotron Super | 0+0 | 3.5 | 18.03 | 21.54 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | all 0 | - | 0+0 | 0.48 | - | 0.48 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 0.35 | 25.11 | 25.46 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | all 3 | Nemotron Super | 0+0 | 0.54 | 26.07 | 26.62 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | all 2 | Nemotron Super | 0+0 | 0.74 | 19.57 | 20.31 | PASS |

## Run 2: 10/10 full answers

| # | Question | Tool / right? | Verdict / right? | Check passed | Required facts by model | Written by | Retries (plan+rewrite) | PLAN s | EXPLAIN s | Total s | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Super | 0+0 | 0.8 | 42.52 | 43.34 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 0.55 | 30.49 | 31.05 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | all 4 | Nemotron Super | 0+0 | 0.52 | 21.28 | 21.81 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 0.73 | 23.24 | 23.98 | PASS |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | all 3 | Nemotron Super | 0+0 | 0.68 | 30.27 | 30.97 | PASS |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | all 3 | Nemotron Super | 0+0 | 0.97 | 18.73 | 19.72 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | all 0 | - | 0+0 | 0.56 | - | 0.56 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 0.31 | 43.0 | 43.32 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | all 3 | Nemotron Super | 0+0 | 0.38 | 17.18 | 17.57 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | all 2 | Nemotron Super | 0+0 | 0.42 | 13.17 | 13.6 | PASS |

## Run 3: 10/10 full answers

| # | Question | Tool / right? | Verdict / right? | Check passed | Required facts by model | Written by | Retries (plan+rewrite) | PLAN s | EXPLAIN s | Total s | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | all 4 | Nemotron Super | 0+0 | 0.66 | 26.38 | 27.06 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 0.41 | 15.89 | 16.31 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | all 4 | Nemotron Super | 0+0 | 0.57 | 39.49 | 40.07 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 0.64 | 20.37 | 21.03 | PASS |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | all 3 | Nemotron Super | 0+0 | 0.5 | 60.28 | 60.79 | PASS |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | all 3 | Nemotron Super | 0+0 | 1.23 | 25.56 | 26.8 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | all 0 | - | 0+0 | 0.74 | - | 0.74 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | all 2 | Nemotron Super | 0+0 | 5.44 | 28.46 | 33.9 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | all 3 | Nemotron Super | 0+0 | 0.6 | 34.59 | 35.19 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | all 2 | Nemotron Super | 0+0 | 0.63 | 25.66 | 26.3 | PASS |
