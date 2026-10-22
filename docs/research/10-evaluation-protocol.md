# 10 — Evaluation protocol (what is tested, against what, on which data)

Written 2026-10-22. Each claim in the paper maps to one row below. "Planned before results" vs "added after
earlier results" is stated per test, as it must be in the paper.

## 1. What ARC does (and does not do)

ARC answers "if I apply action X now, what happens to every service?". It does NOT find the root cause
(where a fault started); root-cause analysis (RCA, e.g. the 15 methods of RCAEval, arXiv:2412.17015) is a
complementary earlier step. ARC needs only the current system state and a candidate action; it is never
given the fault, and half the actions in the data target a service other than the faulty one.

| ARC job | Our method (harness/) |
|---|---|
| J1 per-service damage after the action | `train_gnn.py` (action-conditioned GNN) |
| J2 time course of every service (15 s steps, 3 min) | `dyn_linear.py` (readable), `dyn_gnn.py` (accurate) |
| J3 explainable blast radius: which services, order, path, kind of damage | `blast_radius.py` (on measured, and later on predicted, trajectories) |
| J4 choose the least harmful action | `action_rank.py` |
| J5 damage control: block a harmful action | gate on J1 / J4 predictions (to build) |

## 2. Data and splits

| Set | Episodes | Use |
|---|---|---|
| Batch 1 (main, main2): 20 services, 4 req/s | 701 | training; test split = every 5th block (133 episodes) |
| Batch 2 (wide1): 25 services, new user flows, 4 req/s | 500 | unseen-system test (never trained on) |
| wide1db: db-delay fault, 25 services | 126 | unseen-fault test (fault never trained on) |
| wide2: 25 services, 8 req/s | ~300 (expected 25 Oct) | unseen-load test |
| Laptop pilot: 20 services, 2 req/s, other machine | 89 | optional cross-machine check |
Validation for early stopping: the last 15 % of training blocks. Splits are by block, so episodes of one
block (same fault condition, randomised actions) never appear on both sides.

## 3. Baselines

| Id | Baseline | Represents |
|---|---|---|
| B0 | no damage | null model |
| B1 | mean damage of the action type | knowing only the action |
| B2 | mean by (action, role in the call graph) | topology only |
| B3 | B2 + the service's own badness before the action | the strongest simple rule |
| B4 | graph diffusion from the action target (decay per hop) | propagation / random-walk methods of the RCA literature |
| B5 | dependency-map impact: every caller within k hops is at risk | commercial service maps (Datadog, Dynatrace) |
| B6 | gradient-boosted trees on per-service features, no graph | standard machine learning |
| B7 | yes/no harm classifier per service | the closest prior work (arXiv:2607.20005; no public code found, reproduced in kind) |
| B8 | LLM given graph, state and action | how AI agents judge today (needs an API key; optional) |
| P/R | "nothing changes" / "everything recovers at once" | time-course baselines for J2 |
| AM | action-mean ranking | for J4 |

## 4. Tests

| Id | Test | Held out | Jobs | Metrics | Planned |
|---|---|---|---|---|---|
| T1 | same system, new episodes | batch 1 test blocks | J1-J4 | MAE (points), Spearman per episode, top-1 worst-hit; step MAE, peak error; pair accuracy | before |
| T2 | unseen system | all of batch 2 | J1-J4 | as T1 | before |
| T3 | unseen fault: pod-hang | batch 2 pod-hang episodes | J1, J2 | as T1, per fault type | after (seen in T2) |
| T4 | unseen fault: db-delay | wide1db | J1, J2, J4 | as T1 | after |
| T5 | unseen load (8 req/s) | wide2 | J1, J2, J4 | as T1 | after |
| T6 | adaptation | top-up of 7 / 14 / 28 batch-2 blocks | J1 | as T1 | before |
| T7 | ablation | inputs removed one group at a time | J1 | as T1 | before |
| T8 | action ranking, all pairs | same fault type and target, different action | J4 | share of pairs ordered right | after |
| T9 | action ranking, hard pairs | pairs whose action types have similar mean effect | J4 | as T8 | after |
| T10 | statistics | — | all | 95 % bootstrap intervals over test episodes; paired tests ARC vs best baseline | before |
| T11 | damage-control gate | — | J5 | harmful actions caught vs safe ones wrongly blocked, at several thresholds | after |
| T12 | predicted vs measured chain | — | J3 | precision / recall of hit services, rank agreement of onset order | after |
| T13 | value of root-cause information (upper bound) | ARC given the true faulty service | J1, J4 | gain over T1/T2 | after |

## 5. Reporting rules

- Every number with the dataset, the test, the number of episodes / services / pairs, and seeds (3).
- Which "bad" bar: machine-relative (default) or fixed 1 s; say it each time.
- Services with fewer than 30 requests before or after the action are excluded from per-service scores.
- Saturated episodes (users >= 80 % bad before the action) are kept and reported separately where it matters.
- Prediction cost on a laptop CPU, per candidate action and for all six.
