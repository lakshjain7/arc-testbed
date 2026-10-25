# 08 — Lab machine: what we hit, with numbers (running log)

Started 2026-10-10. One entry per challenge met while moving ARC from the laptop to the lab machine.
Each entry has the same four parts so it can be lifted into the paper's "threats to validity" and
"lessons" sections: **what happened**, **numbers**, **impact**, **interpretation**. Times are UTC.
**VERIFIED** = measured on the machine. **INFERRED** = our explanation, not separately tested.

Add new entries at the bottom of section 2. Never rewrite an old entry; add a dated correction.

---

## 1. The two machines

| | Laptop (pilot) | Lab machine (batch 1) |
|---|---|---|
| CPU given to WSL | 12 | 18 (of 32 logical, i9-13900) |
| Memory given to WSL | 17 GB | 26 GB (of 32 GB) |
| Ubuntu in WSL2 | (see pilot notes) | 26.04, systemd 259 |
| Docker | Docker Desktop | Docker Desktop 4.94.0, engine 29.8.2 |
| Load | 2 req/s | 4 req/s |
| Episodes | 89 | 700 planned |

Same on both: kind v0.30.0, Kubernetes v1.34.0, 20-service core profile, 6 target services, 6 actions.

---

## 2. Findings

### F1. MySQL crash loop caused by the host's open-files limit

- **What happened.** During `setup-cluster.sh` stage `deploy`, pod `nacosdb-mysql-0` went into
  CrashLoopBackOff and the stage sat on "Waiting for 3 pods to be ready". This never happened on the laptop.
- **Numbers (VERIFIED).** Container `mysql` (percona 5.7.34, memory limit 1 GiB): exit code 137,
  reason OOMKilled, 20 restarts in 28 min, empty log. Open-files limit inside the cluster's containers:
  2,147,483,584. containerd in each kind node: `LimitNOFILE=infinity`. After capping it at 1,048,576
  and recreating the pod: 3/3 Running in 65 s, no further restarts.
- **Impact.** About 35 min of a 77 min build (laptop reference: 71 min with no fault). Without the fix
  the build cannot finish on this host at all.
- **Interpretation (INFERRED).** MySQL 5.7 sizes start-up memory from the open-files limit. The limit
  comes from the host kernel setting `fs.nr_open` (2^31 here) passed through containerd. We did not see
  a MySQL log line, so the causal link rests on the fix working. Lesson for the paper: a benchmark that
  builds on one host can fail on another for reasons outside the benchmark; the host OS version is part
  of the experimental setup and must be reported.
- **Fix.** `setup/setup-cluster.sh`, stage `cluster`, now caps the limit on every node (added
  2026-10-10; the manual equivalent was tested, the scripted version has not yet run on a fresh build).

### F2. Memory decides how many services fit

- **Numbers (VERIFIED).** WSL total 26,047 MB. Free after the 20th service became ready: 11,553 MB.
  Available after warm-up: 10,727 MB. During calibration: about 10,700 MB.
- **Impact.** The other 25 services at about 0.45 GB each need roughly 11 GB: nothing would be left
  for scale-up and rollout-restart, which each start one extra copy. All 45 services do not fit;
  about 30 do (estimate, to be measured).
- **Interpretation.** Running out of memory does not crash the cluster, it makes it swap, and swapping
  appears in the data as damage that no action caused. Memory headroom is a data-quality requirement.

### F3. The machine is far from its load limit

- **Numbers (VERIFIED).** Step test, 180 s per rate: 2, 4 and 6 req/s all 100 % successful. At 6 req/s:
  1,082 of 1,082 requests ok, p95 about 84 ms, 0 % CPU-throttled services, load average about 1.0 on
  18 CPUs. All `ts-*` services together use about 228 millicores at 4 req/s.
- **Decision.** `ARC_RATE=4` (two thirds of the highest tested rate). The ceiling was not found.
- **Interpretation.** Services run at well under 1 % of their 2-core CPU limit. That is much emptier
  than a production system and is the root of F5 and F6.

### F4. Calibration

- **Numbers (VERIFIED).** 20 no-fault no-op episodes in 2 h 20 min (about 7 min each). z = 1.6, fitted
  on 15, checked on 5. Held-out false harm: 0 of 85 service verdicts = 0.0 %.

### F5. The same fault setting hits much harder (or weaker) on this machine

