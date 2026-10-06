# 06 — Fault set and action set, v2 (fitted to the testbed we actually have)

Date: 2026-09-29. This builds on `02-fault-and-action-taxonomy.md` and does not repeat it.
**VERIFIED** means I saw it in a source (URL or local file path given). **BELIEVED** means engineering inference that still needs a smoke test.

---

## 0. The short version

- **Pilot faults (6):** `none`, `pod-kill`, `net-delay 300 ms`, `net-loss 15 %`, `cpu-stress 2×100 %`, `blackhole` (100 % egress loss). Every one is a Chaos Mesh CR or nothing at all. All are removed by deleting the CR, and none needs extra memory.
- **Pilot actions (6):** `noop`, `restart-pod`, `rollout-restart`, `scale-up 1→2`, `cpu-bump 2→4 cores (in place)`, `quarantine (NetworkPolicy)`. `cpu-bump` is the **negative control**: if it shows as much collateral damage as a restart, the measurement is broken.
- **flagd code faults: leave them out of the pilot.** Only **3 of the 22** flags are read by any code (tt-feat-01, -17, -22), and none of the three is on our running request path. Details in §3.
- **Four changes to make before the pilot:** (1) lengthen **M from 120 s to 180 s** (§2.3). (2) Record whether the Chaos fault **survived the action** (§2.4). (3) Put a memory guard in front of scale-up and rollout-restart. (4) Smoke-test StressChaos and NetworkPolicy, 5 minutes each.

---

## 1. Fault set: what 2025–26 prior art injects, and what survives on our testbed

### 1.1 What the prior art injects

| Source | Faults | Note |
|---|---|---|
| arXiv:2607.20005 (Safe Remediation) | CPU, memory, disk I/O, socket, network delay, packet loss, network partition, pod kill, HTTP abort, clock skew, DNS error. One service per injection. 41-service Train Ticket on K8s 1.28. Labels: health deviation **within 60 s** of the action | VERIFIED https://arxiv.org/html/2607.20005v1. **No intensities are published**, and the 12 actions are not listed by name |
| RCAEval RE1–RE3 | CPU / MEM / DISK / SOCKET via stress-ng. DELAY / LOSS via tc. RE3 code faults: wrong parameter value, missing parameter, missing call, wrong return value, missing exception handler | VERIFIED https://arxiv.org/html/2412.17015. **No intensities are published either.** Load 10–200 req/s |
| SREGym (arXiv:2605.07161) | Only **2 Train Ticket problems**: `trainticket_f17_nested_sql_select_clause_error` and `train_ticket_f22` (SQL column-name mismatch) | VERIFIED https://github.com/SREGym/SREGym/blob/main/Problem%20List.md, https://github.com/SREGym/SREGym/tree/main/sregym/conductor/problems |
| SREGym, recent PRs | #1038 adds a "pre-incident baseline window", #1042 a "propagation window between fault injection and agent start". These match our B0 and our random delay | VERIFIED (PR titles) https://github.com/SREGym/SREGym/pull/1038, https://github.com/SREGym/SREGym/pull/1042 |
| ARBITER (arXiv:2607.19182, Jul 2026) | Faults: bad image rollout (CPU-burn and latency variants), CPU pressure on a critical-path service, noisy neighbour, 12-worker busy loop. **Actions: `scale_out`, `resize_cpu`, `deschedule_one`, `rollback_canary`**, each with a disruption budget | VERIFIED https://arxiv.org/html/2607.19182v1. Runs on DeathStarBench Social Network and Online Boutique, **not Train Ticket**. Its action set is almost the same as ours, which supports our choice |
| GuardedAct (arXiv:2609.11264), E2E-REME (arXiv:2604.11094) | Remediation safety / RL remediation. E2E-REME uses Online Boutique | Titles VERIFIED via search. Fault lists not extracted |

**Takeaway:** nobody publishes intensity levels, so we have to calibrate our own against the noise thresholds in `MEASUREMENT-SPEC.md` (busy services 1.25×, quiet services 2–5.6×). "Deploy regression → rollback" appears in ARBITER and AIOpsLab and matches Gunawi's top root cause (UPGRADE). It belongs in the full run as the **bad-deploy** family (§4.2).

### 1.2 Each candidate fault checked against OUR constraints

