---
license: cc-by-4.0
pretty_name: "ARC: per-service damage of remediation actions in microservice systems"
language:
  - en
tags:
  - microservices
  - aiops
  - remediation
  - blast-radius
  - fault-injection
  - observability
  - graph
task_categories:
  - tabular-regression
  - graph-ml
size_categories:
  - 10K<n<100K
---

# ARC dataset v1.1: what a remediation action does to every other service

When a microservice system breaks, an operator (or an automated agent) applies a repair: restart a pod, scale a service up,
drain it from rotation. The repair itself can hurt services that were healthy. This dataset records, for **2,075 controlled
incidents** on two open-source systems (**Train Ticket**: 1,795 episodes; **Online Boutique**: 280 episodes), what each of six repair
actions did to **every service**, with the raw telemetry from before and after, so that a model can learn to predict the damage
*before* the action is taken.

* **Task.** Given the state of every service in the 60 s before an action, the call graph and a candidate action,
  predict for each service the rise in its share of bad requests (a request is bad if it fails or is slower than a
  latency bar) over the 180 s after the action.
* **Systems.** Train Ticket (Zhou et al., IEEE TSE 2021), 20 to 25 Java services; Online Boutique (Google), 11 services and a Redis
  cache. Both on Kubernetes 1.34 (kind), faults injected with Chaos Mesh, traces and metrics through OpenTelemetry and Prometheus
  (5 s resolution), an open-loop load generator at 4 or 8 requests per second. Column `system` in every table tells them apart.
* **Actions.** no-op (control), restart-pod, rollout-restart, scale-up, cpu-bump, drain.
* **Faults.** none, pod-kill, hung pod, network delay, packet loss, CPU squeeze, database delay, call-cut, load surge.
* **Labels.** Per service: `y_mean` (mean rise of the bad-request share), `y_peak` (worst 30 s block), a verdict
  (harm / no_harm / inconclusive / no_data), time to recover. Three latency bars: the calibrated 100 ms bar and fixed
  500 ms and 1 s bars. Everything is recomputable from the raw files.
* **Splits.** Nine evaluation protocols in `splits.csv.gz`: six on Train Ticket (in-system, unseen system, unseen fault, held-out
  faults, higher load, noise ceiling) and three that use both systems (train on Train Ticket and test on Online Boutique, the
  reverse, and in-system Online Boutique).

## Versions

* **v1.0** (Train Ticket only): 1,795 campaign episodes. Its rows are unchanged in v1.1.
* **v1.1** adds Online Boutique (280 usable campaign episodes, 40 healthy calibration episodes, 8 episodes kept but not usable) and the
  columns `system` and `contaminated`. Nothing in v1.0 was edited.

## Contents

| File | What it is |
|---|---|
| `episodes.csv.gz` | one row per episode (2,204: 2,075 campaign + 120 calibration + 1 unusable Train Ticket + 8 Boutique campaign episodes that are kept but not usable): system, fault, action, load, saturation flag, user-level damage |
| `service_labels.csv.gz` | one row per (episode, service): request counts before/after, bad-request share, `y_mean`, `y_peak` at three bars, verdict, recovery |
| `client_flows.csv.gz` | one row per (episode, user flow): what users saw |
| `splits.csv.gz` | the nine official evaluation splits |
| `arc-raw-<part>-v1.0.tar.gz`, `arc-raw-boutique-v1.1.tar.gz` | raw files of every episode of a part (Zenodo record only): per-service time series, call-graph edges, exact request-count and latency-bucket counters, the load generator's own request log, Kubernetes events, labels, metadata, calibration |
| `arc_data.py` | loader (standard library; pandas optional) |
| `SCHEMA.md`, `DATASHEET.md` | column definitions; the datasheet (composition, collection, known issues) |

## Quick start

Needs Python 3 only (no other packages).

```python
import arc_data as arc
episodes = arc.load_episodes()                  # list of dicts, or a pandas DataFrame with pandas=True
labels   = arc.load_service_labels()
split    = arc.load_splits()
train_ids = arc.episode_ids("train_tt_test_boutique", "train")     # Train Ticket episodes
test_ids  = arc.episode_ids("train_tt_test_boutique", "test")      # Online Boutique episodes
boutique  = arc.by_system(labels, "online-boutique")
scored    = arc.scored(boutique)                                    # rows with >= 30 requests before and after
```

Raw files of one episode (after extracting an archive): `services.csv.gz` (rate, errors, p50/p95/p99, CPU, memory,
restarts, ready, per 5 s), `edges.csv.gz` (call graph, caller to callee, rate and failures), `op_counters.csv.gz`
(exact cumulative counts per service, operation and latency bucket), `client.csv.gz` (every request the users sent),
`events.json`, `labels_v2.json`, `meta.json`.

## Known issues (read before using)

The datasheet lists all of them. The ones that change results:

1. **Saturation.** In 389 of 1,795 Train Ticket episodes and 59 of 280 Boutique episodes users were already at least 80% bad before the
   action (flag `saturated_before_action`). Exclude them, or use the 1 s bar, when ranking actions.
2. **Drift in the second half of Train Ticket part wide2.** The cancel flow slowed from 77 to 131 ms because two tables were not cleaned;
   labels of wide2 after block 24 (about 23 Oct 2026 20:00 UTC) are inflated for that flow. Use the 1 s bar or the first half
   of wide2 (blocks 1 to 24, 168 episodes; column `wide2_first_half` in `splits.csv.gz`).
3. **One machine, one copy per service.** Fault levels were dosed on this machine; a level is not a severity.
4. **Short bursts are invisible.** The label averages over 180 s; a burst of a few seconds stays in the raw requests only. On Online
   Boutique a restart lasts about 10 s, so restarts show almost no damage in the label.
5. **Online Boutique specifics.** Three services (ad, cart, shipping) are labelled from the counters of their callers. Five episodes
   (`contaminated` = 1) were affected by a leftover CPU limit and are excluded (`usable` = 0); they were re-run as `ep_rerun_boutique_*`.

## Citation

See `CITATION.cff`. The paper that describes the dataset: Jain, Singh, Choudhary, Kolikipogu, "ARC: A Dataset of Per-Service
Damage Caused by Automated Remediation Actions in Microservice Systems" (in preparation for the MSR 2027 Data and Tool Showcase).

## Licence

Data: CC BY 4.0 (`LICENSE-DATA.md`). Code: MIT (`LICENSE-CODE.txt`; the code is at https://github.com/lakshjain7/arc-testbed).