- **Numbers (VERIFIED).** Share of user requests that went bad ("bad" = failed, or slower than twice
  that flow's healthy p95), 60 s measured per level.

  | Fault | Level | Laptop, 2 req/s | Lab, 4 req/s | Lab median latency |
  |---|---|---|---|---|
  | network delay | 25 ms | 31 % | 74.3 % | 34 -> 292 ms |
  | network delay | 75 ms | — | 75.0 % | 35 -> 654 ms |
  | network delay | 100 ms | 73 % | — | |
  | packet loss | 15 % | 12 % | 30.1 % | 37 -> 42 ms |
  | packet loss | 30 % | 59 % | 68.3 % | 36 -> 447 ms |
  | CPU squeeze | 1.5x | 8-20 % | 4.1 % | 36 -> 37 ms |
  | CPU squeeze | 1x | 70 % | 6.1 % | 36 -> 40 ms |

  No request failed in any lab row; all "bad" requests were slow ones.
- **Impact.** With the laptop's levels, both delay levels would saturate and be indistinguishable, and
  both squeeze levels would be nearly fault-free. Roughly half of a 700-episode plan would be wasted.
- **Interpretation (INFERRED).** (a) Healthy requests take about 35 ms here, so "twice the healthy
  time" is a much lower bar than on the laptop: the label definition is itself machine-dependent.
  (b) One search calls the seat service many times, so a per-call delay multiplies (25 ms -> +258 ms).
  (c) Delay saturates near 75 % because search and book are 75 % of the request mix.
- **Lesson.** Fault levels must be chosen by measured effect on each machine, not copied. A fixed
  setting is not a fixed severity.

### F6. CPU squeeze collapsed to one level

- **Numbers (VERIFIED).** Average CPU use at 4 req/s (Prometheus, 5 min): order 89m, seat 17m,
  travel 14m, basic 13m, station 7m, preserve 6m. The squeeze sets limit = level x average use with a
  floor of 25m, so five of six targets get 25m at every level; only order gets distinct limits.
  Both dose-check rows above report `limit 25m`.
- **Impact.** Two of eight fault conditions (a quarter of the plan) would have been the same weak fault.
- **Change.** `harness/run_episode.py`: `SQUEEZE_MIN_M` 25 -> 10 (2026-10-10). 10m is the smallest CPU
  quota Kubernetes enforces. Levels to test: 3x, 2x, 1x. NOT yet verified by a dose check.
- **Interpretation.** A fault defined relative to the service's own use is the right idea, but an
  absolute floor quietly turned it back into a machine-dependent one.

### F7. Disk

- **Numbers (VERIFIED).** Windows drive free: 89 GB after installing Docker, 43 GB with the cluster up.
  Docker volumes of the three kind nodes: 42.8 GB (each node holds its own copy of every image).
  Episode data is small (about 1 MB each).

### F8. Dose check with lower levels (17:13-17:55) — biased by F9, to be repeated

- **Numbers (VERIFIED, but see F9).** 4 req/s, no request failed in any row.

  | Fault | Level | Bad | Median latency | Note |
  |---|---|---|---|---|
  | network delay | 2 ms | 0.0 % | 43 -> 77 ms | too weak |
  | network delay | 4 ms | 17.4 % | 45 -> 87 ms | mild |
  | network delay | 6 ms | 29.8 % | 45 -> 108 ms | |
  | network delay | 10 ms | 33.2 % | 46 -> 155 ms | |
  | packet loss | 8 % | 3.8 % | 42 -> 41 ms | too weak |
  | packet loss | 12 % | 12.2 % | 43 -> 47 ms | mild |
  | packet loss | 22 % | 49.8 % | 44 -> 232 ms | strong |
  | CPU squeeze | 3x (17m) | 10.0 % | 45 -> 47 ms | mild |
  | CPU squeeze | 2x (11m) | 35.1 % | 43 -> 91 ms | |
  | CPU squeeze | 1x (10m) | 43.8 % | 44 -> 117 ms | strong |

- **Interpretation.** The 10m floor works: three distinct limits and a graded response (F6 confirmed
  fixed for station). Useful delay levels on this machine are single-digit milliseconds, 6-20 times
  smaller than the laptop's 25/75 ms.

### F9. The healthy baseline drifted while no episodes were running

- **What happened.** Healthy medians in the second dose check were 43-46 ms, against 34-37 ms in the
  first one 80 minutes earlier.
- **Numbers (VERIFIED).** Median ms per 30 min of the continuous load generator (4 req/s):

  | From (UTC) | search | book | pay | orders |
  |---|---|---|---|---|
  | 12:46 - 15:16 (calibration) | 26-29 | 54-66 | 20-24 | 9-10 |
  | 15:16 | 27 | 67 | 22 | 21 |
  | 16:16 | 32 | 100 | 25 | 50 |
  | 17:16 | 42 | 148 | 32 | 82 |
  | 17:46 | 41 | 156 | 32 | 91 |

  Calibration ended at 15:08. `orders` table at 18:00: 9,140 rows.
- **Cause (VERIFIED in code).** Each episode runs `ops/reset-data.sh`, which deletes the load
  account's orders older than 10 min. `dose_check.py` and an idle load generator do not, so orders
  pile up at about 0.8 per second; the order list returns every order and seat availability counts
  sold tickets. The repo already documents the same effect on the laptop (18 h -> 14,372 rows).
- **Impact.** Both dose checks measured faults against an inflated baseline ("slow" = 2x the current
  healthy p95), so they understate how hard the same level hits on the clean database the campaign
  runs on. The second check is affected more than the first.
- **Lesson.** Any measurement that uses the load generator must control database size the same way
  the episodes do. State drift is a confounder even with no fault and no action.
- **Next.** Repeat the dose check per fault with `reset-data.sh` before each run (F10).

### F10. Dose check on a clean database (18:30-18:59) — the numbers the plan is built on

- **Method.** `ops/reset-data.sh`, wait 150 s, then one fault's levels; repeated per fault. Orders at
  the start of each run: 486, 461, 510. Healthy medians 25-29 ms, the same as during calibration.
- **Numbers (VERIFIED).** No request failed in any row.

  | Fault | Level | Bad, clean DB | Bad, drifted DB (F8) | Median latency (clean) |
  |---|---|---|---|---|
  | network delay | 3 ms | 19.5 % | — | 25 -> 63 ms |
  | network delay | 4 ms | 19.9 % | 17.4 % | 29 -> 77 ms |
  | network delay | 6 ms | 36.4 % | 29.8 % | 28 -> 105 ms |
  | network delay | 10 ms | 70.6 % | 33.2 % | 26 -> 141 ms |
  | network delay | 15 ms | 77.4 % | — | 29 -> 189 ms |
  | packet loss | 12 % | 18.2 % | 12.2 % | 26 -> 34 ms |
  | packet loss | 22 % | 53.3 % | 49.8 % | 26 -> 229 ms |
  | CPU squeeze | 3x (17m) | 31.3 % | 10.0 % | 26 -> 37 ms |
  | CPU squeeze | 1x (10m) | 58.9 % | 43.8 % | 29 -> 208 ms |

- **Impact of F9, now measured.** The same level read up to 2-3 times weaker on the drifted database
  (delay 10 ms: 33 % vs 71 %; squeeze 3x: 10 % vs 31 %). Planning from F8 would have put a saturating
  level into the "strong" slot.
- **Interpretation.** Delay is a cliff on this machine: 6 ms -> 36 %, 10 ms -> 71 %. The whole useful
  range is 3-8 ms.
- **Levels chosen for batch 1.** Delay 4 and 7 ms; loss 12 and 22 %; squeeze 4x and 1x. Delay 7 and
  squeeze 4x were NOT measured: each lies between two measured neighbours (6/10 ms; 25m gave 4-6 % in
  the first check, 17m gave 31 %). Every episode records the severity it actually produced.

### F11. First 251 campaign episodes: two levels saturate under the label definition

- **What happened.** The campaign (plan `main`, delay 4/7 ms, loss 12/22 %, squeeze 4x/1x) started
  2026-10-10 19:22 and ran unattended. Checked 2026-10-12 12:22: 251 of 700 recorded, all `ok`,
  0 discarded, 5 stalled (all in no-fault blocks), 6.1 episodes/hour, load 0.0 % failed.
- **Numbers (VERIFIED).** `saturated_before_action` (users >= 80 % bad in the 60 s before the action):

  | Fault level | Saturated | By fault target (saturated/episodes) |
  |---|---|---|
  | network delay 4 ms | 9 of 28 (32 %) | basic 4/4, order 5/5, preserve 0/6, seat 0/4, station 0/5, travel 0/4 |
  | network delay 7 ms | 29 of 29 (100 %) | every target |
  | packet loss 12 % | 0 of 35 | — |
  | packet loss 22 % | 11 of 35 (31 %) | order 7/7, basic 3/5, travel 1/5, others 0 |
  | CPU squeeze 4x | 1 of 28 (4 %) | preserve 1/4 (limits applied 20-188m) |
  | CPU squeeze 1x | 33 of 33 (100 %) | every target (limits applied 10-37m) |
  | pod kill | 7 of 35 (20 %) | seat 3/5, order 2/7, station 2/6 |
  | none | 0 of 28 | — |

  Total 90 of 251 = 36 % (the pilot had 39 %).
- **Impact.** Two of eight conditions (62 episodes so far, a quarter of the run) cannot show an
  action's effect. The other six are usable; 161 episodes are unsaturated.
- **Interpretation.** (a) Delay 7 ms and squeeze 1x were the two levels chosen without a clean
  measurement (F10), and both were wrong. (b) The dose check's "bad" (2x the current healthy p95,
  measured on one target) is a weaker test than the labels' (per-flow threshold from calibration):
  dose-check values of 20-60 % correspond to anything from 0 % to 100 % saturated. (c) Severity
  depends at least as much on WHICH service is hit as on the level: 4 ms of delay saturates order and
  basic every time and the other four targets never. A level is not a severity; a (level, target)
  pair is. Doses should be set per target, or relative to each target's own baseline.
