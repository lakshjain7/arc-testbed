# 09 — Project history and decision log (for writing the paper)

Written 2026-10-22 by the laptop Claude session that built the harness, from its working conversation
with Laksh (Sep 21 - Oct 22, 2026). Purpose: anyone writing the paper (teammates, another Claude session)
gets not only WHAT was done but WHY, what went wrong, and what we learned. Companion documents:
`07-pilot-results.md` (pilot numbers), `08-lab-machine-findings.md` (F1-F20, lab machine, with numbers),
`docs/RUNBOOK.md` (every infrastructure failure and fix), `docs/MEASUREMENT-SPEC.md` (label definition),
`docs/BATCH2.md` (batch 2 design), git log (every change, with its reason in the message).

Conventions: dates are 2026. "Laptop" = Laksh's laptop (WSL2, 17 GB, 2 req/s). "Lab" = the lab machine
(i9-13900, 32 GB, WSL 26 GB, 4 req/s). Numbers are measured unless marked *inferred*.

---

## 1. The question and how it was framed

- **Goal.** Predict, BEFORE an operator or an AI agent applies a remediation action (restart, scale up,
  drain, ...) during a live incident, how much each service of a microservice system will get worse and
  for how long. ARC = a damage predictor that agents call, plus the dataset to train it. Not an agent,
  not a gym.
- **Why it matters.** Remediation actions have side effects (a restart drops in-flight requests, a drain
  removes capacity). Agents are weak at incident handling (one recent paper reports the best agent solving
  13.8 % of SRE scenarios, arXiv:2601.17915). A pre-action damage check is a safety layer.
- **Closest prior work.** arXiv:2607.20005 (safe remediation; Train Ticket, 41 services, Chaos Mesh,
  partially randomised actions, BINARY blast radius per service inside offline RL). We therefore do NOT
  claim "first to predict blast radius". Defensible differences: per-service damage MAGNITUDE and
  duration (not yes/no), fully randomised actions, a released dataset with machine-independent labels,
  an action-conditioned model that beats graph-diffusion, a timed dynamic model, cross-system tests.
- **Positioning lessons from discussion with Laksh.** He rejected selling "randomisation" or "the label
  formula" as the contribution (they are validity conditions); uniqueness must come from results.

## 2. Testbed decisions (Sep 21-30, laptop)

| Decision | Why | Evidence / incident |
|---|---|---|
| Train Ticket on kind (Kubernetes in Docker), core profile of 20 services | The services on the search/book/pay path; the others get no traffic from our users | 45 services do not fit in memory (laptop 17 GB, lab 26 GB) |
| Nacos at 1 standalone copy, MySQL at 3 | Nacos cluster mode went inconsistent after restarts (copies knew 8, 8 and 20 services) -> random 503s | RUNBOOK |
| CPU limit 2 cores per service (chart: 500m) | At 500m one search took 2-3 s and 1 req/s timed out | measured on laptop |
| OpenTelemetry Java agent -> collector (spanmetrics + servicegraph, 5 s flush) -> Prometheus (5 s scrape) | Per-operation request counters and the call graph every 5 s; the labels are computed from these counters | first config scraped every 60 s and capped latency buckets at 5 s; both fixed |
| Open-loop load generator (Poisson arrivals) | A closed-loop generator sends less when the system slows down and hides damage | |
| Continuous background load, steady-state gate, database reset between episodes | Warm-up drift biased "after" vs "before"; 18 h of load grew orders to 14,372 rows and made every request 5-10x slower | pilot noise episodes; F9 on the lab |
| Bring services up in small batches | Starting all JVMs at once crash-loops Nacos registration | repeated on every restart |

## 3. Episode design

health gate -> database reset -> steady gate -> B0 120 s healthy baseline -> fault -> wait 60-300 s
(random) -> B1 = last 30 s before the action (labels use B1L = last 60 s) -> ACTION -> 5 s grace ->
M = 180 s -> remove fault, undo action -> export -> label. Each fault and action is VERIFIED after it is
applied (an unverified episode is marked discarded, never kept silently).

**Fault set history.** Smoke tests killed two candidates that "succeeded" while doing nothing:
StressChaos ran its stress processes outside the target container on kind + cgroup v2 (whole host at
load 25, target never throttled) -> replaced by cpu-squeeze (in-place CPU-limit cut). A NetworkPolicy
"quarantine" blocked nothing because of kept-alive connections -> replaced by a Nacos "drain".
Lesson for the paper: a fault/action must be proven by a measured effect, not by "applied OK".

**Actions:** noop, restart-pod, rollout-restart, scale-up, cpu-bump, drain; random within blocks of 7
(every action once + noop twice). The no-op is the counterfactual reference.

## 4. The label (how "damage" is measured)

- Per operation, a request is BAD if it failed or was slower than T = smallest histogram bucket >=
  max(100 ms, healthy q99), fitted on dedicated no-fault no-op calibration episodes. This is a ΔSLO:
  errors and slowness combined, as an SLO is stated.
- Per service: bad share in M minus bad share in B1L. y_mean (whole M), y_peak (worst 30 s block),
  y_excess (extra bad requests), t_recover, verdict harm / no_harm / inconclusive with a calibrated z
  and per-service variance inflation phi. Negative values = the action IMPROVED the service.
- Per user flow (search, book, pay, orders, ...) the same, from what the simulated users saw; this is the
  only place HTTP-200 business failures are visible.
- **History.** v0 (latency only) gave 2-6 false harms per no-op episode -> v1 pooled -> v2 bad-request
  ratio with calibration (held-out false harm 0/183 on the laptop). v2.1: stalls (whole-machine
  freezes) are cut only in no-fault episodes, because in fault episodes the fault causes the timeouts.
  **v2.2 (12 Oct, found by the lab session, F13):** after the action, stalls are cut only when the action
  is a no-op. A restart in a healthy system makes requests time out, which looked like a stall, and 69-75 %
  of the after-action window was being deleted, i.e. exactly the damage we measure. Pilot effect:
  rollout-restart in a healthy system went from 0 to 124-140 points of user damage once fixed.
