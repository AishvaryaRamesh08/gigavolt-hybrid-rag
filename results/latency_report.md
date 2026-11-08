# Latency report

Questions run: 36. Used for percentiles: 36 (excluded: 0, rate limit or LLM error).
Backend: gemini:gemini-3.5-flash-lite. Stores queried in parallel threads.

| Stage | P50 (ms) | P95 (ms) | P99 (ms) | Samples |
|---|---:|---:|---:|---:|
| route | 0.2 | 0.3 | 0.5 | 36 |
| encode | 18.3 | 26.5 | 41.0 | 36 |
| sql | 21.3 | 75.5 | 77.2 | 27 |
| vector | 7.3 | 45.1 | 55.2 | 36 |
| mongo | 5.7 | 9.3 | 9.3 | 21 |
| retrieve_parallel | 17.9 | 75.1 | 77.6 | 36 |
| assemble | 0.2 | 0.2 | 0.2 | 36 |
| generate | 1734.3 | 5280.3 | 8316.4 | 36 |
| verify | 0.3 | 0.5 | 0.8 | 36 |
| total | 1780.9 | 5319.0 | 8346.8 | 36 |

**End-to-end median: 1.78 s, target under 5 s: met.** Questions over target: 3 of 36.

## Total time per query

| Query | Run 1 (s) | Run 2 (s) | Run 3 (s) |
|---|---:|---:|---:|
| What are common failure modes for Model X-7000 batteries in high-temperature environments? | 1.43 | 3.34 | 1.29 |
| Which suppliers provide lithium cells for our commercial energy storage units? | 3.36 | 1.24 | 0.88 |
| Show me service history for equipment unit SN-4829 and related warranty claims | 3.45 | 1.50 | 1.19 |
| Show me the service history and warranty claims for equipment unit EQ-7171 | 3.48 | 3.69 | 1.59 |
| What happened to unit SN-X7-0094 and which components were flagged? | 1.23 | 1.39 | 3.13 |
| What does fault code ERR_COOL_302 indicate and on which units has it occurred? | 5.20 | 9.78 | 1.34 |
| How hot do C-1200 units get during thermal faults and what do the manuals advise? | 1.43 | 3.29 | 1.55 |
| What is the procedure for filing a field warranty claim? | 2.77 | 1.98 | 2.94 |
| What should a technician do in a battery fire or thermal runaway emergency? | 1.21 | 1.40 | 2.49 |
| What are the specifications of the LFP battery cell? | 5.68 | 1.98 | 1.53 |
| What are the most common service resolutions and warranty claim outcomes for X-5000 units? | 3.44 | 1.50 | 3.30 |
| What was Gigavolt's total revenue last quarter? | 2.79 | 0.91 | 0.56 |

## Latency per question

Each value is one run, in run order.

| Category | Question | Total (s) | Retrieval (ms) | Gemini (ms) |
|---|---|---|---|---|
| sample query 1 | What are common failure modes for Model X-7000 batteries in high-temperature environments? | 1.43 / 3.34 / 1.29 | 77 / 78 / 75 | 1330 / 3249 / 1196 |
| sample query 2 | Which suppliers provide lithium cells for our commercial energy storage units? | 3.36 / 1.24 / 0.88 | 23 / 21 / 21 | 3312 / 1199 / 839 |
| sample query 3, not in ERP | Show me service history for equipment unit SN-4829 and related warranty claims | 3.45 / 1.50 / 1.19 | 22 / 22 / 22 | 3396 / 1439 / 1135 |
| multi-source unit | Show me the service history and warranty claims for equipment unit EQ-7171 | 3.48 / 3.69 / 1.59 | 52 / 54 / 53 | 3396 / 3602 / 1496 |
| telemetry unit | What happened to unit SN-X7-0094 and which components were flagged? | 1.23 / 1.39 / 3.13 | 22 / 21 / 21 | 1163 / 1333 / 3071 |
| fault code | What does fault code ERR_COOL_302 indicate and on which units has it occurred? | 5.20 / 9.78 / 1.34 | 15 / 13 / 12 | 5158 / 9753 / 1309 |
| thermal, model | How hot do C-1200 units get during thermal faults and what do the manuals advise? | 1.43 / 3.29 / 1.55 | 15 / 14 / 15 | 1389 / 3258 / 1518 |
| procedure | What is the procedure for filing a field warranty claim? | 2.77 / 1.98 / 2.94 | 6 / 7 / 7 | 2741 / 1953 / 2917 |
| safety | What should a technician do in a battery fire or thermal runaway emergency? | 1.21 / 1.40 / 2.49 | 6 / 6 / 6 | 1180 / 1378 / 2469 |
| specification | What are the specifications of the LFP battery cell? | 5.68 / 1.98 / 1.53 | 6 / 7 / 7 | 5648 / 1950 / 1469 |
| warranty aggregate | What are the most common service resolutions and warranty claim outcomes for X-5000 units? | 3.44 / 1.50 / 3.30 | 57 / 58 / 58 | 3364 / 1425 / 3223 |
| out of scope | What was Gigavolt's total revenue last quarter? | 2.79 / 0.91 / 0.56 | 3 / 3 / 3 | 2764 / 892 / 542 |