- **Lesson.** Pick levels with the same definition the labels use, on every target, before a long run.

### F12. Disk: the MySQL audit log grows without limit

- **Numbers (VERIFIED).** Windows drive free: 41.3 GB at campaign start, 25.6 GB 41 h later (about
  9 GB/day). `mysql-audit.log` of the MySQL leader (`tsdb-mysql-2`, emptyDir `logs`): 9.2 GB in about
  49 h, about 4.5 GB/day at 4 req/s. Prometheus: 2.9 GB, capped by its 24 h retention. Episode data:
  197 MB for 271 episodes. Docker's disk image 72 GB (was 43 GB after the build); it never shrinks.
- **Impact.** At this rate the drive fills in about 3 days; the run needs 3.1 more.
- **Interpretation.** The chart enables Percona's audit log on the database; at higher load it becomes
  the largest writer on the machine. Not seen on the laptop at 2 req/s over short runs.

### F13. Campaign stopped at 253 episodes; what the fixed-threshold labels say (2026-10-12)

- **What was done.** Clean stop at 12:47 (253 of 700 recorded, 447 left). Repo pulled to 173bb83.
  Audit logs emptied in place on all six MySQL pods (leader 9,282 MB -> 0; no restart, leader
  unchanged). All 273 episodes relabelled, 0 failed.
