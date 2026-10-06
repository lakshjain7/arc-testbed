# ARC testbed

**ARC** predicts the damage of a remediation action *before* it is taken: given a live incident in a
microservice system and a candidate action (restart, scale up, drain, ...), how much does each
service get worse, and for how long?

This repository is the machine that produces the training data. It

1. builds a Kubernetes cluster running the Train Ticket benchmark (20 core services, or all 45),
2. keeps realistic user traffic flowing (search, book, pay, list orders),
3. runs **episodes**: break something on purpose, wait, apply one action, record everything,
4. turns each episode into labels: per-service damage caused by the action.

One episode = one training example = `(system state graph, action, per-service damage)`.

**New machine? Follow [docs/LAB-SETUP.md](docs/LAB-SETUP.md) from top to bottom.**

## The six commands

```bash
bash setup/preflight.sh                  # can this machine run it? checks only, changes nothing
bash setup/install-tools.sh              # once per machine: Docker, kind, kubectl, helm, tmux
bash setup/setup-cluster.sh              # once per cluster: ~1-2 h, mostly downloads
bash run/start-campaign.sh calibrate     # 20 quiet episodes -> what "normal" looks like (~3.5 h)
bash run/start-campaign.sh campaign 700  # the dataset; resumable; runs in tmux (~5 days)
bash run/status.sh                       # progress at any time
```

A second cluster on the same machine is the same commands with a prefix:
`ARC_CLUSTER=arc2 ARC_INDEX=1 bash setup/setup-cluster.sh`, and so on. It gets its own ports, its own
data folder and a different random plan.

## What an episode is

```
health gate -> reset database -> steady gate
  B0   120 s   healthy baseline
  fault        (delay / packet loss / CPU squeeze / pod kill / none) on one service
  wait 60-300 s
  B1   last 60 s before the action = "the incident as the operator sees it"
  ACTION       (noop / restart-pod / rollout-restart / scale-up / cpu-bump / drain) on one service
  M    180 s   what happened because of the action
  remove fault, undo action, export, label
```

About 10 minutes each. Faults and actions are checked after they are applied; an episode whose fault
or action did not really happen is marked `discarded`, never silently kept.

## Where the data is

```
~/arc-data/                      (ARC_DATA_ROOT)
  arc/raw/<episode>/             one folder per episode  <- THE DATASET
      meta.json                  what was done, when, whether it is usable
      services.csv.gz            per service, every 5 s: request rate, errors, latency, CPU, memory
      edges.csv.gz               per caller->callee edge, every 5 s: rate, failed rate (the graph)
      counters.csv.gz            raw per-service counters every 5 s
      op_counters.csv.gz         raw per-operation request counters every 5 s (labels are computed from these)
      client.csv.gz              every request a simulated user made, and what they got
      events.json                Kubernetes events during the episode
      labels_v2.json             per-service damage: y_mean, y_peak, y_excess, t_recover, verdict
  arc/plans/main.json            the plan (fixed by a seed before anything ran)
  arc/logs/                      runner and setup logs
  calibration/                   thresholds learned from quiet episodes (shared by all clusters)
  index/episodes.csv             one row per episode        } open these two in Excel
  index/service_labels.csv       one row per episode x service }
```

`bash run/sync-data.sh` rebuilds the two spreadsheets and copies everything to `$ARC_BACKUP`.

## Layout

| folder | what |
|---|---|
| `setup/` | install tools, build a cluster (`setup-cluster.sh`, staged and re-runnable) |
| `run/` | start / watch / stop data collection, back up data |
| `harness/` | one episode (`run_episode.py`), many (`run_campaign.py`), export, labels, calibration |
| `loadgen/` | the simulated users |
| `ops/` | health check, recovery after a reboot, cleanup, database and Nacos helpers |
| `viewer/` | live service graph in the browser |
| `analysis/pilot/` | the analysis of the 50-episode laptop pilot (kept for the record) |
| `docs/` | lab setup, runbook (every problem met so far and its fix), measurement spec, research notes |

## Status (2026-10-07)

- Validated on a laptop (WSL2, 17 GB, 20 services): 89 episodes including a 50-episode pilot.
- Pilot result in one line: the yes/no "was this service harmed" label was too coarse and the faults
  too strong; the *size* of the damage separates actions clearly (drain >> restart > rollout-restart >
  scale-up ~ cpu-bump ~ noop). See [docs/research/07-pilot-results.md](docs/research/07-pilot-results.md).
- This repository applies those lessons: milder faults at several levels, magnitude labels first.
- Known limit of the labels: services with little traffic (a few requests per 30 s) have noisy peaks
  (one slow request = +20 points). Always compare an action with the no-op episodes of the same block,
  never with zero. More load (`ARC_RATE`) on the bigger machine shrinks this noise.
- Fixed on 2026-10-07: the simulated "pay" flow used to stop for ~10 minutes at a time (13 of 52 pilot
  episodes had no payment at all, so the two payment services had no data in them).
- Tested on 2026-10-07 on the laptop: `setup/setup-cluster.sh` built a second cluster from nothing in
  71 minutes (all 9 stages, real booking verified); the campaign runner, calibrate mode, clean stop and
  resume ran on real episodes. Not tested: native Ubuntu (only WSL2), `install-tools.sh` on a machine
  with nothing installed, `PROFILE=full`, and two clusters running at the same time.
  Each setup stage can be re-run on its own (`--from`, `--only`).