- **Fixed-threshold labels ("abs", 500 ms and 1 s), added 10 Oct.** The relative threshold follows each
  machine's healthy speed (35 ms requests on the lab -> a 150 ms answer is "bad"). The fixed ones mean the
  same on every machine. F13: of 92 episodes "saturated" by the relative bar only 36 were saturated by the
  1 s bar. The paper must say which bar a number uses.
- **Saturation flag**: users >= 80 % bad before the action. Such episodes cannot show further harm by the
  relative bar (they can still show improvement).

## 5. Pilot (laptop, Oct 3-5) — what it changed

50 pre-registered episodes. Pre-registered H1 (actions cause collateral harm, binary count) NOT supported
(+0.23 services, p = 0.16; only drain significant). Exploratory magnitudes in non-saturated episodes: user
damage +55 points (p = 0.001); ranking drain >> restart-pod > rollout-restart > scale-up ~ cpu-bump ~ noop;
collateral lands almost only on UPSTREAM callers (8 upstream, 0 downstream, 1 neither). 18 of 46 episodes
saturated: faults too strong (300 ms delay, 1/4 CPU, blackhole). Decisions: magnitude labels primary,
milder multi-level faults, more load, keep the binary verdict secondary. Later found: the load generator
had a pay-flow starvation bug (13 of 52 pilot episodes without payments), fixed 11 Oct.

## 6. Moving to the lab machine (Oct 7-10) and machine dependence

- Built from the repo in 77 min; F1: MySQL OOM crash loop caused by the host's open-files limit
  (containerd LimitNOFILE=infinity, 2^31) -> capped in setup.
- **The central methodological finding (F5, F10, F11, F14): a fault setting is not a severity.** On the
  lab (faster, healthy 25-35 ms) 25 ms of delay made 74 % of requests bad (laptop: 31 %). Severity depends
  on the machine, the load, AND the target: 4 ms saturated order and basic every time and the other four
  targets never, because order and basic are called many times per user request. Delay is a cliff
  (seat: 2 ms 2 %, 4 ms 41 %, 6 ms 100 %). CPU squeeze is a switch, not a dial (laptop: 3x normal use = 0-3 %,
  2x = 55-100 %).