- **Numbers (VERIFIED).** 92 of 253 are saturated by the machine-relative bar. With the fixed 1 s bar
  (`users_bad_before_abs1000 >= 0.8`) only 36 are: squeeze 1x 29 of 33, pod kill 7 of 7, and none of
  delay 7 ms (0/31), delay 4 ms (0/9), loss 22 % (0/11), squeeze 4x (0/1). With the 500 ms bar: 38.
  Median `users_bad_before_abs1000` among the 92: 0.17.
- **Interpretation.** Most "saturation" on this machine is the relative bar, not a broken system: at a
  healthy 25-45 ms, a 250 ms search already counts as bad. Delay and loss episodes stay usable with the
  fixed bar. Squeeze 1x is saturated by any bar. The choice of bar changes the count from 36 % to 14 %
  of the dataset, so the paper must state which bar a "saturated" figure uses.
- **Stalled episodes (VERIFIED).** All 5 are restart-type actions in no-fault blocks: rollout-restart
  on order (2) and station (1), restart-pod on seat (2); 69-75 % of the after-action window was cut.
  The stall rule is removing the action's own damage in exactly the episodes that isolate it.

### F14. Re-dose by the worst-hit user flow, per target; plan `main2` (2026-10-12)

- **Method.** Repo at ee7907f. `dose_check.py` now resets the database before each level and reports
  WORST FLOW: the share of bad requests in the user flow that suffers most, with the labels' own
  threshold (100 ms per flow here). This is what `saturated_before_action` (>= 80 %) is computed from.
  4 req/s, 13:25-15:18 UTC. No row had a container restart or an unapplied fault.
- **Numbers (VERIFIED).** WORST FLOW, with LABEL bad over all requests in brackets:

  | Fault | Target | Levels -> worst flow |
  |---|---|---|
  | delay (ms) | seat | 2 -> book 2 % (1) · 3.2 -> search 15 % (10) · 4 -> search 41 % (24) · 6 -> book 100 % (56) |
  | delay (ms) | order | 1 -> orders 20 % (3) · 2 -> book 58 % (14) · 3 -> book 100 % (33) |
  | delay (ms) | basic | 1 -> book 2 % (0) · 2 -> book 3 % (0) · 3 -> book 46 % (9) |
  | loss (%) | travel | 8 -> search 10 % (7) · 11.3 -> search 26 % (18) · 15 -> search 42 % (29) · 22 -> search 72 % (52) |
  | loss (%) | order | 4 -> 0 % (0) · 8 -> pay 24 % (9) · 12 -> pay 36 % (22) |
  | loss (%) | basic | 4 -> book 2 % (0) · 8 -> book 12 % (6) · 12 -> book 29 % (12) |
  | squeeze | order (27m healthy) | 3x/80m -> book 55 % (16) · 2.5x/67m -> book 74 % (18) · 2x/53m -> book 80 % (27) |
  | squeeze | station (6m healthy) | 3x/17m -> book 80 % (22) · 2.5x/14m -> book 96 % (30) · 2x/11m -> book 100 % (52) |

- **Interpretation.** (a) The average hides the flow that breaks: at 6 ms delay on seat 56 % of all
  requests are bad but 100 % of bookings are. This is why delay 7 ms saturated every episode (F11)
  although the old dose check read "between 36 % and 71 %". (b) Delay on seat goes from 2 % to 100 %
  between 2 and 6 ms: the usable window is about 1 ms wide. (c) Order is about 2.5 times as sensitive
  to delay as seat; basic is less sensitive to delay than seat at low levels. (d) No squeeze level is
  inside 15-65 % on both a busy and a quiet service: the squeeze is a switch, not a dial.
