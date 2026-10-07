# ARC testbed: context for Claude

This file is the hand-over from the long working session in which this repository was built
(Laksh's laptop, 21 Sep - 7 Oct 2026). Read it before doing anything; it replaces that chat.

## What the project is

**ARC** predicts the damage of a remediation action before it is taken. Input: the state of a
microservice system during an incident (a graph of services with metrics) and a candidate action
(restart, scale up, drain ...). Output: per service, how much worse it gets and for how long.

This repository produces the training data: it runs Train Ticket on Kubernetes (kind), keeps simulated
users active, injects a fault, applies one randomly assigned action, records everything, and labels
the per-service damage. One episode = one training example. After the data: train an
action-conditioned graph neural network and compare it with simple baselines (hop distance, diffusion).

Team: three students; Laksh (GitHub `lakshjain7`) owns the cluster and the harness. The lab machine
was arranged through their faculty guide.

## Where things stand (7 Oct 2026)

- Laptop pilot done: 89 episodes, of which a 50-episode pre-registered pilot. Write-up:
  `docs/research/07-pilot-results.md`. One line: the yes/no "service harmed" label was too coarse and
  the faults too strong (18 of 46 episodes were fully broken before the action); the SIZE of the
  damage separates actions clearly (drain >> restart-pod > rollout-restart > scale-up ~ cpu-bump ~ noop),
  and collateral damage lands almost only on upstream callers of the action target.
- This repository is the portable version for a lab machine (Intel i9, 20 cores, 32 GB, A4000,
  reached by remote desktop; OS and admin rights were still unknown on 7 Oct).
- Tested on the laptop (Windows 11 + WSL2 + Docker Desktop) on 6-7 Oct: `setup/setup-cluster.sh`
  built a cluster from nothing in 71 min; `run/start-campaign.sh` calibrate / campaign / stop;
  `harness/dose_check.py`; both preflight scripts; `ops/recover-after-restart.sh`.
- NOT tested: native Ubuntu, `setup/install-tools.sh` on a bare machine, `PROFILE=full` (all 45
  services), two clusters at once, the resume path all the way into the next episode, the Nacos
  wait fix in `stage_tame` (written after the test run that exposed it), delay 75 ms.
- Next step: follow `docs/LAB-SETUP.md` on the lab machine: preflight -> install -> cluster ->
  step test -> dose check -> calibrate (20 episodes) -> campaign (700 episodes per cluster, ~5 days).

## Decisions already made (do not re-open without a reason)

- ARC is a damage predictor that agents call, plus a dataset. It is not an agent and not a gym.
  Closest prior work: arXiv:2607.20005 (binary blast radius inside offline RL). The team does NOT
  claim "first to predict blast radius", and does not sell random action assignment or the label
  formula as the contribution; uniqueness has to come from results.
- Labels: per-operation "bad request" ratio (failed, or slower than that operation's healthy q99),
  action window M compared with the 60 s before the action. Primary labels are sizes (`y_mean`,
  `y_peak`, `y_excess`, `t_recover`); the harm / no_harm / inconclusive verdict is secondary.
  Spec: `docs/MEASUREMENT-SPEC.md`, code: `harness/labels_v2.py`, thresholds from
  `harness/calibrate_v2.py` on no-fault no-op episodes.
- Faults: none, pod-kill, network-delay, net-loss, cpu-squeeze (blackhole only with `--hard`).
  Actions: noop, restart-pod, rollout-restart, scale-up, cpu-bump, drain. Six target services.
  Every one was verified by a smoke test. Two earlier candidates failed silently and were replaced
  (Chaos Mesh StressChaos leaks to the whole host on kind + cgroup v2; a NetworkPolicy "quarantine"
  blocked nothing because of keep-alive connections). Any new fault or action needs a smoke test
  that proves it does what it claims before it goes into a plan.
- Core profile (20 services) for the first dataset; the simulated users only search, book, pay and
  list orders, so the other 25 services would get no traffic.
- Open question put to Laksh on 7 Oct, unanswered: new fault/action types in the first run, or as a
  second batch (recommended: second batch).

## Things that will bite you (all learned the hard way; details in docs/RUNBOOK.md)

- Never start all Java services at once (Nacos registration crash-loops). Use batches:
  `ops/recover-after-restart.sh` after any Docker or machine restart, then `loadgen/warmup.sh`.
- Nacos runs as ONE standalone copy on purpose (3 copies went inconsistent). MySQL has 3 copies;
  writes must go to the leader (`ops/mysql-leader.sh`); `max_connections=500` is lost on restart
  (the recovery script re-applies it).
- CPU limit per service is 2 cores (the chart's 500m made 1 request/s time out). In-place pod resize
  needs the default strategic-merge patch, not `--type=merge`.
- A drained service is hidden from Nacos' list API: re-enable by address (`ops/nacos-set-enabled.sh`).
- CPU squeeze is a cliff (3x average use = no effect, 1.5x = 8-20 % bad, 1x = 70 %) and noisy.
  Fault strength depends on machine and load: measure with `harness/dose_check.py`, pass the levels
  to `harness/run_campaign.py plan --delay .. --loss .. --squeeze ..`.
- Services with few requests have noisy peaks (one slow request in a 30 s block = +20 points).
  Compare with the no-op episodes of the same block, never with zero.
- Docker Desktop on Windows after sleep: click Quit, NEVER "Reset to factory defaults" (deletes the
  cluster); `wsl --shutdown`; if it still fails, rename (not delete) `%LOCALAPPDATA%\Docker\run`.
- Prometheus and Grafana live in namespace `kube-system` (NodePorts 30003 / 31000), not `monitoring`.
- From Git Bash on Windows, `wsl ... bash -c '...$VAR...'` gets mangled: write a script file and run it.
- Stop a run with `run/start-campaign.sh stop` (it undoes the fault). After a hard kill: `ops/cleanup.sh`.

## Where data is

- Lab machine: `~/arc-data/<cluster>/raw/<episode>/` (the dataset), spreadsheets in `~/arc-data/index/`.
- Laptop pilot (89 episodes): Laksh's `OneDrive\ARC-backup\` (`episodes.csv`, `service_labels.csv`,
  raw folders under `arc-wsl\data\raw\`), and `~/arc/data/raw` in the laptop's Ubuntu.
- Never edit raw episode files. Labels are recomputed from them (`harness/relabel.py`).

## How to work with this team

- Explain in plain language, briefly, starting from the big picture; they are students and several
  of them were not in the original chat. Say what a thing is for before how it works.
- Be decisive: give one recommendation, not a menu.
- Verify before saying something works, and say plainly what was tested and what was not.
- Do not commit data, the 25 MB agent jar, or secrets. The repository is PUBLIC (since 7 Oct 2026):
  nothing personal, no passwords or tokens, no machine addresses in any commit.
