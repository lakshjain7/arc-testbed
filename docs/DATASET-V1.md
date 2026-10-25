# ARC dataset v1.0: scope, composition, splits, known issues (frozen 2026-10-25, held added when finished)

This file is the seed of the dataset's datasheet and of the dataset section of paper 1. Numbers come from the lab's
`index/episodes.csv` (1,691 episodes on 25 Oct) and the decision log (`research/09-decision-log.md`); nothing here is estimated.

## What v1.0 contains

One episode = one incident on a running Train Ticket system: a fault is injected, a remediation action is applied after
60-300 s, and per-service and per-user-flow request counts, latencies, errors, resource use and the call graph are recorded
before and after the action. 6 action types (no-op, restart-pod, rollout-restart, scale-up, cpu-bump, drain).

| Part | Episodes (usable) | System | Load | Calibration | Faults | Role |
|---|---|---|---|---|---|---|
| batch 1: `main` + `main2` | 253 + 448 = 701 | 20 services (core mix) | 4 req/s | calibration-batch1 | none, pod-kill, network-delay, net-loss, cpu-squeeze (`main` only) | train / in-system test |
| wide1 | 500 (of 504 planned) | 25 services (wide mix) | 4 req/s | calibration-wide | none, pod-kill, pod-hang, network-delay, net-loss | unseen-system test; extra training |
| wide1db | 126 | 25 services | 4 req/s | calibration-wide | none, pod-kill, db-delay | unseen-fault test |
| wide2 | 301 | 25 services | 8 req/s | calibration-wide-8 (see issue 3) | none, pod-kill, pod-hang, network-delay, net-loss | higher-load test |
| reptest | 20 (4 recipes x 5 runs) | 25 services | 8 req/s | calibration-wide-8c | none, network-delay, net-loss | repeatability / noise ceiling |
| held | 147 planned (7 conditions x 21) | 25 services | 8 req/s | calibration-wide-8c | none, pod-kill, call-cut (3 links), load-surge (3x, 4x) | held-out new faults (never trained on) |
| calibration | 60 (+ 20 for 8c) | | | | none (no-op) | thresholds only, not campaign data |

Totals before held: 1,648 campaign episodes (701 + 500 + 126 + 301 + 20) plus 60 calibration episodes + 2 early db-delay test
episodes (`wide` plan, not part of the benchmark). With held: 1,795 campaign episodes.
Actions are balanced (about 232 per action type; no-op about twice as many, by design). Everything was recorded on
one machine (i9-13900, 32 GB) in one cluster (kind + Chaos Mesh); the 89-episode laptop pilot is not part of v1.0.

## Splits (official)

1. In-system: every 5th block of each plan (block % 5 == 0) is test; blocks never straddle train and test.
2. Unseen system: train on batch 1 (core mix, 20 services), test on all of wide1 (25 services, 5 new services).
3. Unseen fault: train on wide1, test on wide1db (db-delay never seen).
4. Held-out faults: train on everything except held; test on held (never seen: call-cut, load-surge).
5. Higher load: train on 4 req/s data, test on wide2 (8 req/s).
6. Noise ceiling: reptest (the same incident repeated 5 times).

## Label sets

Per service: `y_mean` (mean rise of the bad-request share over the 180 s after the action) and `y_peak` (worst 30 s block),
where a request is bad if it failed or exceeded a latency bar. Bars: the calibrated per-operation bar (in practice 100 ms
for 58 of 65 operations, higher for booking: finding in decision log 10i), and fixed 500 ms / 1000 ms bars. The
label-sensitivity analysis (decision log, when finished) shows how far the conclusions depend on the bar.
The raw per-request and per-step data are included, so any other label can be recomputed (`harness/relabel.py`).

## Known issues (each is a numbered finding in `research/08-lab-machine-findings.md`; do not hide them)

1. **Saturation (F11, F13).** Episodes where users were >= 80 % bad before the action are flagged `saturated_before_action`:
   batch 1 109 of 701, wide1 91 of 500, wide2 134 of 301 (most of wide2's are issue 2). Use the flag; with the fixed 1 s bar far fewer.
2. **Cancel-flow drift in the second half of wide2 (F21).** Two tables the cancel flow reads were not cleaned; cancel slowed
   from 77 to 131 ms during wide2 (and from 25 to 56 ms during wide1, which stayed under the 100 ms bar, so wide1's labels are unaffected). Relative labels of wide2 after 23 Oct 20:00 UTC are inflated
   for the cancel flow and its path (per-episode drift list: `wide2-cancel-b0.csv`). Use the 1 s bar labels for wide2, or the first half.
3. **wide2 was labelled with a calibration fitted on the drifted database (F22).** calibration-wide-8c (clean) replaces it from reptest on.
4. **Prometheus was killed 35 times during wide1 (F19);** 4 of 504 episodes lost; use the index, not the folder list.
5. **Hung-pod (pod-hang) episodes are all saturated** (the service answers nothing); they test blast-radius, not action ranking.
6. **Only one replica per service in all episodes;** the number of copies and the age of the fault are not model inputs.
7. **One machine, one system (Train Ticket), one fault injector (Chaos Mesh).** Fault levels were dosed on this machine (F5, F14, F20, F25);
   a level is not a severity.
8. **HTTP-level fault injection did not attach (F25);** the shared-database-slow fault was a cliff with no usable level and was dropped.
9. **Repeatability (F24, decision log 10h, 10i):** the same incident repeated gives a net effect within 12-27 % (coefficient of variation) for real actions;
   `y_peak` of services with few requests is unreliable (spread up to 53 points between identical runs).

## Release (to decide by the user)

Raw archives with sha256 (all already computed by the lab), the index, the per-bar labels, the splits, the loader and the
baseline/evaluation code. About 1 GB compressed. Recommended: Zenodo (DOI, archive) + Hugging Face (browsing); data CC BY 4.0, code MIT.