- **Levels chosen (the laptop chat's rule, applied mechanically).** Delay 3.2 and 4 ms (seat: 15 %,
  41 %). Loss 11.3 and 15 % (travel: 26 %, 42 %). The two mild levels were interpolated and then
  measured once. Scale for order 0.35 (from delay: 1.55 ms on order matches 4 ms on seat; loss gave
  0.8, the smaller wins), for basic 0.70 (delay 2.88/4 = 0.72; loss 0.8). No squeeze.
- **Known weak spots.** The mild delay level sits on the band's lower edge (15 %). The two delay
  levels are 0.8 ms apart. One scale serves delay and loss, so loss on order is weak: 3.96 % and
  5.25 % applied, where 4 % measured 0 % and 8 % measured 24 %.
- **Plan.** `run_campaign.py plan --episodes 447 --name main2 --delay 3.2,4 --loss 11.3,15 --squeeze none
  --target-scale ts-order-service=0.35,ts-basic-service=0.7` -> 448 episodes, 64 blocks of 7, six
  conditions (none, pod kill, two delay, two loss). Started 15:19 UTC.

### F15. Windows Update restarted the machine mid-campaign (2026-10-13)

- **What happened.** At 23:29 local (17:59 UTC) Windows Update (`MoUsoCoreWorker.exe`, reason
  "Operating System: Service pack") restarted the PC. The campaign died mid-episode (b025_3, its
  network delay left behind). Docker Desktop is not set to start with Windows, so nothing came back.
  Found at 04:50 UTC the next morning: about 11 h lost, roughly 70 episodes.
- **Recovery (VERIFIED).** Start Docker Desktop; the kind nodes restarted by themselves with the
  open-files cap still in place. `ops/recover-after-restart.sh` (20 services back in pairs, 13 min,
  MySQL leader moved from tsdb-mysql-2 to tsdb-mysql-0), `loadgen/warmup.sh` (0.3/0.6/1.0 req/s all
  100 % ok), `ops/cleanup.sh` (deleted the leftover NetworkChaos), then the campaign resumed from the
  interrupted episode. Down time to resumed: 21 min of work.
- **Lesson.** On a borrowed Windows machine, pause Windows Update for the length of the run before
  starting, and know the recovery path. The repo's resume design meant nothing recorded was lost.
- **It happened again (2026-10-16).** Updates were still not paused. 00:29-00:32 local, three
  restarts in a row (`MoUsoCoreWorker.exe` "Service pack (Planned)", then `TrustedInstaller.exe`
  "Upgrade (Planned)" twice). Campaign died in episode b060_2 at 414 of 448; found 15:30 UTC, about
  20.5 h lost. Same recovery, 20 min, all services ready, warm-up 100 % ok; resumed 15:51 UTC.
  Both restarts came around midnight local, when nobody was watching.

### F16. Batch 1 finished; the load generator kept running afterwards and broke the idle cluster

- **Numbers (VERIFIED).** Plan `main2` finished 2026-10-16 21:07 UTC: 448 of 448 `ok`, 0 discarded,
  0 stalled, 17 saturated (3.8 %). Batch 1 in total: 701 episodes (253 `main` + 448 `main2`) plus 20
  calibration; all 721 `ok` and `usable` in `episodes.csv`; 337 MB of raw data.
- **What happened afterwards.** `CAMPAIGN DONE` left the continuous load generator running with no
  episode to reset the database. 7 h later (04:00 UTC) every request started failing (search and book
  HTTP 500, orders 503; gateway: "No servers available for service: ts-order-service"). Orders table at
  the check: 22,607 rows. Stopping the generator, `reset-data.sh` and a rollout restart of
  ts-order-service fixed it (105 of 105 requests ok). No episode was affected.
- **Lesson.** The runner should stop its load generator when the plan completes.

### F17. Batch 2 setup and dose check; db-delay never reaches the database traffic (2026-10-17)

- **Setup (VERIFIED).** Repo 5d36c85. Audit log off on all six MySQL pods (runtime setting, lost if
  MySQL restarts). Five services added (travel2, preserve-other, assurance, cancel, execute): memory
  available 10.0 -> 7.7 GB. First run of the full `wide` mix, 10 min at 4 req/s: 2,381 of 2,381 ok,
  all nine flows 0 % failed. Wide-mix calibration: z 1.6, fitted on 49, checked on 19, held-out false
  harm 0/348.
- **Dose check, wide mix, WORST FLOW (VERIFIED).**
  delay@seat 3.2: 21 % · 4: 47 % | delay@order 1.12: 0 % · 1.4: 10 % | delay@basic 2.24: 11 % · 2.8: 41 % |
  delay@travel2 3.2: 0 % · 4: 8 % | delay@preserve-other 3.2: 6 % · 4: 25 % |
  loss@travel 11.3: 25 % · 15: 49 % | loss@travel2 11.3: 16 % · 15: 48 % | loss@preserve-other 11.3: 8 % · 15: 22 % |
  db-delay 10/30/60 ms on order and seat, 30 ms on travel2: 0 % in every row |
  pod-hang@seat: search 100 % (70 % of all requests failed) · pod-hang@travel2: search2 100 %.