- **Response (the design argument for the paper).** The fault setting is NEVER a model input; actions are
  randomised within each fault level, so per-machine dosing only chooses which incidents are sampled. What
  must be machine-independent is the label (fixed-threshold version) and the model inputs (ratios to each
  service's own baseline). Doses are measured per machine and per target ("dose check"), judged by the
  WORST user flow (what the saturation flag uses; averaging hid a search flow at 100 %, F14).

## 7. Batch 1 (Oct 10-16) — 701 episodes + 20 calibration

- Plan "main" (253): delay 4/7 ms, loss 12/22 %, squeeze 4x/1x chosen partly by interpolation; delay 7 and
  squeeze 1x saturated everything (F11). Also the MySQL audit log grew 9.2 GB in 49 h (F12) -> emptied
  before every episode. Stopped at 253.
- Plan "main2" (448): delay 3.2/4 ms, loss 11.3/15 %, no squeeze, per-target scale order 0.35, basic 0.7
  (decided with Laksh: "per-target strength", option A). 17 saturated (3.8 %).
- Windows Update restarted the machine twice (31 h lost, F15); the resume design lost no recorded episode.
- After the end, the still-running load generator filled the database until everything failed (F16) ->
  the runner now stops it.

## 8. Batch 2 (Oct 17-21) — the wider system, 500 usable episodes

- 25 services: five more brought into play by new simulated user flows (other train types, insurance,
  cancel, ticket collection), each tested on the laptop first (0 failures under load).
- Laksh's requirement: batch 2 must include NEW faults. Added and smoke-tested: **pod-hang** (Chaos Mesh
  pod-failure: alive, answers nothing; 77/77 saturated by nature; useful through whether an action cures
  it) and **db-delay** (delay on MySQL's replies to the target). db-delay first did nothing on the lab
  (F17): the target reaches MySQL through a Service IP translated after the packet leaves the pod, so the
  filter never matched -> moved to the reply side; validated selective (untargeted station unaffected).
- Same 4 req/s as batch 1 (lab session's point: then batch 1 -> 2 changes only the system).
- Calibration bug (F18): the wide calibration fitted on every no-fault no-op episode on disk (mixing
  load mixes) and rewrote 48 batch-1 labels. Fixed: calibration uses only dedicated ep_cal episodes of the
  same mix and never rewrites labels; batch 1 relabelled from its own calibration (identical to the archive).
- Prometheus was OOM-killed 35 times with 25 services (1 Gi limit) -> 2 Gi.
- wide1db (db-delay, 126 episodes, Oct 21-22): order is a switch even at 2 ms -> excluded; travel,
  station, travel2 with per-target scale. Plan-generator bug found by the lab session (blocks of 4 with
  3 targets) -> fixed.

## 9. Models and results so far (laptop CPU; batch 1 test split by block, 133 episodes)

Target y_peak (worst 30 s rise, points), services with >= 30 requests.

| Predictor | MAE | Spearman | worst-hit service found |
|---|---|---|---|
| no damage | 6.39 | 0 | 3 % |
| mean damage of the action | 9.03 | 0 | 3 % |
| role in the call graph (caller / callee / ...) | 4.01 | 0.46 | 19 % |
| role + the service's own badness before the action | 3.82 | 0.62 | 35 % |
| graph diffusion from the target (prior-work style) | 8.11 | 0.13 | 9 % |
| **action-conditioned GNN** (latency inputs dropped) | **1.84** | **0.69** | **77 %** |

- Ablation (GNN): without the action MAE 5.29; without the graph 3.03 (top-1 51 %); without prior
  badness 2.34; without roles no change (the graph carries it); without latency features slightly
  better -> dropped. Answers recent claims that graphs do not help (arXiv:2501.02766): for action
  effects they do.
- Other targets: y_mean 1.19 vs best baseline 2.37; fixed 1 s bar 1.45 vs 3.34.
- **Unseen system** (train batch 1, test all 500 batch-2 episodes): GNN 3.01 / 0.65 / 56 % vs best rule
  4.17 / 0.58 / 35 %. By fault: known faults stay close to in-system quality (none 1.54, delay 2.40, loss
  2.60, pod-kill 3.71); the never-seen pod-hang is the weak spot (6.43, 30 %). Top-up with 7/14/28 blocks
  of batch 2: MAE 2.82 / 2.80 / 2.52, top-1 62 / 60 / 63 %.

## 10. The dynamic model (Laksh's idea, Oct 22)

Laksh proposed predicting the TIME COURSE: a service's state at t+1 depends on its own previous state and
a weighted combination of its neighbours' states, plus the action. Built as:

  d_i(k+1) = a d_i(k) + w_down mean(callees) + w_up mean(callers) + g d_i(k_action) + u[action, role, lag]

on 15 s steps (deviation of the bad share from the service's healthy level). Linear fit on batch 1:
a = 0.84 (trouble persists), **w_down = 0.17 vs w_up = 0.02: trouble climbs from a service to its
callers about 9x more than the other way** (the pilot's "collateral is upstream", now as a coefficient).
Action impulse on the target: restart-pod +3.0, +2.8, -4.8 points at +15/30/45 s (worse while down, then
better). Rollout from the action: in-system step MAE 3.72 vs persistence 4.66; unseen system 3.52 vs
persistence 3.03 (the shared linear coefficients do not transfer). ~2 ms per 3-minute rollout. Graph-network
version (`harness/dyn_gnn.py`, per-service learned coefficients, trained by rolling out 3 minutes):
in-system step MAE 2.17 +- 0.05, peak error 2.10 (linear 3.72 / 4.02, persistence 4.66 / 5.35);
UNSEEN SYSTEM step MAE 2.21 +- 0.01, peak error 2.61 (linear 3.52 / 4.01, persistence 3.03 / 3.92), i.e.
it keeps its in-system accuracy on the new system, unlike the linear version. 3-5 ms per rollout on a
laptop CPU. Roles: linear version = the explanation, graph version = the predictor.
Mathematical framing: a linear dynamical system / network VAR on the service graph, the discrete form of
dx/dt = -(1-a)x + Wx + Bu; actions are randomised, so u is a causal effect, not a correlation.
Related: Sage (CBN latency propagation callee -> caller, diagnosis), HyperODE-RCA (neural ODE, diagnosis),
GRAF and LQ-GNN (prediction feeding resource decisions). None models a remediation action as a controlled
input to every service's trajectory.

## 10b. Explainable blast radius (Oct 22, `harness/blast_radius.py`)

**Why.** Laksh asked for the blast radius to be explainable: which services, how much, in what ORDER and
along which CALLS, and what KIND of damage. Per-service totals alone hide the chain.
**How.** From the 15 s trajectories: onset = first step after the action with the bad share >= 5 points
above its pre-action level for two steps in a row; recovery = first step after which it stays within 5
points; damage profile = change in bad share, error share, p95 ratio, traffic ratio, CPU throttling; "via"
= the earlier-hit neighbour on the call graph, with the action target as the origin at t = 0 (a drained or
restarting target often has no traffic, so it cannot show its own rise).
**Results (batch 1 / batch 2).**
- Services hit per episode: drain 3.35 / 2.77, restart-pod 1.93 / 1.83, rollout-restart 1.80 / 1.49,
  scale-up 0.99 / 0.56, cpu-bump 0.63 / 0.51, noop 0.62 / 0.63 (the no-op rate is the noise floor:
  ~0.6 false "hits" per episode, all on services not connected to any target).
- Almost every hit is an UPSTREAM caller: e.g. drain 3.29 callers vs 0.02 callees per episode.
- **The chain follows the call graph:** for real actions 75-96 % of hit services (86-96 % for restart,
  rollout, drain) have an earlier-hit neighbour on the call graph; for no-op only 15-21 % (chance level of
  the noise). This is the evidence that damage PROPAGATES along calls rather than appearing at random.
- **Timing:** median onset after the action: direct callers 30 s (batch 2: 45 s), 2-3 hops 45 s; i.e. the
  damage climbs one hop per ~15 s step toward the gateway. Callees rarely hit, and late (60-105 s).
- **Damage kind:** a drain makes callers fail FAST (errors +80-100 points but p95 x0.2-0.6: requests fail
  quickly), whereas restart / rollout make them fail SLOW (p95 x60-450 plus errors). The damage profile
  separates "unavailable" from "slow", which the single score cannot.
- Example (ep_main2_arc_b001_1, drain on order, no fault): gateway, preserve, security +15 s (1 hop),
  seat +30 s, travel +30 s via preserve (2 hops), inside-payment +105 s; 6 services, 548 points.
**Use in the paper.** The blast radius figure: a timed tree per action type; the "chain follows calls"
statistic against the no-op noise floor; the fast-fail vs slow-fail split.

## 10c. Does ARC choose the right action? (Oct 22, `harness/action_rank.py`)

**Why.** ARC's use is to score candidate actions for an incident, so the decisive test is ranking, not
per-service error. Each episode shows only one action's outcome (the counterfactual problem), so we use
pairs of test episodes with the same fault type and fault target (the same kind of incident) handled with
different actions, and ask whether the predicted net effects (sum of signed y_mean over services) are
ordered as observed. Pairs whose observed net effects differ by < 2 points are skipped.
**Results (3 seeds).**
| Test | Pairs | Action-mean baseline | ARC |
|---|---|---|---|
| batch 1 (in-system) | 361 | 75.3 % | **78.8 ± 1.3 %** |
| unseen 25-service system | 3,419 | 76.5 % | **83.9 ± 0.3 %** |
Scoring one candidate action: ~4-5 ms; all six: ~25-30 ms on a laptop CPU.
**Interpretation, honestly.** The baseline that only knows each action type's average effect is already
strong (75-77 %), because actions differ a lot on average (drain >> restart > ... > no-op). ARC's added
value is +3.5 points in-system and +7.4 points on the unseen system, i.e. it uses the incident state to
order actions the average gets wrong, and the gain is larger on the new system. The net-effect error is
large in absolute terms (16 and 37 points summed over all services), so ARC is better at ORDERING actions
than at stating their exact total damage. Next: report "hard pairs" (pairs where the two action types have
similar averages), where the baseline is near chance and ARC's added value should be clearest.

## 10d. Full evaluation round, 22 Oct (protocol: docs/research/10-evaluation-protocol.md)

**New baselines (B5-B7) added after Laksh asked for existing approaches, not only our own rules.**
y_peak, services with >= 30 requests. MAE (points) / Spearman per episode / top-1 worst-hit.
| Test | B5 dependency map | B6 trees, no graph | B3 best rule | ARC |
|---|---|---|---|---|
| T1 batch 1 (133) | 6.46 / 0.41 / 15 % | 3.96 / **0.74** / 39 % | 3.82 / 0.62 / 35 % | **1.84** / 0.69 / **77 %** |
| T2 unseen system (500) | 5.80 / 0.43 / 16 % | 3.91 / **0.76** / 34 % | 4.17 / 0.58 / 35 % | **3.01** / 0.65 / **56 %** |
| T4 unseen fault db-delay (126) | 4.71 / 0.43 / 18 % | 2.61 / **0.76** / 48 % | 3.13 / 0.65 / 48 % | **1.86** / 0.68 / **67 %** |
**Honest reading.** ARC wins clearly on error (MAE) and on finding the worst-hit service. Gradient-boosted
trees on per-service features (B6) rank the services within an episode BETTER than ARC (Spearman 0.74-0.76
vs 0.65-0.69): they order the many small effects well but miss which service is hit hardest. This must be
reported; it also suggests a combined model (ARC + per-service trees, or a ranking loss) as an easy
improvement.
**Yes/no "harmed" (>= 10 points), the closest prior work's view.** F1: B5 0.60 / 0.56 / 0.63,
B7 classifier 0.73 / 0.69 / 0.73, ARC 0.76 / 0.70 / 0.74 (T1 / T2 / T4); ARC has the highest precision
(0.85-0.91). On the binary question ARC is only slightly better than a dedicated classifier; ARC's
advantage is in magnitude, worst-hit service, time course and the gate, i.e. exactly what the binary
formulation cannot express. The dependency map flags every caller: high recall, precision ~0.5.
**T4, the second unseen fault (db-delay), generalises well, unlike pod-hang:** db-delay episodes MAE 2.04,
top-1 73 % (pod-hang in T3: 6.43, 30 %). Dynamic model step MAE 1.23 vs persistence 2.12. Action ranking
85.1 % vs action-mean 75.9 %. Interpretation: a slow dependency produces symptoms like the network delay
ARC has seen; a hung service (alive, answering nothing) is a qualitatively new pattern.
**T9 hard pairs** (action types with mean effects within 5 points): batch 1 has only 10 such pairs (too few
to conclude); unseen system 142 pairs: action-mean 68.3 %, ARC 73.9 / 68.3 / 77.5 % over 3 seeds (mean 73 %).
**T10 confidence (bootstrap over incident kinds, 1,000 resamples).** ARC's lead over action-mean in action
ranking: batch 1 -2.4 to +12.6 points (NOT significant; 15-35 % of resamples <= 0); unseen system +1.4 to
+11.5 points (significant; 0.1-1.2 % of resamples <= 0).
**T11 damage-control gate (harmful = observed net effect >= 20 points).** Block if predicted >= 20 points:
| Test | ARC catches / wrongly blocks | action-type rule catches / wrongly blocks |
|---|---|---|
| batch 1 (39 harmful of 133) | 97 % / 2 % | 100 % / 19 % |
| unseen system (111 of 491) | 87-89 % / 6-7 % | 95 % / 28 % |
The headline safety result: about the same harmful actions caught, with 4-10x fewer safe actions blocked.
**T12 blast radius from PREDICTIONS (dynamic GNN) vs the measured chain**, real actions only: which services
are hit, F1 ARC 0.74 vs dependency map 0.64 (batch 1); 0.71 vs 0.55 (unseen); ARC precision 0.80 / 0.67 vs
0.50 / 0.40. ORDER of onset: not predicted (Spearman -0.21 and -0.15 over only 5 and 18 episodes with >= 3
services hit in both; at 15 s steps most hits look simultaneous). Claim "which and how much", not "in what
order", from predictions; the order is shown on measured chains (10b).

## 11. Decisions on scope (with Laksh)

- Paper option A: a research paper (ARC: dataset + harness + action-conditioned prediction + unseen-system
  test), with the lab lessons as a section. A survey would waste the new data.
- "Complete model on one application" over "partial model on two": the idea must be complete; one
  application is a stated limitation; a second application (Online Boutique) is the next paper. Deadline:
  lab machine until 1 Nov (Windows Update resumes); paper experiments targeted for late Oct.
- Latency matters: predictions must be cheap enough for an agent to call (ms, not seconds).
- Explainability: blast radius as which services, how much, in what order along which calls.

## 12. Known limitations (state them in the paper)

One application (Train Ticket); 6 action types (no rollback, no scale-down); one main machine (+ laptop
pilot); load 4 req/s only (higher-load run planned); CPU faults thin (squeeze dropped after main);
pod-hang always saturated; quiet services have noisy labels (weighted / excluded below 30 requests);
fault doses tuned per machine and target (documented, not hidden); injected faults, not real incidents.

## 13. Data inventory

| Set | Episodes | Where |
|---|---|---|
| Laptop pilot | 89 | OneDrive ARC-backup (arc-pilot-dataset-2026-10-07.zip) |
| Batch 1 (main, main2, cal 001-020) | 721 | arc-data-DESKTOP-UJ3ATL6-2026-10-17.tar.gz, sha256 d49a27c7... |
| Batch 2 (wide1, cal 021-040) | 524 folders, 500 usable | arc-data-wide1-2026-10-21.tar.gz, sha256 a8bc083e... |
| Corrected labels for both | 1,243 labels | arc-labels-index-2026-10-21.tar.gz, sha256 d8f68c63... |
| wide1db (db-delay) | 126 planned | on the lab machine, ends 22 Oct |

### 10e. 5-fold cross-validation on batch 1 (2026-10-23)

**Why.** The batch-1 numbers so far came from one test split (block % 5 == 0, 133 episodes) and only 10 hard
pairs. Cross-validation tests every block once, so the numbers do not depend on one lucky split.
**How.** `--fold k` in train_gnn.py, baselines.py, action_rank.py (fold k tests blocks with block % 5 == k).
ARC = GNN without latency inputs, 2 seeds per fold for damage and 1 seed per fold for ranking. Every value in the
table is the mean of the 5 folds.

| Measure | ARC | B6 trees | B3 rule | B5 dependency map | B7 / B1 |
|---|---|---|---|---|---|
| Damage MAE (points) | **1.98** (1.81-2.19) | 4.43 | 3.86 | 6.73 | - |
| Spearman | 0.68 | **0.75** | 0.61 | 0.41 | - |
| Top-1 hit | **0.78** | 0.40 | 0.37 | 0.15 | - |
| Yes/no F1 | **0.77** | - | - | 0.64 | B7 0.75 |
| Pairs ordered right | **86.3 %** | - | - | - | B1 80.1 % |
| Hard pairs (100 over 5 folds) | **68 %** | - | - | - | B1 51 % |
| Gate at 20 points: catches / wrongly blocks | 83.8 % / **1.6 %** | - | - | - | rule 91.7 % / 21.2 % |

- The fold-0 numbers match the earlier single-split ones, and all 5 folds agree. The single split was not lucky.
- The trees still rank services better (Spearman 0.75 vs 0.68 in all 5 folds). This is a stable finding to report,
  and the reason for combining ARC with B6 (item 5).
- Ranking: ARC leads B1 by 0 to 11 points. The bootstrap lead is significant in 3 of 5 folds (1, 3, 4) and not in
  folds 0 and 2. With 100 hard pairs, ARC gets 68 % against B1's 51 %. The 10-pair result was too small to judge;
  this one is not.
- Gate: ARC blocks about 13 times fewer safe actions (1.6 % vs 21.2 %) but misses more harmful ones (catching
  83.8 % vs 91.7 %). This is a threshold choice; report the full curve.
- Speed: scoring all six candidate actions takes 23-31 ms.

**Train on main2 only** (308 instead of about 560 training episodes): batch-1 test MAE 2.13 (vs 1.84 with all
plans), unseen system 2.86 (vs 3.01). Fewer episodes from one plan cost a little in-system and nothing unseen, so
the result does not depend on mixing plans.

### 10f. "I'm not sure" signal, ARC + trees, best-case root cause (T13), LLM baseline (B8) (2026-10-23)

harness/extras.py (5-seed ensemble, y_peak, latency off) and harness/llm_baseline.py.

**"I'm not sure".** Disagreement = the spread of the 5 seeds' predictions. Novelty = the distance to the nearest
training episodes.

| Setting | Ensemble MAE | Disagreement vs error (Spearman) | Error of the 20 % most flagged / rest | Novelty above the 95th pct |
|---|---|---|---|---|
| Batch 1 | 1.78 | 0.53 | 3.73 / 1.31 | 5 % |
| Unseen system | 2.80 | 0.74 | 7.19 / 1.95 | 22 % |
| Unseen fault (db-delay) | 1.86 | 0.79 | 4.52 / 1.16 | 55 % |

Disagreement is the useful signal: it is stronger the further the test is from training. Novelty is a weak
predictor of error but a good alarm for "this is a new system or fault" (5 % → 22 % → 55 %).
Intuition: seeds agree where the training data pinned the answer down and drift apart where it did not.

**ARC + trees.** Per service, w·ARC + (1−w)·trees, with w chosen on validation.

| Setting | ARC alone | Chosen blend |
|---|---|---|
| Batch 1 | MAE 1.78, Spearman 0.70 | w = 0.9: MAE 1.89, Spearman 0.74 |
| Unseen system | MAE 2.80, Spearman 0.69 | w = 0.9: MAE 2.80, Spearman 0.73 |
| Unseen fault | MAE 1.86, Spearman 0.71 | w = 0.6: MAE 2.09, Spearman 0.79 |

The blend closes the ranking gap to the trees at little MAE cost, and ARC keeps its top-1 lead.

**T13: ARC given the true faulty service.** No gain anywhere: MAE 1.78→1.75, 2.80→2.90, 1.86→1.92. On pod-hang
in the unseen system it is worse (5.24→6.04). The state before the action already shows where the fault is.
Pairing ARC with root-cause analysis adds explanation, not accuracy. The pod-hang weakness is a symptom-input
problem, not a localisation problem.

**B8 LLM (GPT-4o Mini, 3 solved examples of the same action type, JSON answer).**

| Setting | B8 MAE / Spearman / top-1 | ARC MAE / Spearman / top-1 |
|---|---|---|
| Batch 1, 133 episodes | 6.39 / 0.44 / 30 % | 1.78 / 0.70 / 81 % |
| Unseen system, 150 episodes | 6.69 / 0.28 / 23 % | 2.80 / 0.69 / 61 % |

- B8 is worse than the B3 rule on every measure.
- It takes 3.6 s per decision against ARC's 4 ms, and costs $0.001 per episode ($0.33 in total).
- Caveat: a small, cheap model; a stronger one may do better, but it would be slower and cost more.

### 10g. Call-failure inputs, three-way gate, held-out faults (2026-10-23)

**Call-failure inputs (`--calls`).** Two new inputs per service, taken from the call graph already in the dataset:
the rps-weighted failed share of the calls INTO the service and of the calls it MAKES. Intuition: a hung pod looks
healthy on its own (it is alive, not restarting, using no CPU); the symptom is on the calls into it.

| Setting (3 seeds) | Without the new inputs | With them |
|---|---|---|
| Batch 1: MAE / Spearman / F1 | 1.83 / 0.68 / 0.74 | 1.83 / 0.69 / 0.76 |
| Unseen system: MAE / Spearman | 2.90 / 0.65 | 2.86 / 0.65 |
| Unseen system, pod-hang (last seed): MAE / top-1 | 8.23 / 0.28 | **6.51 / 0.37** |
| Unseen fault: MAE | 1.94 | 1.95 |

They help the weakest case (pod-hang) and are neutral elsewhere, so they are kept on in the ARC tool. pod-hang is
still the worst fault: the inputs are only a 1-minute average before the action, so a richer time profile is
still to do.

**Three-way gate (harness/gate3.py).** BLOCK if the 5-seed mean predicted net effect is >= T; otherwise ASK a
human if the seeds' spread is >= S; otherwise ALLOW. At T = 20:

| Setting | Harmful caught, block only → block + ask | Safe wrongly blocked | Human asked |
|---|---|---|---|
| Batch 1 | 97.4 % → 97.4 % | 2.1 % | 10 % |
| Unseen system | 88.3 % → 91.9 % | 6.6 % | 14 % |
| Unseen fault | 89.7 % → 89.7 % | 2.1 % | 4 % |

- The 5-seed mean alone makes a strong gate.
- ASK adds little: the misses are confident ones, where all seeds agree it is safe and are all wrong.
- Disagreement flags bad *damage* predictions (10f), but it is a weak extra gate layer. Report the gate as
  block / allow, with ask as an option.

**Held-out faults (commit 8a14ade, lab smoke test pending).** Four faults never trained on, chosen by the design
weak point they hit:

| Fault | What it does | Looks like a trained fault? |
|---|---|---|
| http-error (HTTPChaos 500) | The target fails fast | Yes, familiar-looking |
| call-cut | One dependency link is lost (partition on the callee side) | Yes, familiar-looking |
| shared-db-slow | Every service's database replies are delayed | No, new shape |
| load-surge | An extra load generator adds traffic; nothing is broken | No, new shape |

- Memory pressure was dropped: Chaos Mesh stress runs outside the container on kind + cgroup v2 (same as
  cpu-stress).
- Clock skew on auth was dropped: the load generator logs in only every 20 minutes, so it would not show within an
  episode.
- Plan: 168 episodes at the wide2 load (8 req/s, calibration-wide-8). ARC is trained without them, then tested
  with no examples and with a few blocks added; it checks whether the "not sure" signal fires on the new shapes.

### 10h. Repeatability test, noise ceiling, and ARC against it (2026-10-25)

Data: reptest (20 episodes = 4 recipes x 5 runs, 8 req/s, clean database after the reset fix; archive sha256
3dfdcf7d..., verified). harness/noise_ceiling.py.

**Repeat spread of the net effect** (sum of y_mean over scored services, points):

| Recipe | Runs | Mean | CV |
|---|---|---|---|
| R2 delay on seat + restart seat | 260, 241, 110, 254, 225 | 218 | 28 % |
| R3 loss on travel + drain travel | 35, 33, 44, 70, 53 | 47 | 32 % |
| R4 no fault + rollout-restart order | 116, 115, 74, 72, 78 | 91 | 25 % |
| R1 no fault + noop | -9, 4, 2, 39, -16 | 4 | not meaningful |

**Noise ceiling** (leave-one-out: predict a run by the mean of the other four, per service): y_peak 3.77 points,
y_mean 2.01 points (365 service-replicates). The estimate is slightly high (the mean of four runs is itself noisy;
about 10 %), so the true floor is probably about 3.4 for y_peak.

**ARC on the same 20 episodes (y_peak MAE, 5 seeds):** ARC trained on wide1 5.41 (+-0.77), trained on batch 1 5.51.
Baselines: trees 9.3 / 9.0, rule B3 9.0 / 8.7, action mean 13.6 / 15.9.
ARC is about 1.7 points above the noise ceiling, the trees about 5.5 points above it, the action mean about 10 above it.
This set (high-damage actions) is much harder than the usual test split (ARC 1.8-2.9), so the numbers are not comparable
across sets, only against the ceiling of the same set.

**Findings.**
- y_peak is unreliable for sparse services: in R4 inside-payment's y_peak has a spread of 53 points between identical
  runs. A maximum over six noisy 30 s blocks is dominated by chance when traffic is low (winner's curse).
  Net effect and y_mean are the reliable targets; y_peak needs a minimum-traffic rule when it is reported.
- R4 (rollout-restart on order) splits into two groups (116, 115 vs 74, 72, 78): something that varies between runs
  moves the outcome by about 40 points. Unexplained; to investigate in the raw episodes (pod placement, timing of the
  restart against the load generator's order cycle).
- A real action repeats to within 25-32 %: no predictor can be more accurate than that on a single incident.

Also logged (lab, 24-25 Oct): cancel-flow drift in wide2 (F21): reset-data.sh did not clean assurance and inside_money; the fix
is in commit 092dc5c, plus d523d64 (the drift warning also fires when the B0 median is far BELOW the calibration median).
calibration-wide-8 was fitted on a drifted database (cancel 76 ms against about 20 ms clean) and is to be refitted before held.
wide2: relative labels of the second half are inflated for cancel and its path; use the fixed-bar labels on all of it, and the
relative labels on the first half only. wide1 was affected little (cancel 25 -> 56 ms, below the 100 ms floor of the threshold).

### 10i. Repeatability test relabelled with the clean calibration (2026-10-25)

calibration-wide-8c (fitted on the clean database, 20 episodes ep_cal_arc_061-080, z 1.6, held-out false harm 0/176).
Compared with the drifted calibration-wide-8, 10 of 65 operation thresholds differ (booking: gateway / preserve / assurance
100 -> 250 ms, client book / book2 100 -> 174 / 177 ms; cancel: 250 -> 100 ms). Of the 65 thresholds in 8c, 58 are at 100 ms,
the floor of max(100 ms, q99): the "machine-relative" bar is mostly the floor in practice. Thresholds are histogram bucket
boundaries (10, 25, 50, 100, 250 ms), so a q99 near a boundary flips the threshold.

| Reptest, relabelled | Old labels (drifted calibration) | Clean calibration |
|---|---|---|
| Noise ceiling y_peak / y_mean (points) | 3.77 / 2.01 | 3.08 / 1.49 |
| R1 (no fault, noop) net effect spread (sd) | 21.4 | 6.0 |
| R2 net effect mean (CV) | 218 (28 %) | 283 (27 %) |
| R3 net effect mean (CV) | 47 (32 %) | 74 (12 %) |
| R4 net effect mean (CV) | 91 (25 %) | 94 (23 %) |

- The drifted calibration added noise (the noop recipe spread fell from 21 to 6 points).
- Net effect for real actions moved by 3-60 % with a different calibration: labels are sensitive to the threshold choice.
  A label-sensitivity analysis (relabel under several calibrations and the fixed bars; do the model comparisons and the
  action rankings stay the same?) is to be done and reported.

**ARC against the clean-label noise ceiling** (trained on wide1 with its own labels, tested on the 20 repeat episodes
labelled with 8c; y_peak MAE, 5 seeds): ARC 5.19 (+-0.87), noise ceiling 3.08, rule B3 9.44, trees B6 10.32, action mean 14.60.
ARC is about 2.1 points above the ceiling; the trees 7.2; the action mean 11.5. Note that 7 operation thresholds differ between the labels ARC
was trained on and the test labels (booking 100 -> 250 / 174 ms), and ARC's error did not degrade (5.41 -> 5.19).

### 10j. Label-sensitivity sweep: do the conclusions depend on the latency bar? (2026-10-25)

Method: every episode of batch 1 (701) and wide1 (500) relabelled with a request counted bad if it failed or took longer than a
FIXED bar of 50, 100, 250, 500 or 1000 ms (same windows, blocks and smoothing as labels_v2.py; input `bad_before` recomputed
under the same bar; harness/label_sweep.py, label_sweep_build.py). Check: the 100 ms bar reproduces the real labels of batch 1 and
wide1 (correlation 1.00, same mean) because the calibrated per-operation bars were at the 100 ms floor there. Correlation of
y_mean with the real labels: 0.80 (50 ms), 0.97 (250), 0.96 (500), 0.95 (1000). Single split (block % 5), 3 seeds, y_peak, latency inputs off, call-failure inputs on.

In-system (batch 1 test, 133 episodes): MAE in points, Spearman, top-1 hit.

| Bar | ARC | Trees B6 | Rule B3 | Action mean B1 | Zero B0 | ARC / zero |
|---|---|---|---|---|---|---|
| 50 | 1.44 / .710 / .73 | 3.10 / .726 / .48 | 3.07 / .493 / .42 | 6.52 | 4.63 | 0.31 |
| 100 (= real) | 1.83 / .690 / .77 | 3.96 / .742 / .39 | 3.82 / .616 / .35 | 9.03 | 6.39 | 0.29 |
| 250 | 1.66 / .681 / .83 | 4.11 / .794 / .39 | 3.64 / .063 / .27 | 9.38 | 6.54 | 0.25 |
| 500 | 1.46 / .690 / .79 | 4.36 / .806 / .27 | 3.39 / .114 / .35 | 9.51 | 6.57 | 0.22 |
| 1000 | 1.36 / .705 / .75 | 4.18 / .767 / .35 | 3.25 / .209 / .42 | 9.51 | 6.47 | 0.21 |

Unseen system (train batch 1, test wide1, 500 episodes): ARC MAE 2.57 / 2.86 / 2.58 / 2.49 / 2.52 against trees 3.36 / 3.91 / 3.92 / 4.26 / 3.95,
rule 3.66 / 4.17 / 3.94 / 3.88 / 3.85, action mean 6.62 / 8.72 / 8.81 / 8.94 / 8.93 (bars 50 .. 1000). ARC / zero 0.56 / 0.50 / 0.47 / 0.46 / 0.47.
Yes/no 'harmed' F1 in-system, ARC against the prior-work classifier B7: 0.72 / 0.68, 0.76 / 0.73, 0.79 / 0.75, 0.85 / 0.81, 0.88 / 0.84.
Action ranking (pairs ordered right, ARC against action mean): 77.4 / 75.5, 78.8 / 75.3, 85.2 / 78.1, 86.5 / 83.2, 94.0 / 87.7.
Gate at 20 points: ARC catches 92-100 % of harmful and wrongly blocks 2-6 % of safe; the action-mean rule catches 97-100 % and wrongly blocks 19-22 %, at every bar.

**Robust across bars:** (1) ARC has the lowest error at every bar, 2-3x below the trees and the rule in-system and 1.3-1.5x on the unseen system;
as a fraction of the zero predictor's error it removes 69-79 % (in-system) and 44-54 % (unseen). (2) ARC's top-1 hit is the highest everywhere except tied at
bar 50 on the unseen system (0.48 against 0.38). (3) ARC's yes/no F1 is above the prior-work classifier at every bar. (4) The gate's false-block rate stays at 2-6 %.
(5) The trees rank services better (Spearman .73-.81 against .61-.71) at every bar: a stable weakness, addressed by the 90/10 blend.
**Not robust:** (6) The lead in action ranking is small and varies with the bar (+1.9 to +7.1 points on one split, no interval). (7) Hard pairs (training means within
5 points) number only 10-34 on one split, and at bar 250 ARC is below the action-mean rule (32-41 % against 82 %): the claim "ARC wins hard pairs" is not established across bars
(5-fold results per bar are being computed). (8) The rule B3's Spearman collapses at coarse bars (0.06-0.21): its fitted line on `bad_before` carries little at those bars.
(9) Absolute errors are not comparable across bars (the zero predictor's MAE changes from 4.6 to 6.6); compare ratios.
At 1000 ms the remaining damage is mostly outright failures (8.5 % of scored services still show >= 10 points against 10.2 % with the real labels), so the 1000 ms bar
tests failure prediction, not slowdown prediction.

### 10k. Action ranking and hard pairs across the latency bars, 5-fold (2026-10-26)

Batch 1, 5-fold by block, one seed per fold, pairs pooled over the folds (same fault type and target, different actions;
ordering of the observed net effect, ties under 2 points skipped).

| Bar (ms) | Pairs | ARC right | Action-mean right | Lead | Hard pairs | ARC | Action-mean |
|---|---|---|---|---|---|---|---|
| 50 | 2,079 | 83.9 % | 75.0 % | +9.0 | 244 | 69.3 % | 47.5 % |
| 100 (real labels) | 1,943 | 86.2 % | 80.2 % | +5.9 | 100 | 67.0 % | 51.0 % |
| 250 | 1,797 | 90.8 % | 84.7 % | +6.0 | 91 | 46.2 % | 65.9 % |
| 500 | 1,690 | 94.2 % | 88.9 % | +5.2 | 45* | 62.2 % | 53.3 % |
| 1000 | 1,600 | 96.0 % | 90.6 % | +5.4 | 51 | 43.1 % | 45.1 % |

(*hard pairs at 500 ms: from the first run, whose fold 4 had not finished: 4 of 5 folds.)
- Robust: ARC orders pairs of actions better than the action-mean rule at every bar, by 5.2 to 9.0 points on 1,600-2,100 pairs.
- Not robust: hard pairs (those where the two action types have similar training means). ARC wins at 50, 100 and 500 ms, loses at 250 ms (46 % against 66 %) and ties at
  1000 ms (43 % against 45 %). The paper must not claim superiority on hard pairs; report the table.
- Accuracy rises with the bar for both methods because the coarser the bar, the more the outcome is decided by whether a restart/drain happens at all.

### 10l. Higher load (T5): trained at 4 req/s, tested at 8 req/s on wide2 (2026-10-26)

ARC (3 seeds, call-failure inputs, latency off) trained on wide1 (4 req/s), tested on wide2 (8 req/s). The cancel-flow drift (F21) makes the
relative labels of the second half of wide2 unreliable, so two tests: the first half (blocks 1-24, 168 episodes, calibrated bar) and all of wide2
under the fixed 1000 ms bar (301 episodes).

| Test | ARC error / Spearman / top-1 | Trees | Role rule | Dependency map | Runbook average | No damage |
|---|---|---|---|---|---|---|
| wide2 first half, calibrated bar | 2.78 / .751 / .50 | 4.11 | 4.46 | 5.88 | 7.82 | 6.15 |
| all wide2, 1 s bar | 2.12 / .744 / .46 | 4.38 | 4.17 | 5.79 | 7.47 | 5.56 |

ARC's error is 32-52 % below the best baseline at double the load, and its ranking of services (Spearman .74-.75) is above the trees' (.69) here.
Yes/no F1: 0.70 and 0.80. The deck (docs/ppt, not in the repo) slide "Results: generalisation" reads these numbers directly from the test log.

## 10m. Second application: Online Boutique (27 Oct 2026)

Why: the main weakness of v1.0 is one system. A second application gives a cross-application result in the paper and in v1.1 of the dataset.

- Setup (`boutique/`): kind cluster `boutique` next to Train Ticket, Online Boutique v0.10.1 (11 services + Redis), same telemetry (OTel spanmetrics + servicegraph at 5 s, kube-state-metrics, cAdvisor), Chaos Mesh 2.6.3. Open-loop load generator `boutique/loadgen_boutique.py` (reuses the Train Ticket engine): browse, home, currency, add, cart, checkout.
- Telemetry check (lab, 27 Oct): 7 of 10 services emit server spans. adservice, cartservice and shippingservice (v0.10.1) emit none; no later release (up to v0.10.7) is documented to fix this. Decision: stay with Boutique; name the three from their callers' client spans (servicegraph `virtual_node_peer_attributes`) and derive their labels from the edge into them (request count, failures, caller-side latency; threshold = the 100 ms floor; bad = max(slow, failed)). Recorded per episode in `edge_counters.csv.gz`. This is the caller's view, not the service's own; to be stated in the paper.
- Harness port: `ARC_APP=boutique` (default trainticket). Boutique's drain action is a Chaos Mesh partition between the target and the other pods (no service registry exists to disable an instance in). Faults used: none, pod-kill, pod-hang, network delay, packet loss, CPU squeeze (no database fault: the services are stateless apart from Redis).
- Smoke test (5 episodes, lab): all ok. drain: 620 of 755 requests failed in M, frontend HARM. restart-pod, rollout-restart, scale-up and cpu-bump: no label-visible damage. restart-pod does cause a ~10 s error burst (7 of 30 requests in the 10 s after the action, 0 of 37 before) that the 180 s label window averages to about 0.5 %, far below the 5 to 10 point detection limit; the raw requests keep it.
- Bugs found by the smoke test and the first calibration: (1) both applications shared one calibration folder (labels used Train Ticket's thresholds); Boutique now has its own. (2) `run_campaign.ensure_load` started the Train Ticket load generator for Boutique, so the first calibration (20 episodes) ran at the episode's own 2 req/s instead of 8; kept as `calibration-boutique-2rps`, repeated at 8 req/s. (3) With 4 req/s, checkout/payment/email had under 30 requests per window ("inconclusive"); load raised to 8 req/s and checkout weight to 20 %.
- Thresholds: every calibrated T is the 100 ms floor (healthy latencies are about 10 ms), held-out false harm 0/42.
- Regression: the label change was checked on 6 held-out Train Ticket episodes: identical output before and after.
