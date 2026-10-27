# Datasheet: ARC dataset v1.0

Following "Datasheets for Datasets" (Gebru et al.). Numbers come from the released tables and the project's decision log
(`docs/research/09-decision-log.md`) and findings (`docs/research/08-lab-machine-findings.md`) in the code repository.

## 1. Motivation

**Why was it created?** Autonomous remediation tools decide whether to act by how confident they are in a root cause.
Nothing predicts what the chosen action will do to the services around the target. No public dataset we could find records, per
service, how much worse a service gets after a repair (the closest, Dai et al. 2026, labels each decision as resolved, partial or
false remediation; RCAEval, AnoMod and TrainTicketTrace are root-cause or detection datasets). ARC records that damage.
**Who created it?** Laksh Jain, Abhishek Kumar Singh, Yogesh Choudhary, under Dr. Ramakrishna Kolikipogu, Department of
Information Technology, Chaitanya Bharathi Institute of Technology (Autonomous), Hyderabad. **Funding:** none external.

## 2. Composition

**What is an instance?** One episode: a controlled incident on a running system. A fault is injected, 60 to 300 s later one
remediation action is applied, and everything is recorded for 60 s before and 180 s after the action.
**How many?** 1,795 campaign episodes in six parts, plus 80 calibration episodes (healthy, no-op; used only to set latency bars) and
one unusable episode kept for completeness.

| Part | Episodes | System | Load | Faults |
|---|---|---|---|---|
| batch1 | 701 | 20 services | 4 req/s | none, pod-kill, network delay, packet loss, CPU squeeze |
| wide1 | 500 | 25 services | 4 req/s | none, pod-kill, hung pod, network delay, packet loss |
| wide1db | 126 | 25 services | 4 req/s | none, pod-kill, database delay |
| wide2 | 301 | 25 services | 8 req/s | none, pod-kill, hung pod, network delay, packet loss |
| reptest | 20 | 25 services | 8 req/s | 4 recipes repeated 5 times |
| held | 147 | 25 services | 8 req/s | none, pod-kill, call-cut (3 links), load surge (3x, 4x) |

Actions: no-op 512, restart-pod 259, rollout-restart 258, drain 258, scale-up 255, cpu-bump 253. Faults: none 273, packet loss 467,
network delay 434, pod-kill 273, hung pod 119, CPU squeeze 61, database delay 63, call-cut 63, load surge 42.
**Rows.** 37,790 labelled (episode, service) rows in campaign episodes, of which 28,769 are scored (at least 30 requests before and
after the action; below that a share of bad requests is dominated by noise). 4,696,050 individual user requests are recorded.
**Raw data.** About 1.14 GB uncompressed including calibration; 0.96 GB as the released archives.
**Is anything missing?** Four episodes of wide1 were lost when the monitoring system was killed (finding F19); use the index
(`episodes.csv.gz`, column `usable`), not the folder listing.
**Confidentiality / personal data.** None. The "users" are a script using one test account (`fdse_microservice`) of the open-source
Train Ticket application; no real person's data is involved. Host names and user paths were removed from the released JSON files.

## 3. Collection

**How?** One machine (Intel i9-13900, 20 cores, 32 GB), one Kubernetes cluster (kind, v1.34) running Train Ticket, Chaos Mesh 2.6.3 for
faults, OpenTelemetry Collector (span metrics and service graph, 5 s resolution) into Prometheus, cAdvisor and kube-state-metrics for
resources. An open-loop load generator (Poisson arrivals, nine user flows: search, search2, orders, orders2, book, book2, pay, cancel, collect)
keeps the offered load constant even when the system slows down. Between episodes the database is trimmed so the healthy baseline does not
drift. Episodes run one at a time, unattended, from a pre-registered plan of blocks of 7 (one block = one fault condition, one episode
per action, no-op twice).
**When?** 17 to 26 October 2026 (the 89-episode laptop pilot of 29 Sep to 7 Oct is not part of v1.0).
**Labelling.** For each service, the share of bad requests in the 60 s before the action and in the 180 s after it (starting 5 s later) is
compared. A request is bad if it failed or took longer than a bar: the calibrated per-operation bar (healthy 99th percentile, with a
100 ms floor), or a fixed 500 ms or 1 s bar. `y_mean` is the mean rise in points of bad-request share, `y_peak` the worst 30 s block.

## 4. Preprocessing

Raw files are exactly what the exporter wrote, except that the machine's host name and user paths are replaced in the JSON files
(`host` = `lab-machine`). Labels are computed from the raw counters (`harness/labels_v2.py`) and can be recomputed with other bars
(`harness/relabel.py`). Calibration (latency bars) was fitted only on healthy calibration episodes of the same load.

## 5. Uses

**Intended.** Training and testing models that predict per-service damage of a remediation action; ranking and gating actions;
blast-radius explanation; benchmarking against simple baselines (included in the code repository).
**Not suitable for.** Claims about other applications or hardware without testing there (one system, one machine, one copy of each service);
using a fault level as a measure of severity (levels were dosed on this machine); detecting damage shorter than a few tens of seconds
(the label averages over 180 s; the raw requests keep short bursts).

## 6. Known issues

1. **Saturation.** In 389 of 1,795 episodes users were already at least 80% bad before the action (`saturated_before_action`): batch1 109 of 701,
   wide1 91 of 500, wide2 134 of 301 and 54 of the 147 held-out episodes (both call-cuts that reach the configuration service: 21 of 21 each). Hung-pod episodes are always saturated.
2. **Drift in wide2 (findings F21, F22).** Two tables read by the cancel flow were not cleaned; cancel slowed from 77 to 131 ms during wide2.
   Labels of wide2 after block 24 are inflated for that flow; use the 1 s bar or blocks 1 to 24. wide2 was first labelled with a calibration
   fitted on the drifted database; the released labels use the clean calibration of the repeat test.
3. **One copy per service** in every episode; number of copies and the age of the fault are not recorded as inputs.
4. **Fault injection:** HTTP-level injection did not attach (finding F25); a fault slowing every database at once was a cliff with no usable level and was dropped.
5. **Repeatability (finding F24).** The same incident repeated gives a net effect within 12 to 27% (coefficient of variation) for real actions; `y_peak`
   of services with few requests varies by up to 53 points between identical runs.
6. **Drain** removes the target from the registry, so services that only the drained service called receive no requests and drop out of scoring.
7. **Pod-kill** often self-recovers before the action, which makes later actions look harmless.

## 7. Distribution

Zenodo (archive with DOI; raw archives, tables, documents) and Hugging Face (tables, documents, loader). Licence: CC BY 4.0 for the data,
MIT for the code. Version 1.0; later versions will add a second application (Online Boutique) as v1.1 without changing v1.0.

## 8. Maintenance

Maintainer: Laksh Jain (https://github.com/lakshjain7). Issues: https://github.com/lakshjain7/arc-testbed/issues. Corrections will be released
as new versions; v1.0 is never edited in place.