- **db-delay test episode (VERIFIED).** `ep_wide_dbtest`, 30 ms on order, no-op: users 0 % bad before
  the action and 0 % after, in every flow; order's own requests 0 bad of 665 before, 0 of 1,835 after.
- **Cause (connection VERIFIED, mechanism INFERRED).** Order holds its 10 MySQL connections to
  10.96.7.195, the ClusterIP of service `tsdb-mysql-leader`. The fault's `target` selects the MySQL
  pods (10.244.x.x). Packets leave the order pod addressed to the ClusterIP and are rewritten to a pod
  IP only on the node, after the pod's own filter has already looked at them, so the delay never
  matches. Chaos Mesh reports the fault as injected anyway.
- **Interpretation.** The new travel2 and preserve-other targets are far less sensitive to delay than
  seat (8 % and 25 % at 4 ms against 47 %). A fault that reports "injected" can still do nothing; only a
  measured user effect proves it.

### F18. The wide-mix calibration also fitted on batch 1's episodes and rewrote their labels

- **Numbers (VERIFIED).** `calibrate` with `ARC_MIX=wide` (17 Oct 12:20-14:43 UTC) ran 20 new
  episodes (ep_cal_arc_021-040) but fitted on every no-fault no-op episode on disk: 68 in all, 40
  calibration (20 core-mix from 10 Oct, 20 wide-mix) plus 28 batch-1 campaign episodes (8 main,
  20 main2). It then relabelled those 68 with the new thresholds. Batch 1's own calibration fitted on
  20 core-mix episodes only.
- **Impact.** (a) The labels of 48 batch-1 episodes on disk now differ from the batch-1 archive made
  at 11:43 UTC, which still holds the batch-1 calibration (checked: identical checksums to
  `calibration-batch1`). (b) wide1 is labelled with thresholds fitted mostly on core-mix episodes.
  Raw data is intact, so both are fixable by relabelling with the right calibration.
- **Lesson.** A calibration must be fitted only on episodes of the same system and load mix.

### F19. wide1 finished at 500 of 504: Prometheus was killed for memory 35 times (2026-10-21)