Testbed facts used below:
- JVM `-Xmx200m` from the Dockerfile `CMD`. VERIFIED `~/src/xlab-train-ticket/ts-seat-service/Dockerfile`, base image `eclipse-temurin:8-jre`.
- Container limits: memory 2000Mi, CPU now 2 cores. Requests: 100m / 300Mi. VERIFIED `deploy.yaml` and RUNBOOK.
- Readiness probe is `tcpSocket` with a 60 s initial delay. There is **no liveness probe**. VERIFIED `deploy.yaml`.
- The callers' load balancer is Spring Cloud LoadBalancer (Spring Boot 2.7.18). VERIFIED `pom.xml`. **It caches the instance list for 35 s by default, and load-balanced RestTemplate retries are off by default.** VERIFIED https://docs.spring.io/spring-cloud-commons/docs/3.1.x/reference/html/
- WSL has 12 CPUs, 17 GB RAM and 8 GB swap. VERIFIED `C:\Users\Laksh\.wslconfig`.

| Fault | Realistic? | Measurable at 2 req/s? | Cleanly reversible here? | Verdict |
|---|---|---|---|---|
| pod-kill | yes (crash; Liu: error component 43 %) | yes: ~70–85 s outage plus cold start | yes (ReplicaSet). Verified in the harness | **pilot** |
| net-delay (egress of target) | yes | yes: every call into the target pays the delay. Search fans out per trip (travel→basic/seat), so it multiplies | yes (tc removed). Verified in the harness | **pilot** 300 ms; full run 100/300/1000 ms |
| net-loss | yes | yes: TCP retransmits (≥200 ms RTO; SYN retry 1 s, 3 s) give tail latency | yes | **pilot** 15 %; full run 5/15/30 % |
| blackhole (100 % loss) | yes (unresponsive component, Liu 29 %) | yes: callers hang (no connect timeouts are set, BELIEVED), then Nacos drops the instance and callers fail fast with "no instances" (BELIEVED) | BELIEVED: the Nacos client re-registers after heal. The health gate catches it if not | **pilot**. Beware floor effects (callers already at ~100 % errors cannot get worse) |
| cpu-stress (StressChaos) | yes (RCAEval CPU, ARBITER) | yes: 2 workers at 100 % in a 2-core cgroup starve the JVM. Also a noisy neighbour on the node | yes, if the StressChaos actually attaches. **Risk:** cgroup-v2/containerd problems, e.g. https://github.com/chaos-mesh/chaos-mesh/issues/4038 → 5-min smoke test (throttling metric must rise) | **pilot**, workers 2 load 100. Full run also workers 1 |
| cpu-limit squeeze (in-place resize 2→0.25 core) | yes (mis-sized limits; RUNBOOK measured travel at 500m throttled 45 %) | yes | yes (resize back, no restart) | **fallback** if StressChaos fails the smoke test. Full-run fault. `cpu-bump` is its natural fix |
| network partition (target ↔ callers, or target ↔ tsdb) | yes (Gunawi CROSS) | yes | BELIEVED. Partition has direction bugs (#4477) and ipset cleanup bugs when pods restart mid-chaos (https://github.com/chaos-mesh/chaos-mesh/issues/4827, v2.7) | full run only; DB partition only for DB-backed targets |
| memory stress | yes (RCAEval MEM) | **no**: heap is capped at 200m, so a stressor outside the heap barely touches the JVM until the 2000Mi limit, and the laptop has only ~1.8 GB free, so a big stressor risks node-wide swapping | risky | **exclude on laptop.** DGX: use the F3-style bad deploy instead (§4.2) |
| pod-failure (pause image) | yes (hang) | yes | two restarts (pause in, JVM back → cold start). Pause image must be local: set `controllerManager.podChaos.podFailure.pauseImage=registry.k8s.io/pause:3.10`, which is already on kind nodes (BELIEVED) | full run |
| HTTP abort (HTTPChaos) | yes (2607.20005 uses it) | only if it fires. It needs non-reused TCP connections (VERIFIED in the Chaos Mesh docs, see 02), and our RestTemplate keeps connections alive | BELIEVED flaky | full run only after a 20-episode check |
| disk I/O, socket, DNS, clock skew, JVMChaos, Kernel/Block | — | Java services barely touch disk. DNS: calls go through Nacos IPs plus JVM DNS cache. Clock breaks JWT and our telemetry. JVMChaos: `eclipse-temurin:8-jre` has no attach tooling | — | **exclude** (reasons in 02) |

---

## 2. Action set without Istio and with 1 replica

### 2.1 Two facts that shape every restart-type action

1. **Rolling update with 1 replica = surge, not downtime.** The Deployments set no strategy, so the default 25 %/25 % applies. With 1 replica, maxSurge rounds up to 1 and maxUnavailable rounds down to 0. The new pod starts and the old one keeps serving until the new one is Ready (BELIEVED; standard K8s rounding). Ready here means the TCP port is open, so "Ready" comes before Nacos registration and JIT warm-up. `rollout-restart`, `rollback` and any template patch therefore cost +1 JVM (~0.45 GB) for ~80–100 s, then a cold replacement. `delete pod` gives ~70–85 s of full outage instead. **These are different damage profiles, which is why both are in the set.**
2. **Callers keep a stale instance list for up to 35 s** (SCL cache, VERIFIED above). After a restart, callers still send to the dead IP for up to 35 s. After a scale-up, the new replica gets traffic only once the cache refreshes. At that point round-robin sends about half of all calls to a **cold** JVM.

### 2.2 Implementations (namespace `train-ticket`, context `kind-arc`)

`K="kubectl --context kind-arc -n train-ticket"`, `S=<service>`, `P=<its running pod>`.

| Action | Apply | Post-condition (sets `action_applied`) | Reset after M | Time to effect | Memory | Expected collateral mechanism on OUR stack |
|---|---|---|---|---|---|---|
| **noop** | — | — | — | — | 0 | none: the counterfactual arm |
| **restart-pod** | `$K delete pod $P --grace-period=0 --force --wait=false` (already in the harness) | a new pod exists within 30 s (already in the harness) | none; the next steady-state gate absorbs the warm-up | outage now; Ready 70–85 s; slow for ~50 s more (JIT) | 0 | Callers' in-flight requests get RST. For ≤35 s callers target the dead IP. Callers without connect timeouts hang (BELIEVED). Then "no instances". Then a cold JVM. **The JIT storm burns up to 2 cores on the node, which slows co-located, graph-unrelated pods** (the non-graph channel that static reachability misses) |
| **rollout-restart** | `$K rollout restart deploy/$S` (**do not** block on `rollout status`) | within 10 s, `.status.observedGeneration` has increased and a new RS exists. Background: record `new_pod_ready_at` | none (the template differs only in the `restartedAt` annotation) | old pod serves; new pod Ready 70–85 s; then the old pod gets SIGTERM | **+0.45 GB for ~90 s** | Startup CPU while the old pod still serves. Spring Boot 2.7 defaults to `server.shutdown=immediate`, so in-flight requests on the old pod drop. Callers' 35 s cache holds the old IP after it dies. Then the cold pod. Damage peaks **~80–130 s after the action** |
| **scale-up** | `$K scale deploy/$S --replicas=2` | 2 pods exist within 10 s. Background: `new_pod_ready_at` | `$K scale deploy/$S --replicas=1`. The ReplicaSet deletes the **newer** pod (BELIEVED, deletion ranking prefers recently created pods), so the warm pod survives. Wait ≥40 s (cache) before the next gate | new pod Ready 70–85 s, gets traffic ≤35 s later | **+0.45 GB for M + reset** | Cold-replica latency on ~50 % of calls. +10 Hikari connections to the shared tsdb (Hikari default pool 10, BELIEVED; check `SHOW VARIABLES LIKE 'max_connections'`). JIT on the node. The reset itself removes an instance, which means another ≤35 s of stale cache |
| **cpu-bump** (in place) | `$K patch pod $P --subresource resize --type=merge -p '{"spec":{"containers":[{"name":"'$S'","resources":{"limits":{"cpu":"4"}}}]}}'` (same mechanism as the working `cpu-resize.sh`) | `.status.containerStatuses[0].resources.limits.cpu=="4"` and `restartCount` unchanged | same patch with `"cpu":"2"` | seconds | 0 | Expected ≈ null, which is why it is the **negative control**. Only under cpu-stress does it help: the JVM gets 2 free cores (a **non-degenerate pair**). A burst on the target can steal node CPU from neighbours |
| **quarantine** (NetworkPolicy) | apply the YAML in §5.3 | the NP exists. Optional canary: a new TCP connection from a scratch pod times out | `$K delete networkpolicy arc-q-$EP`; wait 40 s | new connections are dropped at once; **established keep-alive connections survive** until they close (BELIEVED, from kindnet's first-packet design) | 0 | Callers' SYNs are dropped silently, so they hang until their timeouts. Every upstream path through the target fails. Nacos still lists the target (it can still heartbeat out). The target's own latency looks *better* (less traffic), which is an artefact the label must not reward. **Side effect:** each policy change rebuilds nftables, which drops packets queued on nfqueue on that node (https://github.com/kubernetes-sigs/kube-network-policies/issues/402) |
| **rollback** (full run; needs seeding, §2.5) | `$K rollout undo deploy/$S --to-revision=$REV_A` | the new RS has the A template hash | benign variant: none. Regressive variant: `rollout undo --to-revision=$REV_B` + warm-up | same as rollout-restart | +0.45 GB for ~90 s | Same as rollout-restart, plus whatever revision A regresses |

**Does kind enforce NetworkPolicy? Yes.** VERIFIED: kind v0.24.0 added "out-of-the-box support for network policy via sigs.k8s.io/kube-network-policies" in kindnetd, and **v0.30.0 is the release whose default node image is v1.34.0** (i.e. ours): https://github.com/kubernetes-sigs/kind/releases. Mechanism: the first packet of a connection is checked in user space and the verdict is cached (VERIFIED https://kindnet.es/docs/user/network-policies/). So **existing connections are not cut** (BELIEVED consequence). Kubelet readiness probes should still pass because node-to-pod traffic is allowed (BELIEVED). Smoke test: apply the NP to `ts-station-service`, then check that basic→station calls fail and the pod stays Ready. **Fallback if not enforced:** disable the instance in Nacos: `PUT /nacos/v1/ns/instance?serviceName=$S&ip=$IP&port=$PORT&enabled=false&ephemeral=true`. That is "drain traffic" Nacos-style, BELIEVED, and the client's redo may override it.

**Other candidate actions:**
- **restart a dependency.** Already covered: the action target is randomised, so restart-pod on a callee *is* "restart a dependency". Do **not** restart tsdb/nacos: xenon re-enables semi-sync after a MySQL restart, which blocks writes (RUNBOOK), and Nacos is a single copy.
- **client-side load-shed** (full run): the loadgen reads a control file, e.g. `{"drop": {"book": 0.5}}`. Shed requests **must count as client errors**, otherwise shedding looks free (MEASUREMENT-SPEC already warns about this).
- **scale-down / drain-one-instance / deschedule_one:** meaningless at 1 replica. **Cordon/drain:** on this laptop it restarts ~7 JVMs at once, which is the Nacos crash loop from the RUNBOOK. **Exclude both on the laptop.** On the DGX, run the targets at **2 replicas** so scale-down 2→1 and draining one instance become real (see §4.2).

### 2.3 The M window is too short for surge-type actions (decide before the pilot)

`rollout-restart`, `rollback` and `scale-up` make their damage **80–130 s after the action**: Ready 70–85 s, plus ≤35 s of cache, plus JIT. M currently ends at 125 s, so it cuts that damage off and would under-label exactly these actions. **Recommendation: M = 180 s for every episode** (not per action, which would confound). This adds 1 min per episode. 2607.20005's 60 s window has the same blind spot, which is worth one sentence in the paper.

### 2.4 Does the fault survive a restart-type action? (must be recorded)

When the action replaces the target pod, the new pod may not receive the Chaos fault. That turns restart into an accidental "fix" of netem or stress faults. Chaos Mesh re-injection onto replacement pods is **not documented** (https://github.com/chaos-mesh/chaos-mesh/issues/1222 was left unanswered). NetworkChaos cleanup also breaks when pods restart during chaos (https://github.com/chaos-mesh/chaos-mesh/issues/4827, v2.7). BELIEVED: in 2.6.3 the targets are fixed when the experiment starts, so a new pod is **not** injected. **Harness:** 5 s after the action, read `.status.experiment.containerRecords` and set `fault_on_new_pod = (new pod name ∈ records)`. That is realistic for a CPU stressor (it dies with its container) but an artefact for netem. Keep the flag and analyse restart × network faults with it.

### 2.5 Rollback: seeding a sensible "previous revision"

Today's history: rev without OTel, rev with OTel, and probably a rev from `persist-cpu-limit.sh` (500m→2). **A plain `rollout undo` could strip the OTel agent or drop CPU back to 500m, so always use `--to-revision`.**

Seed once per target at setup, in batches of ≤3 (it costs 2 restarts per service):
```bash
$K set env deploy/$S ARC_BUILD=2026.09-a [+ variant env, below]; $K rollout status deploy/$S --timeout=240s
$K set env deploy/$S ARC_BUILD=2026.09-b [variant env removed];  $K rollout status deploy/$S --timeout=240s
# find revision A for the action:
REV_A=$($K get rs -l app=$S -o json | jq -r '.items[] | select(any(.spec.template.spec.containers[0].env[]?; .name=="ARC_BUILD" and .value=="2026.09-a")) | .metadata.annotations["deployment.kubernetes.io/revision"]')
```
Keep `revisionHistoryLimit` at 10. Every rollout-restart action adds a revision, so check `REV_A` exists before each rollback and re-seed if it was pruned.

Realistic A-vs-B differences. Store the variant as `rollback_variant`:

| Variant | Revision A carries | Effect | Realism |
|---|---|---|---|
| `benign` | only `ARC_BUILD` | pure redeploy cost (≈ rollout-restart) | "rolled back a harmless version bump" |
| `jvm-c1` | `JAVA_TOOL_OPTIONS="-javaagent:/otel/opentelemetry-javaagent.jar -XX:TieredStopAtLevel=1"` | slower steady state, faster warm-up | JVM startup tuning left in. Works through `JAVA_TOOL_OPTIONS` because the CMD does not set it (BELIEVED) |
| `heap-small` | `command: ["java","-Xmx128m","-jar","/app/<svc>-1.0.jar"]` | more GC. Needs `command` because the CMD's `-Xmx200m` beats `JAVA_TOOL_OPTIONS` (the command line wins, BELIEVED) | classic config regression |
| `threads-low` | `SERVER_TOMCAT_THREADS_MAX=8` | harmless when healthy; **binds only under fault latency** (an interaction) | Fudan F5 (thread-pool starvation) |
| `hikari-low` (DB-backed only: order, travel, station) | `SPRING_DATASOURCE_HIKARI_MAXIMUMPOOLSIZE=2` | queueing on `getConnection()` | common pool mis-sizing |

Avoid image-tag changes on the laptop (150 MB per node at ~200 KB/s). Pilot: no rollback, or `benign` only. Full run: uniform over the 5 variants.

---

## 3. Fudan / flagd code faults: what is actually wired

**How toggling works** (VERIFIED, local clone `\\wsl$\Ubuntu\home\laksh\src\xlab-train-ticket`, cloned Sept 2026, plus SREGym's `inject_tt.py`):
- The flags live in ConfigMap `flagd-config`, key `flags.yaml`. There are 22 boolean flags with `defaultVariant: "off"` (`templates/flagd-config.yaml`). flagd v0.11.1 serves them on gRPC :8013 and OFREP :8016 (`templates/flagd-deployment.yaml`).
- SREGym toggles a flag by patching `defaultVariant` in the ConfigMap, running `kubectl rollout restart deployment/flagd`, then **`sleep(20)`**. Its `supported_faults` are **only `tt-feat-17` and `tt-feat-22`**. Other flags are used as decoys. VERIFIED https://raw.githubusercontent.com/SREGym/SREGym/main/sregym/generators/fault/inject_tt.py

**Which flags any code reads.** VERIFIED by grepping the whole clone: only three.

| Flag | Fudan | Service (running?) | Code | SLO-visible with our 20 services + loadgen? |
|---|---|---|---|---|
| `tt-feat-01` | F1 (async ordering) | ts-cancel-service (**scaled to 0**) | `AsyncTask.drawBackMoneyForOrderCancel`: `Thread.sleep(8000)` inside an `@Async` refund | **No.** The response returns before the refund, so it is silent. It needs cancel running plus a business-level check |
| `tt-feat-17` | F17 (nested SELECT) | ts-voucher-service, Python/Tornado (**scaled to 0**) | `SELECT SLEEP(10)` on every `POST /getVoucher` (`server.py`) | **Yes, if** voucher is scaled up (Python, cheap, BELIEVED <100 MB) **and** the loadgen adds a "get voucher" call after pay. A blocking handler on a single IOLoop, BELIEVED, so requests serialise into multi-second queues |
| `tt-feat-22` | F22 (wrong column) | ts-contacts-service (running) | only in `create`/`createContacts`: a native query with `accountId` instead of `account_id`. The exception is caught and the service returns **HTTP 200 with `status:0` "Contact check failed"** | **Not in spans.** The trace error rate stays 0. It needs a loadgen "add contact" op **and** a label that counts app-level `status==0` as an error |

The other 19 flags are defined but never read. Toggling them does nothing, which is exactly why SREGym can use them as decoys. The 8-fault wiring (F1, F3, F7, F12, F14, F15, F17, F22) exists only in a third-party fork: https://github.com/rajagopal-epistak/train-ticket-test-lab/pull/1. It is unverified, and using it means pulling new images.

Also note: order and inside-payment build `new FlagdProvider()` with no host. The provider then defaults to localhost (BELIEVED), but neither service reads a flag, so this does not matter.

**Recommendation.** Pilot: **none.** Full run: include **F17** (scale voucher to 1, add a voucher op at ~5 % of the mix). **F22** goes in only once the label has an app-status error channel; it is then a good "silent failure" case. Toggle procedure:
```bash
$K get cm flagd-config -o jsonpath='{.data.flags\.yaml}' > /tmp/flags.yaml
python3 - <<'EOF'
import yaml; f='/tmp/flags.yaml'; d=yaml.safe_load(open(f)); d['flags']['tt-feat-17']['defaultVariant']='on'; yaml.safe_dump(d,open(f,'w'))
EOF
$K create cm flagd-config --from-file=flags.yaml=/tmp/flags.yaml --dry-run=client -o yaml | $K apply -f -
$K rollout restart deploy/flagd && $K rollout status deploy/flagd --timeout=60s && sleep 20
# verify the flagd side (port-forward svc/flagd 8016 first):
curl -s -X POST localhost:8016/ofrep/v1/evaluate/flags/tt-feat-17 -H 'content-type: application/json' -d '{"context":{}}'
# the canary still counts: a voucher call must take >=10 s
```
Reset: the same with `"off"`. The fault becomes active ~25–40 s after the command, so start the random delay from **verified-on**, not from the command.

---

## 4. Recommended sets

### 4.1 PILOT (laptop, ~50 episodes, answers H1)

**Targets (6):** seat, order, travel, basic, preserve, station. Their observed callers and callees (VERIFIED `archive-before-rebuild/service-graph-snapshot-33-edges.json`):
- seat ← travel, preserve; → order, config
- order ← seat, preserve, security, gateway (order list), inside-payment (pay); → DB
- travel ← gateway, preserve; → basic, seat, DB
- basic ← travel, preserve; → station, train, route, price
- preserve ← gateway; → basic, contacts, order, seat, security, travel, user
- station ← basic; → DB

**Faults (1 level each in the pilot):**

| id | Fault | Level | Why this level |
|---|---|---|---|
| F0 | none | — | pure action effect, plus drift monitoring |
| F1 | pod-kill | mode one, gracePeriod 0 | self-healing crash. B1 often catches the recovery tail |
| F2 | net-delay | 300 ms, jitter 75 ms, corr 25 | ≫ the 1.25× busy-service threshold. Survivable (well below the loadgen and nginx timeouts) |
| F3 | net-loss | 15 %, corr 25 | tail latency from retransmits, rare hard failures |
| F4 | cpu-stress | 2 workers × 100 % | starves the JVM in its 2-core cgroup and adds ~2 busy cores on a 12-CPU host |
| F5 | blackhole | 100 % egress loss | full unresponsiveness: tests the error channel and floor effects |

**Actions:** noop, restart-pod, rollout-restart, scale-up, cpu-bump, quarantine.

**Design: randomised complete blocks.**
- 7 blocks × 7 episodes = 49, plus 1 spare no-fault noop = **50**.
- A block has one fault. Block order: `none, pod-kill, delay, cpu, loss, blackhole, none`. Running `none` first and last measures overnight drift.
- In each block, all 6 actions appear once, plus **noop a second time** (in random order). That gives noop 14/50 = **28 %** and each other action 7 episodes.
- Fault target: a random permutation of the 6 targets, plus 1 random pick.
- Action target: the fault target with p = 0.5, otherwise uniform over the other 5 pilot targets (the "misdiagnosed" case). With no fault, uniform over all 6. Record `action_on_fault_target`.
- Delay: U(60, 300) s, as now.
- A discarded episode is re-run once at the end of its block with the same assignment.
- Memory guard: before scale-up or rollout-restart, WSL `available` must be ≥ 1.0 GB, otherwise discard with `low_memory`.
- Record the node of every pod, which is needed for the co-location analysis.
- Runtime: ~10–11 min per episode with M = 180 s → **~9 h, one overnight run.**

**H1 analysis (pre-register before running):**
- Outcome per episode: `C = number of services, excluding the action target and the fault target, with harm_v1 = 1` (skip `insufficient` services; analyse stall-flagged episodes separately).
- Primary test: a within-block permutation test of mean C, **{restart-pod, rollout-restart, scale-up, quarantine} vs noop** (28 vs 14 episodes).
- Secondary: each action vs noop.
- **Negative control:** cpu-bump vs noop should be ≈ 0.
- **H1 holds if** the pooled difference is ≥ 1.5 services per episode with p < 0.05 **and** at least 2 single actions have mean C ≥ 2× the noop mean. The noop false-harm rate is ~0.9 of 17 per episode (MEASUREMENT-SPEC), so this is a detectable effect at n = 7 vs 14.
- **ARC-relevant split:** classify each harmed service as (a) an upstream caller of the action target, (b) a downstream callee, or (c) neither (co-located or infrastructure). A non-zero (c) is the evidence that graph-reachability baselines are not enough.

### 4.2 FULL RUN (DGX Spark, 128 GB, ~3000 episodes)

- **Baseline replicas = 2** for the target set, ideally for all services. Memory allows it, and it makes scale-down, drain-one-instance and restart-one-of-two real. **Decide this before any full-run episode, because it changes the system.** Also bring back cancel and voucher (for F1 and F17) and more targets: add security, contacts, route, price, config, user.
- **Faults (≈12):**
  - none, pod-kill, pod-failure (hang)
  - net-delay 100/300/1000 ms, net-loss 5/15/30 %, blackhole
  - DB partition (target ↔ tsdb; DB-backed targets only)
  - cpu-stress 1×100/2×100, cpu-limit squeeze 0.25 core
  - **bad-deploy family:** a rollout whose new template carries the `heap-small`/`threads-low`/`hikari-low` config, or an F3-style `-Xmx` above a too-small memory limit, which gives an OOM loop. Here **rollback is the true fix.**
  - flagd F17, plus F22 once the app-status error channel exists
  - HTTP abort only if it passes a validity check
- **Actions (≈10):** noop, restart-pod, rollout-restart, scale-up, scale-down (2→1), cpu-bump, quarantine (or the Nacos drain), rollback (5 variants), client load-shed, restart-dependency (via target randomisation).
- Sampling as in 02 §C: uniform actions with noop at ~20 %, blocked by fault, degenerate pairs kept and flagged. Fault levels are drawn uniformly within the fault.
- **ARM64 check before committing:** confirm arm64 images for RadonDB MySQL/xenon, Nacos 2.0.1, Chaos Mesh 2.6.3, flagd and the OTel agent. The ts-* images are multi-arch (VERIFIED, RUNBOOK). SREGym has an "ARM compatible" PR (https://github.com/SREGym/SREGym/pull/1031, title VERIFIED).

---

## 5. Exact YAML and commands for the pilot

All CRs live in `train-ticket` and are deleted at teardown (the harness already does delete → wait → force the finalizer). `duration: 30m` is only a safety net.

### 5.1 Faults
```yaml
# F1 pod-kill  (already in run_episode.py)
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata: {name: arc-EP, namespace: train-ticket}
spec: {action: pod-kill, mode: one, gracePeriod: 0,
       selector: {namespaces: [train-ticket], labelSelectors: {app: TARGET}}}
---
# F2 net-delay  (already in run_episode.py; set param 300)
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata: {name: arc-EP, namespace: train-ticket}
spec:
  action: delay
  mode: all
  selector: {namespaces: [train-ticket], labelSelectors: {app: TARGET}}
  direction: to
  delay: {latency: "300ms", jitter: "75ms", correlation: "25"}
  duration: "30m"
---
# F3 net-loss
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata: {name: arc-EP, namespace: train-ticket}
spec:
  action: loss
  mode: all
  selector: {namespaces: [train-ticket], labelSelectors: {app: TARGET}}
  direction: to
  loss: {loss: "15", correlation: "25"}
  duration: "30m"
---
# F5 blackhole (same as F3 with loss "100", correlation "0")
---
# F4 cpu-stress
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata: {name: arc-EP, namespace: train-ticket}
spec:
  mode: all
  selector: {namespaces: [train-ticket], labelSelectors: {app: TARGET}}
  containerNames: [TARGET]
  stressors:
    cpu: {workers: 2, load: 100}
  duration: "30m"
```
Verification: NetworkChaos and StressChaos use the existing `AllInjected == True` check. **Add for StressChaos:** `rate(container_cpu_cfs_throttled_periods_total{pod=P}[30s])` must rise within 30 s, or the episode is discarded (this catches a silent cgroup-v2 no-op). Teardown kinds: `networkchaos`, `stresschaos`, `podchaos`.

Fallback fault (if StressChaos fails the smoke test), cpu-limit squeeze:
`$K patch pod $P --subresource resize --type=merge -p '{"spec":{"containers":[{"name":"'$T'","resources":{"limits":{"cpu":"250m"}}}]}}'`, reset with `"2"`.

### 5.2 Actions
Commands are in the §2.2 table. Harness additions:
- after restart-type actions, record `fault_on_new_pod` (§2.4)
- record `new_pod_ready_at` in the background for surge-type actions
- apply the memory guard
- reset per the table **before** the next health gate

### 5.3 Quarantine NetworkPolicy
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: arc-q-EP, namespace: train-ticket}
spec:
  podSelector: {matchLabels: {app: TARGET}}
  policyTypes: [Ingress]
  ingress: []          # deny all ingress to TARGET; its egress (Nacos, DB) is untouched
```

### 5.4 Smoke tests before the pilot (≈20 min total)
1. **StressChaos:** apply F4 to station for 90 s. Throttling rises, basic→station p95 rises, and deleting the CR restores both.
2. **NetworkPolicy:** apply §5.3 to station. New basic→station calls fail within ~10 s and station stays Ready. Delete it, and calls recover within 40 s.
3. **Fault survival:** F2 on seat, then restart-pod on seat. Check whether the new pod is in `containerRecords` and whether seat's latency is still +300 ms.
4. **Blackhole heal:** F5 on station for 3 min, then delete it. Station must be back in Nacos (`nacos-health.sh`) within 60 s.
5. **Scale-up reset:** 1→2→1 on order. The surviving pod is the older one.

---

## 6. Blockers and risks

| # | Item | Severity |
|---|---|---|
| 1 | flagd: 22 flags defined, **3 wired**, and all 3 are off our running path (cancel and voucher at 0; contacts only on create, and invisible in spans) | pilot unaffected; the full run needs a voucher scale-up, loadgen ops and an app-status error channel |
| 2 | M = 120 s truncates surge-type damage (80–130 s after the action) | **fix before the pilot**: M = 180 s |
| 3 | Unknown whether Chaos faults reach replacement pods, so restart may silently "fix" netem | record `fault_on_new_pod`; smoke test 3 |
| 4 | StressChaos on cgroup v2 + containerd has open reports (#4038) | smoke test 1; cpu-limit squeeze as fallback |
| 5 | 1.8 GB free: scale-up and rollout-restart each need +0.45 GB. Memory faults are infeasible | memory guard; no memory faults on the laptop |
| 6 | NetworkPolicy works only on new connections, and each policy change briefly drops nfqueue packets node-wide | label caveat; smoke test 2 |
| 7 | Rollback history holds a no-OTel revision and probably a 500m-CPU revision | always `--to-revision` to a seeded revision |
| 8 | Blackhole makes caller errors hit the ceiling, so action damage cannot show there | analyse separately; this is itself a finding |
| 9 | DGX Spark is ARM64: RadonDB/xenon/Nacos arm64 images are unverified | check before ordering time on it |

## Sources
- Local files: `\\wsl$\Ubuntu\home\laksh\src\xlab-train-ticket\{templates/flagd-config.yaml, templates/flagd-deployment.yaml, ts-contacts-service/.../ContactsServiceImpl.java, ts-cancel-service/.../AsyncTask.java, ts-voucher-service/server.py, ts-voucher-service/feature_flag_service.py, ts-seat-service/Dockerfile, pom.xml, deploy-job/.../yamls/deploy.yaml}`; `infra/RUNBOOK.md`; `infra/wsl-scripts/{bringup-core.sh, scale-to-core.sh, cpu-resize.sh, kind-cluster.yaml}`; `archive-before-rebuild/service-graph-snapshot-33-edges.json`; `C:\Users\Laksh\.wslconfig`
- [SREGym Problem List](https://github.com/SREGym/SREGym/blob/main/Problem%20List.md) · [SREGym problems dir](https://github.com/SREGym/SREGym/tree/main/sregym/conductor/problems) · [inject_tt.py](https://raw.githubusercontent.com/SREGym/SREGym/main/sregym/generators/fault/inject_tt.py) · [PR #1038](https://github.com/SREGym/SREGym/pull/1038) · [PR #1042](https://github.com/SREGym/SREGym/pull/1042) · [PR #1031 ARM](https://github.com/SREGym/SREGym/pull/1031)
- [train-ticket-test-lab PR #1 (8 wired faults)](https://github.com/rajagopal-epistak/train-ticket-test-lab/pull/1)
- [arXiv:2607.20005](https://arxiv.org/html/2607.20005v1) · [RCAEval arXiv:2412.17015](https://arxiv.org/html/2412.17015) · [ARBITER arXiv:2607.19182](https://arxiv.org/html/2607.19182v1) · [GuardedAct arXiv:2609.11264](https://arxiv.org/pdf/2609.11264) · [E2E-REME arXiv:2604.11094](https://arxiv.org/pdf/2604.11094)
- [kind releases (v0.24 netpol, v0.30 = k8s 1.34)](https://github.com/kubernetes-sigs/kind/releases) · [kindnet network policies](https://kindnet.es/docs/user/network-policies/) · [kube-network-policies #402](https://github.com/kubernetes-sigs/kube-network-policies/issues/402)
- [K8s 1.33 in-place resize](https://kubernetes.io/blog/2025/05/16/kubernetes-v1-33-in-place-pod-resize-beta/) · [Spring Cloud Commons 3.1 LoadBalancer cache/retry](https://docs.spring.io/spring-cloud-commons/docs/3.1.x/reference/html/)
- Chaos Mesh issues: [#4827](https://github.com/chaos-mesh/chaos-mesh/issues/4827) · [#1222](https://github.com/chaos-mesh/chaos-mesh/issues/1222) · [#4038](https://github.com/chaos-mesh/chaos-mesh/issues/4038)
