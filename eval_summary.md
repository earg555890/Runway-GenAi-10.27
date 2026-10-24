# Ask Runway: how well it answers

We asked Runway 10 realistic student questions, 3 separate times (30 answers in all), using the real NVIDIA Nemotron models. Every answer was graded automatically against numbers that Runway's money engine computes on its own.

- **Picked the right tool:** 30/30
- **Gave the right verdict** (yes / no / yes-if; money runs out or not): 30/30
- **Every dollar amount and date matched the student's records:** 30/30
- **Full answers** (all of the above, plus the key numbers, written by a Nemotron model): 20/30

10 answers were not a full answer: 0 because of NVIDIA service errors (no model responded in time, so Runway showed a short summary built from the numbers instead) and 10 because of real mistakes:
  - Run 1, "What if I pick up a 5 hour shift on Nov 7?": left out a key number
  - Run 1, "Can I afford new headphones for $150?": left out a key number
  - Run 1, "Why is my refund on hold?": left out a key number
  - Run 2, "Can I afford a $400 flight home for Thanksgiving if I book it Nov 10?": left out a key number
  - Run 2, "What if I pick up a 5 hour shift on Nov 7?": left out a key number
  - Run 2, "Why is my refund on hold?": left out a key number
  - Run 3, "Can I afford a $400 flight home for Thanksgiving if I book it Nov 10?": left out a key number
  - Run 3, "What if I pick up a 5 hour shift on Nov 7?": left out a key number
  - Run 3, "Why is my refund on hold?": left out a key number
  - Run 3, "Is there a week coming up where money gets really tight?": left out a key number

Who wrote the answers: Nemotron Lightning 1, Nemotron Super 26 (the off-topic question gets a fixed reply and needs no writer).
Typical time to write an answer: 18.57 s (median). Planning takes about a second.

The model never does the math: Runway's engine computes every number, and a checker rejects any amount or date the model didn't take from the student's records.

## Run 1: 7/10 full answers

| # | Question | Tool / right? | Verdict / right? | Check passed | Key numbers | Written by | Retries (plan+rewrite) | PLAN s | EXPLAIN s | Total s | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | yes | Nemotron Super | 0+0 | 0.63 | 14.51 | 15.15 | PASS |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | yes | Nemotron Super | 0+0 | 0.59 | 30.15 | 30.75 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | yes | Nemotron Super | 0+0 | 0.46 | 18.54 | 19.0 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | NO | Nemotron Super | 0+0 | 0.89 | 14.16 | 15.05 | FAIL |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | NO | Nemotron Lightning | 0+1 | 0.87 | 334.47 | 335.35 | FAIL |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | yes | Nemotron Super | 0+0 | 1.18 | 20.9 | 22.09 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | yes | - | 0+0 | 1.61 | - | 1.61 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | yes | Nemotron Super | 0+0 | 0.72 | 22.43 | 23.16 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | NO | Nemotron Super | 0+0 | 1.83 | 18.63 | 20.46 | FAIL |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | yes | Nemotron Super | 0+0 | 6.85 | 17.82 | 24.67 | PASS |

## Run 2: 7/10 full answers

| # | Question | Tool / right? | Verdict / right? | Check passed | Key numbers | Written by | Retries (plan+rewrite) | PLAN s | EXPLAIN s | Total s | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | NO | Nemotron Super | 0+0 | 1.17 | 16.34 | 17.53 | FAIL |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | yes | Nemotron Super | 0+0 | 0.72 | 15.84 | 16.57 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | yes | Nemotron Super | 0+0 | 0.53 | 12.15 | 12.69 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | NO | Nemotron Super | 0+0 | 0.73 | 12.76 | 13.5 | FAIL |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | yes | Nemotron Super | 0+0 | 1.34 | 19.91 | 21.26 | PASS |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | yes | Nemotron Super | 0+0 | 0.96 | 70.28 | 71.26 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | yes | - | 0+0 | 0.55 | - | 0.55 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | yes | Nemotron Super | 0+0 | 0.51 | 10.92 | 11.43 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | NO | Nemotron Super | 0+0 | 0.54 | 13.01 | 13.55 | FAIL |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | yes | Nemotron Super | 0+0 | 0.5 | 18.57 | 19.07 | PASS |

## Run 3: 6/10 full answers

| # | Question | Tool / right? | Verdict / right? | Check passed | Key numbers | Written by | Retries (plan+rewrite) | PLAN s | EXPLAIN s | Total s | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Can I afford a $400 flight home for Thanksgiving if I book it Nov 10? | can_afford / yes | yes_if / yes | yes | NO | Nemotron Super | 0+0 | 2.48 | 23.55 | 26.04 | FAIL |
| 2 | How long will my money last? | runway / yes | runs_out / yes | yes | yes | Nemotron Super | 0+0 | 0.72 | 24.2 | 24.92 | PASS |
| 3 | Where is my money leaking? | find_leaks / yes | - / yes | yes | yes | Nemotron Super | 0+1 | 0.53 | 30.75 | 31.29 | PASS |
| 4 | What if I pick up a 5 hour shift on Nov 7? | what_if / yes | runs_out / yes | yes | NO | Nemotron Super | 0+0 | 1.1 | 9.86 | 10.98 | FAIL |
| 5 | Can I afford new headphones for $150? | can_afford / yes | no / yes | yes | yes | Nemotron Super | 0+0 | 0.64 | 10.89 | 11.55 | PASS |
| 6 | Can I put a $120 concert ticket on my credit card on Nov 20? | can_afford / yes | yes_if / yes | yes | yes | Nemotron Super | 0+0 | 1.06 | 22.31 | 23.38 | PASS |
| 7 | What's the capital of France? | none (off-topic) / yes | - / yes | yes | yes | - | 0+0 | 0.5 | - | 0.5 | PASS |
| 8 | am I ok? | runway / yes | runs_out / yes | yes | yes | Nemotron Super | 0+0 | 0.41 | 58.54 | 58.96 | PASS |
| 9 | Why is my refund on hold? | refund_status / yes | - / yes | yes | NO | Nemotron Super | 0+0 | 0.43 | 11.88 | 12.31 | FAIL |
| 10 | Is there a week coming up where money gets really tight? | cash_crunches / yes | - / yes | yes | NO | Nemotron Super | 0+0 | 0.37 | 27.32 | 27.69 | FAIL |