- **Numbers (VERIFIED).** CAMPAIGN DONE 21 Oct 05:47 UTC. 500 ok, 1 discarded ("no span metrics in
  the export", b070_2), 3 never recorded after two attempts each (b066_7, b070_1, b070_4; "export
  FAILED", `TimeoutError`). Many other episodes needed a second attempt; the last day ran at about
  2.6 episodes/h instead of 6. Prometheus (limit 1000Mi): 35 restarts, last termination OOMKilled
  (exit 137) at 05:35 UTC; resident memory 862 MB at rest; head series 94k-114k over the last 24 h
  with 25 services.
- **Cause (INFERRED from the above).** Each time Prometheus is killed, the metrics of the episode in
  progress are lost or not yet queryable, so its export times out or lacks span metrics.
- **Impact.** 4 of 504 episodes lost, about 10 h of machine time spent on retries. The three
  unrecorded folders exist but have no meta.json: use `index/episodes.csv`, not the folder list.
- **Fix to decide before any further run.** Raise Prometheus' memory limit (e.g. 2Gi; 7.5 GB is free).
- **Also done.** Wide-only calibration (ep_cal_arc_021-040: z 1.6, held-out false harm 0/110) in
  `calibration-wide`; wide1 and those 20 relabelled with it (521). Batch 1 relabelled with
  `calibration-batch1` (721); spot checks match the 17 Oct archive exactly. The default
  `calibration/` still holds the blended 17 Oct fit: any new run must use `calibration-wide`.

### F20. Reply-side db-delay works, but is a switch, not a dial (2026-10-21)

- **Numbers (VERIFIED, wide mix, 4 req/s, WORST FLOW).** order 2 ms 97 %, 4 ms 100 %, 6 ms 100 %,
  10/30/60 ms 100 % | seat 10/30/60 ms 0 % | travel 2 ms 0 %, 5 ms 3 %, 10 ms 42 % |
  station 5 ms 8 %, 15 ms 100 %, 30 ms 100 % | travel2 10 ms 8 %, 15/20/30/60 ms 100 %.
  Test episode (30 ms on order, no-op): order p50 5 -> 62.5 ms, travel 24 -> 189 ms, station
  5.0 -> 5.0 ms (label: no harm), users saturated by the fixed 1 s bar too.
- **Interpretation.** The fix is selective, as intended: the untargeted database user is untouched.
  One request makes many database calls, so a few ms per query multiply; the worst flow jumps from
  under 10 % to about 100 % within a few ms on every target except travel. Order saturates at the
  smallest level tested. `--target-scale` does not apply to db-delay, so one level would serve all
  targets, and no single level is usable on all four.

### F21. wide2: the cancel flow drifted slower all run long, and the saturation flag followed it

- **Numbers (VERIFIED).** Cancel median (load generator, per 4 h): 77 ms (22 Oct 12:00 UTC), 89, 98,
  106, 118, 128, 131 ms (24 Oct 12:00); p90 92 -> 150-156 ms. Other flows flat (search 31-36 ms,
  book 68-79 ms, orders 12-15 ms). Its calibrated threshold is 111 ms, so from about 23 Oct 20:00 the
  worst flow before the action was "cancel" at 80-100 % in almost every episode: 123 of 290 saturated,
  including 16 of 42 no-fault episodes (0 of 21 a day earlier). users_bad_before_abs1000 stayed 0 in
  those episodes: under the fixed 1 s bar they are not saturated.
- **Cause (tables VERIFIED, link INFERRED).** `ops/reset-data.sh` cleans orders, orders_other, payment
  and inside_payment, but not `assurance` (167,787 rows; 30 % of bookings buy insurance) or
  `inside_money` (60,355 rows; every cancel writes a refund). Cancel reads them.
- **Impact.** The relative labels of the second half of wide2 are inflated for the cancel flow and the
  services on its path; the raw data is intact and the fixed-bar labels are unaffected.
- **Lesson.** Every table the load writes must be in the reset, or the baseline drifts (F9 again,
  through a table added with batch 2).
- **Follow-up (2026-10-24, VERIFIED).** The drift began with batch 2, not with wide2. Cancel median in
  B0 per fifth of each run: wide1 25, 34, 42, 49, 56 ms; wide1db 64, 65, 66, 68, 72 ms; wide2 83, 94, 105,
  118, 130 ms. No no-fault episode of wide1 or wide1db was saturated (the threshold was not yet
  crossed). calibration-wide-8 was fitted on 22 Oct, already drifted: its cancel median is 75.9 ms.
  Fix in ops/reset-data.sh: delete assurance rows whose order is gone, and the load account's
  inside_money refund rows ('D'; the one 'A' row is kept). 15-min check at 8 req/s: 0 failed requests
  before and after; cancel median 140 -> 20 ms (p90 162 -> 23); book 76 -> 64 ms, orders 20 -> 13 ms;
  assurance 170,393 -> 185 rows (545 after 15 min), inside_money 61,233 -> 1 (73 after 15 min).
  A health-gate warning now logs any flow whose B0 median is > 15 % above its calibration median
  (meta["baseline_drift"]); it never aborts.

### F22. The calibration itself can be drifted; refit on the clean database (2026-10-25)

- **What happened.** calibration-wide-8 was fitted on 22 Oct 10:38-13:04 UTC, five days into the
  cancel drift of F21. Its cancel median is 75.9 ms and its cancel threshold 111 ms; on the cleaned
  database cancel runs at about 20 ms (B0 ratio 0.26 in the live check of the new drift warning).
- **Impact.** Labels made with it are less sensitive for the cancel flow (a slowdown from 20 to 100 ms
  stays below the 111 ms bar). Everything else in it matched the clean run within 11 %
  (search 0.89, search2 1.06, book 0.98, book2 1.01, pay 1.01, orders 0.99, orders2 1.01, collect 0.98).
- **Response.** The drift warning also fires when a flow's B0 median is more than 30 % BELOW its
  calibration median ("stale calibration", laptop commit d523d64). A new 8 req/s calibration,
  calibration-wide-8c, is fitted on the clean database only on the 20 episodes it records, before held.
- **Lesson.** A calibration is a measurement of the system at one moment; if the system's state drifted
  before it was taken, it inherits the drift. Check the baseline before calibrating, not only after.

### F23. Compacting Docker's disk image (2026-10-25)

- **Numbers (VERIFIED).** Docker's disk image had grown to 118.3 GB while holding about 73 GB; C: was
  down to 8.8 GB free and falling about 1 GB/h with the cluster idle (Prometheus and MySQL keep
  writing; the image never returns freed space). Steps: `docker run --privileged --pid=host
  docker/desktop-reclaim-space` (trim), `docker desktop stop`, `wsl --shutdown`, then as administrator
  `diskpart`: select vdisk / attach vdisk readonly / compact vdisk / detach vdisk. Result: 118.3 ->
  73.9 GB; C: free 8.8 -> 52.8 GB. Restart: kind nodes up in 10 s with the open-files cap intact;
  recover-after-restart.sh 25 services ready in 18 min; MySQL leader moved to tsdb-mysql-1; warm-up
  100 % ok. About 45 min offline in all.
- **Lesson.** On a machine with one disk, plan a compaction between long runs; Windows shadow copies
  (up to 19 GB, F12/F19) and the Docker image are the two silent consumers.

### F24. Repeatability: the same episode, five times (2026-10-24)

- **Design.** 4 fixed recipes x 5 runs, interleaved, wide mix, 8 req/s, calibration-wide-8, reset fix
  applied. 20 of 20 ok (one export retried), none saturated.
- **Numbers (VERIFIED).** User damage, min-max: R1 no fault / no-op 0.00-0.38 (four runs ~0);
  R2 delay 4 ms seat / restart-pod seat 0.86-3.42; R3 loss 15 % travel / drain travel 0.82-1.06;
  R4 no fault / rollout-restart order 2.45-3.74. Callers' y_peak, min-max: R3 gateway 0.29-0.35,
  preserve 0.44-0.67; R2 travel 0.64-0.72, preserve 0.20-0.80, travel2 0.58-0.98; R4 gateway
  0.44-0.65, preserve 0.44-0.84, low-traffic callers (cancel, inside-payment) 0.0-0.98.
- **Interpretation.** The no-op baseline is near zero and the drain recipe repeats tightly; restart
  recipes repeat in size order but spread 2-4x, most for low-traffic services. Labels of rare flows are
  the noisiest part of the dataset.

### F25. Smoke test of the held-out faults: 2 of 6 pass (2026-10-25)

- **Setup.** Repo 01b8dbd, wide mix 8 req/s, clean database, calibration-wide-8c (fitted on
  ep_cal_arc_061-080 only: z 1.6, held-out false harm 0/176). One no-op episode per case on seat.
- **Numbers (VERIFIED).** http-error: HTTPChaos "not AllInjected within 30 s" (Selected True,
  AllInjected False), episode discarded, teardown stuck (finalizer forced); it left a PodHttpChaos on the
  seat pod with a "replace response code 500" rule (status empty, not active: 128/128 then 477/477
  requests ok); removed by hand. call-cut (seat -> config): verified, worst flow book 100 %, travel,
  travel2, preserve, preserve-other 100 % bad: saturated. shared-db-slow 5 ms and 15 ms: verified,
  worst flow 100 %, saturated. load-surge 1.5x: worst flow 9 %; 2x: 18 %; both clean and healthy.
  All teardowns except http-error clean; healthy after in 4-5 s; drift ratios 0.87-1.22.
- **Interpretation.** Cutting one call or slowing the shared database by 5 ms breaks every booking:
  these are switches at this load, like db-delay (F20). HTTP fault injection does not attach on this
  stack (sidecar-less HTTPChaos needs the target's traffic to pass its proxy port).

---

## 3. How to deal with machine dependence (design notes)

ARC's input is the system state and the action, not the fault setting. The setting only has to produce
a spread of realistic incidents. What must not depend on the machine is what the model sees.

1. **Dose by effect, not by setting.** Choose the level that makes 10-25 % (mild) and 40-60 % (strong)
   of requests bad on this machine. Fang et al. (arXiv:2510.04711) found 84.4 % of 9,152 injections had
   no user-visible effect and kept only cases with a measured impact on user-facing indicators.
2. **Give the model ratios.** Latency relative to the service's healthy latency, CPU use / limit,
   error share, and the measured severity before the action. Never raw milliseconds or the setting.
3. **Define levels relative to the system.** Loss in percent and CPU limit as a multiple of use already
   are. Delay could be a multiple of the call's healthy latency.
4. **Match the operating point.** Same fraction of capacity on every machine, not the same req/s.
5. **Spread the levels.** Sample across a range so the model sees the dose-response curve.
6. **Test it.** Train on one machine, test on the other (laptop pilot vs lab), and 20 vs 30 services.
   The closest prior work (arXiv:2607.20005) reports one fixed cluster and no fault intensities.

Recoverable later: labels and input features are recomputed from raw episodes (`harness/relabel.py`).
Not recoverable: the doses and the operating point. Those must be right before the campaign.

### Fault families by machine dependence

| Kind | Examples | Depends on the machine? |
|---|---|---|
| On/off | pod kill, hung pod, network cut, dependency down, DNS error | No (recovery time still scales with CPU speed) |
| Proportional | packet loss %, abort a share of HTTP requests, wrong status code | Little |
| Relative to baseline | delay = k x healthy latency, CPU limit = k x use | Little, by design (see F6 for the trap) |
| Logic / config | code bug, bad deploy (heap too small), wrong return value | No |
| Absolute | fixed-ms delay, CPU or memory stress with fixed workers, fixed limits | Yes: dose per machine |

In arXiv:2510.04711, HTTP request abort (100 %) and response status replacement (98 %) almost always
produced visible impact, while CPU and memory stress almost never did at first try because the
effective range is narrow. On our stack HTTP faults are still unproven (kept-alive connections; see 06).

## Sources

- Fang et al., "Rethinking the Evaluation of Microservice RCA with a Fault Propagation-Aware Benchmark", arXiv:2510.04711
- Dai et al., "Safe Remediation as Risk-Constrained Intervention Decision in Microservice Systems", arXiv:2607.20005
- Basiri et al., "Chaos Engineering", arXiv:1702.05843 (steady state as a measurable output; control vs experiment group)
- This repo: `docs/research/06-faults-actions-v2.md`, `07-pilot-results.md`, `docs/LAB-SETUP.md` (laptop reference numbers)
