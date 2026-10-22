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
