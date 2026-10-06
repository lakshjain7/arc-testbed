# 07: H1 pilot results (laptop, 2026-10-04/05)

**Question (H1):** do remediation actions cause measurable collateral damage on services other than the one they target?
**Design:** 50 episodes, randomised complete blocks (7 faults-blocks × 7 + 1 spare), plan frozen before running (`harness/run_pilot.py`, seed 2026). Analysis fixed in advance (`harness/h1_analysis.py`). Laptop: kind, 20 Train Ticket services, 2 req/s continuous load, label v2 (per-operation bad-request ratio, calibrated on 20 no-fault no-op episodes, 0/183 held-out false harms).

## 1. Pre-registered result: H1 NOT supported

46 usable episodes (2 discarded: blackhole + noop failed the health check twice; 2 stalled), after the stall-rule correction below. Outcome C = number of services other than the action/fault targets with verdict "harm".

| action | n | mean C | vs noop |
|---|---|---|---|
| noop | 13 | 0.08 | — |
| cpu-bump (negative control) | 7 | 0.00 | −0.08 ✔ |
| scale-up | 7 | 0.00 | −0.08 |
| restart-pod | 7 | 0.14 | +0.07, p = 0.55 |
| rollout-restart | 5 | 0.20 | +0.12, p = 0.56 |
| **drain** | 7 | **0.86** | **+0.78, p = 0.038** |
| **disruptive (pooled)** | 26 | | **+0.23, p = 0.16** — criterion was ≥ +1.5 and p < 0.05 |

Where collateral harm landed: **8 upstream callers, 0 downstream, 1 neither.** Almost all of it is explained by the call graph.

**Two analysis corrections, made openly after the run:**
1. **Stall rule.** The stall detector (built for ambient laptop freezes in no-fault episodes) also removed fault-caused timeouts, which discarded most delay/squeeze episodes (36 → 46 usable after the fix: stalls are cut only when fault = none, label v2.1). Before the fix: +0.35, p = 0.12, still not supported.
2. **"≥ 2× noop" criterion.** With a noop mean of 0, any action passes trivially. The fix requires a positive mean C as well.

## 2. Exploratory (NOT pre-registered): magnitudes show a clear signal

`harness/h1_exploratory.py`. Same permutation test, but the outcome is magnitude instead of binary verdict counts:
- **A**: sum over non-target services of the worst-30 s rise in bad-request ratio (points)
- **B**: rise of user-facing bad-request ratio, summed over flows (search, book, orders, pay)

**18 of 46 episodes were saturated**: users were already ≥ 80% bad *before* the action (300 ms delay, ¼-CPU squeeze, blackhole). In those, no action can show more damage.

Non-saturated episodes (n = 28):

| action | users' extra bad (pts) | collateral magnitude (pts) |
|---|---|---|
| noop (n=10) | 6.7 | 73.9 |
| cpu-bump (4) | 0.3 | 29.4 |
| scale-up (4) | 0.8 | 50.8 |
| restart-pod (4) | 19.9 (p = 0.037) | 124.4 (p = 0.023) |
| rollout-restart (2) | 76.7 (p = 0.11) | 141.0 (p = 0.11) |
| **drain (4)** | **157.5 (p = 0.012)** | **260.0 (p = 0.012)** |
| **disruptive vs noop** | **+55.2, p = 0.001** | **+70.6, p = 0.002** |

**Caveats:** this was chosen after seeing the data; groups are tiny (2–4 per action); multiple comparisons; one laptop. It is a hypothesis for the full run, not a finding.

## 3. What the pilot taught us (design changes for the full run)

1. **Binary per-service "harm" is too insensitive at this load.** About 12 of 17 services are "inconclusive" in every episode. **Make magnitude the primary label** (y_mean, y_peak, y_excess, user-facing flows), which is ARC's original "per-service magnitude" claim. Keep the binary verdict as secondary.
2. **Fault strength must be moderate.** 39% of episodes were saturated. Use several milder levels (delay 50/100 ms; CPU squeeze ½ rather than ¼; packet loss 5/15%; drop blackhole or use it only as a "hard" level), and **exclude or stratify episodes saturated in B1**.
3. **Actions differ strongly and plausibly.** drain ≫ restart-pod > rollout-restart > scale-up ≈ cpu-bump ≈ noop. Surge-based actions (rollout-restart, scale-up) keep the old pod serving and are gentle. Removing a service (drain, hard restart) hurts its callers. This differential is what ARC must learn and predict.
4. **Collateral is mostly upstream callers, so graph reachability explains WHICH services get hurt.** ARC's added value must therefore be **how much, for how long, and which action is least damaging**, not "which services". A reachability baseline will be strong on the binary question; it is the baseline to beat on magnitude.
5. **Higher load improves sensitivity.** At 2 req/s, quiet services can only show ≥ 20–48-point effects. The lab machine should run more load (re-run the step test there).
6. **Other measured facts:** a Chaos Mesh network fault followed a rollout-restarted pod (`fault_on_new_pod = True`) but not a deleted pod (smoke test); scale-up's reset keeps the warm pod; the database must be reset between episodes; continuous load is required; a Nacos drain must be undone with the saved address.

## 4. Data

`~/arc/data/raw/ep_pilot_b*/` (52 directories including re-runs), `~/arc/data/pilot_plan.json`, `~/arc/data/h1_result.json`, logs in `~/arc/archive/pilot.log`.
