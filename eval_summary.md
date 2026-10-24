# Ask Runway: how well it answers

We asked Runway 10 realistic student questions, 3 separate times (30 answers in all), using the real NVIDIA Nemotron models. Every answer was graded automatically against numbers that Runway's money engine computes on its own.

- **Picked the right tool:** 30/30
- **Gave the right verdict** (yes / no / yes-if; money runs out or not): 30/30
- **Every dollar amount and date matched the student's records:** 30/30
- **Full answers** (all of the above, plus the key numbers, written by a Nemotron model): 29/30

1 answer was not a full answer: 1 because of NVIDIA service errors (no model responded in time, so Runway showed a short summary built from the numbers instead) and 0 because of real mistakes.

Who wrote the answers: Nemotron Super 26, a template 1 (the off-topic question gets a fixed reply and needs no writer).
Typical time to write an answer: 19.63 s (median). Planning takes about a second.

The model never does the math: Runway's engine computes every number, and a checker rejects any amount or date the model didn't take from the student's records.

## Run 1: 9/10 full answers

| # | Question | Tool / right? | Verdict / right? | Check passed | Key numbers | Written by | Retries (plan+rewrite) | PLAN s | EXPLAIN s | Total s | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | yes | Nemotron Super | 0+0 | 1.44 | 11.66 | 13.11 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | yes | Nemotron Super | 0+0 | 0.69 | 32.58 | 33.28 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | yes | Nemotron Super | 0+0 | 0.49 | 14.68 | 15.17 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | yes | a template | 0+1 | 0.66 | 155.02 | 155.69 | FAIL |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | yes | Nemotron Super | 0+0 | 0.62 | 11.34 | 11.98 | PASS |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | yes | Nemotron Super | 0+0 | 0.98 | 10.01 | 11.0 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | yes | - | 0+0 | 0.44 | - | 0.44 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | yes | Nemotron Super | 0+0 | 0.34 | 20.72 | 21.06 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | yes | Nemotron Super | 0+0 | 0.34 | 11.99 | 12.33 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | yes | Nemotron Super | 0+0 | 0.49 | 12.91 | 13.4 | PASS |

## Run 2: 10/10 full answers

| # | Question | Tool / right? | Verdict / right? | Check passed | Key numbers | Written by | Retries (plan+rewrite) | PLAN s | EXPLAIN s | Total s | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | yes | Nemotron Super | 0+0 | 0.86 | 32.66 | 33.54 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | yes | Nemotron Super | 0+0 | 0.42 | 19.63 | 20.05 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | yes | Nemotron Super | 0+0 | 0.72 | 26.58 | 27.31 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | yes | Nemotron Super | 0+0 | 1.77 | 31.54 | 33.31 | PASS |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | yes | Nemotron Super | 0+0 | 0.81 | 43.54 | 44.36 | PASS |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | yes | Nemotron Super | 0+0 | 0.76 | 28.18 | 28.96 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | yes | - | 0+0 | 0.77 | - | 0.77 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | yes | Nemotron Super | 0+0 | 0.51 | 35.98 | 36.49 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | yes | Nemotron Super | 0+0 | 0.67 | 10.1 | 10.78 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | yes | Nemotron Super | 0+0 | 0.45 | 15.74 | 16.19 | PASS |

## Run 3: 10/10 full answers

| # | Question | Tool / right? | Verdict / right? | Check passed | Key numbers | Written by | Retries (plan+rewrite) | PLAN s | EXPLAIN s | Total s | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | yes | Nemotron Super | 0+0 | 0.91 | 28.49 | 29.41 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | yes | Nemotron Super | 0+0 | 0.45 | 15.38 | 15.84 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | yes | Nemotron Super | 0+0 | 0.48 | 12.2 | 12.69 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | yes | Nemotron Super | 0+0 | 0.79 | 64.11 | 64.91 | PASS |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | yes | Nemotron Super | 0+0 | 0.58 | 36.09 | 36.7 | PASS |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | yes | Nemotron Super | 0+0 | 0.71 | 14.39 | 15.12 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | yes | - | 0+0 | 0.54 | - | 0.54 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | yes | Nemotron Super | 0+0 | 0.32 | 14.26 | 14.58 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | yes | Nemotron Super | 0+0 | 0.44 | 18.9 | 19.34 | PASS |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | yes | Nemotron Super | 0+0 | 0.58 | 26.15 | 26.73 | PASS |
