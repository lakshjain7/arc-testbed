# ARC — Decision Brief
*Synthesis of three research passes, 21 September 2026. Detail lives in reports 01–03.*

---

## Three findings that change the plan

### 1. Your machine cannot run the stack as designed

Measured on this laptop:

| | Value |
|---|---|
| Total RAM | **23.4 GB** |
| Free RAM right now | 1.7 GB |
| CPU | Intel Core Ultra 5 125H, 18 logical cores |
| GPU | **Intel integrated only — no NVIDIA** |
| Disk free (C:) | 182 GB |
| Docker VM memory today | **11.4 GiB** (WSL2 default = 50% of host) |

Computed from Train Ticket's actual manifests, the Kubernetes **scheduler admits pods on requests**, and those come to **~20 GiB plain, ~23 GiB with `--with-tracing`** (Elasticsearch alone is a fixed 2 GiB, requests == limits). The README's "24 GB" figure is for docker-compose and is not the binding constraint — the manifest requests are.

So the honest position: **23.4 GB total is below what the upstream deployment asks for**, before Windows takes its 4–6 GB. Raising `.wslconfig` to 20 GB would leave Windows 3.4 GB and you would be swapping.

This is not a tuning problem you solve in an afternoon. It decides your architecture. Options in [§ Hardware](#hardware).

Separately: **no NVIDIA GPU** — that is why `torch.cuda.is_available()` returned `False` earlier, and no PyTorch reinstall will change it. GNN training on 3000 graphs of 41 nodes is genuinely fine on CPU, so this is not urgent, but plan Colab or a lab machine for anything larger.

---

### 2. Someone published your project two months ago

**arXiv:2607.20005 — *Safe Remediation as Risk-Constrained Intervention Decision in Microservice Systems*.** Dai, Yan, Lei, Li, Zhang. Submitted 22 July 2026. **I fetched the arXiv page myself and confirmed the title, authors, date and abstract.** It is real.

What it does:

- Train Ticket, **41 services**, Kubernetes, **Chaos Mesh**, 11 fault categories
- **1,664 fault injections → 8,320 decision records**
- Action space of 12 remediation actions plus `escalate`, `wait`, `no-op`
- A **learned blast-radius model** `b(s,a)` — a diffusion kernel over powers of the adjacency matrix, supervised on whether each service deviated within 60 s of the action
- Offline RL (Conservative Q-Learning) with a constrained-MDP safety gate
- Its own gap statement: *"no prior remediation work operationalizes these dimensions within a constrained decision framework"*

That is your setup, your benchmark, your framing. Two further preprints (both verified real) crowd the same space: **arXiv:2604.09963** *Rebooting Microreboot* (April 2026) and **arXiv:2609.11264** *GuardedAct* (September 2026).

**Do not claim "first to predict blast radius of remediation actions." That claim is gone.** Read those three papers this week before writing another line of proposal.

#### What is still genuinely unclaimed

Five gaps survive, ranked by how well they hold up:

**(a) Uniformly random action selection — a validity condition, NOT a headline contribution.**
⚠️ *Corrected 21 Sep: an earlier draft of this brief called randomisation "your strongest card." That was wrong. It is methodological hygiene — the equivalent of "we used a control group." It belongs in the experimental-design section in one sentence, not in the abstract.*

What it actually buys you: 2607.20005 generates data with a softmax-over-compatibility policy (T=0.12) and only 25% uniform exploration, so action choice is **correlated with incident state** and their `b(s,a)` is fitted on confounded observational data. Random assignment makes the causal estimand identified by construction, and — the operationally important part — makes `E[ΔSLO(no-op) | fault, state]` estimable, which is what every other action's effect is measured against.

It yields exactly **one finding**, worth one ablation figure: train a model on a simulated biased-operator policy using your own data, and show it mis-ranks action damage. Not a thesis.

**(b) Per-service ΔSLO magnitude, not a binary.** Their blast radius collapses to a scalar in [0,1] from binary per-service deviation labels. *Rebooting Microreboot*'s harm is binary too. Predicting the **vector of magnitudes** is unclaimed and strictly more useful — "this rollback costs service X 40 ms of p99 and service Y nothing."

**(c) A released public dataset of (incident state, action, per-service ΔSLO).** Searched for directly; does not exist. RCAEval, Nezha, GAIA, AIOps-challenge all label *root causes*. R2Act (arXiv:2607.04623) has actions but explicitly no collateral-damage labels. The only action-outcome corpus is **fully synthetic** and its authors say so. **This may be your most durable contribution, above the model.**

**(d) Action-conditioned GNN vs. their fixed diffusion kernel.** `Σ αₖAᵏ` on a static adjacency matrix cannot represent workload-dependent propagation, asymmetric edges, or the difference between restarting a stateless replica and restarting the database. Use their kernel as a baseline.

**(e) Zero-shot transfer to an unseen topology.** Train on Train Ticket, evaluate on Online Boutique or Sock Shop. Nobody has shown this.

#### Positioning to use instead

The contribution is a **capability**, plus the dataset that makes it possible. Lead with (b) and (c), not (a).

> Given a live incident and a candidate repair action, we predict the **per-service ΔSLO cost of taking that action, before it is taken**. Existing systems output a ranked list of suspect components, a binary risk label, or the blast radius after the fact; none returns a per-service cost vector for a candidate action. We release the corpus of (incident state, action, per-service ΔSLO) records this requires, and show an action-conditioned GNN over the runtime traffic graph beats static reachability, diffusion-kernel and worst-case-simulation baselines.

Randomised assignment is how the corpus is made trustworthy, and appears as one line of experimental design.

Baselines you are now obliged to include: static downstream reachability, the 2607.20005 diffusion kernel, worst-case call-graph simulation, and a no-graph tabular regressor.

#### Two things to borrow immediately

- **Harm definition** (*Rebooting Microreboot*, use verbatim): a remediation action that causes an **SLO regression >10% for >30 s relative to the pre-action baseline**. Baseline = 60 s pre-action mean, 5 s grace after the action.
- **Blast radius is large in practice**: on Alibaba's 5,459-service trace, restarting one service touches a **median of 8 services, P99 59, max 177**. That is your motivating number.

---

### 3. Don't deploy the upstream repo — use the UIUC fork

`FudanSELab/train-ticket` master's **last commit is 2022-11-01**. Recent issues (#299, #306, #308, #310–312) all have **zero replies**. The MySQL chart (RadonDB/xenon, 3-replica Raft) is the dominant failure mode across the issue tracker and appears to break on Kubernetes ≥ 1.25.

**[xlab-uiuc/train-ticket](https://github.com/xlab-uiuc/train-ticket)** — last push **2026-04-15** — ships a real Helm chart, images on GHCR instead of the flaky `codewisdom` Docker Hub org, Jaeger + Prometheus + Grafana, and `flagd-config.yaml` defining **22 OpenFeature flags `tt-feat-01`…`tt-feat-22`** — the 22 Fudan industrial faults as *runtime-togglable flags*, no rebuild, no branch switching.

It belongs to **[SREGym](https://github.com/SREGym/SREGym)** (UIUC, MIT licence, last push 2026-09-19, arXiv:2605.07161), which documents an **8 vCPU / 16 GB floor for "SREGym-Lite"** on `kind`. That is the only configuration in this whole research pass that fits your laptop.

It uses `kind`, not `k3d`. You have installed neither, so switching costs you nothing.

---

<a name="hardware"></a>
## Hardware: pick one

| Option | Viability | Notes |
|---|---|---|
| **A. SREGym-Lite on this laptop** | ✅ Plausible | 8 vCPU / 16 GB claimed floor. Reduced deployment, shortened Prometheus retention. **Pilot this first — it is the cheapest test of whether anything runs at all.** |
| **B. Full upstream on this laptop** | ❌ No | ~23 GiB of requests vs 23.4 GB total. Pods will sit `Pending`. |
| **C. Lab machine / university server** | ✅ Best | 32 GB comfortable. **Raise with your guide now — procurement takes weeks and is on the critical path.** |
| **D. Cloud (GKE/EKS spot, or a single 32 GB VM)** | ✅ Works | Costs money; 3000 episodes is ~400 h serial. |

**Throughput reality check:** 3000 episodes × 8 min = **400 hours ≈ 16.7 days serial**, before teardown and health-gating (budget another 60–90 s per episode). Four parallel clusters gets you to ~4 days. Plan for this now, not at episode 500.

---

## The stack, decided

| Layer | Tool | Why |
|---|---|---|
| Cluster | **kind** (if SREGym) or k3d | k3s ships `local-path` as default StorageClass — **OpenEBS is not required**, contrary to the README |
| App | **xlab-uiuc/train-ticket** | maintained; Helm; flagd faults |
| Traces + graph | **SkyWalking 8.5** (upstream) or **Jaeger + OTel servicegraph connector** (fork) | see below |
| Resource metrics | **kube-prometheus-stack** | you need **kube-state-metrics** for restart counts; TT's bundled Prometheus does not deploy it, so **skip `--with-monitoring`** |
| Fault injection | **Chaos Mesh** | only tool of the four with a JVM fault primitive; CRD-per-experiment maps 1:1 onto an episode with finalizer-guaranteed revert |
| Episode store | **SQLite (or Postgres+JSONB)** → **Parquet + DuckDB** | not W&B — see below |
| Graph inspection | **networkx** + **pyvis** (interactive) + **Graphviz** (thesis figures) | networkx is the hub; converts to PyG, pyvis and dot |
| Model tracking, later | MLflow or W&B | only for GNN training runs, not episodes |

### On the service graph — the question you asked earlier

**SkyWalking answers it natively.** Verified metric names from `core.oal` in both v8.5.0 and master:

```
service_relation_client_cpm          # calls per minute  → your call_rate
service_relation_server_cpm
service_relation_client_call_sla     # success %         → error_ratio = 1 − sla/100
service_relation_server_call_sla
service_relation_client_resp_time
service_relation_server_percentile
```

Topology via `getGlobalTopology(duration:{start,end,step})` — `step` is your per-episode window knob. Query `POST http://<oap>:12800/graphql`, no auth in the shipped config.

Two gotchas: **`Topology.calls` carries no metrics**, so you need a second `readMetricsValues` call per edge (~200 GraphQL calls per episode — batch with aliases). And **SkyWalking 8.5.0 has neither MQE nor the PromQL Service** (9.5.0 and 9.4.0 respectively). Bump the OAP image to 9.7+/10.x and both stacks speak PromQL, which makes your collection code identical either way.

**OTel alternative:** the servicegraph connector emits `traces_service_graph_request_total` / `..._failed_total` labelled `client`/`server`, so **one PromQL range query returns the whole graph for a window** instead of 200 GraphQL calls. But Train Ticket does not emit OTLP; you would swap the agent initContainer. ⚠️ Its defaults `store.ttl: 2s` / `max_items: 1000` are far too small for Train Ticket's deep chains — raise to 30 s / 100000 and **watch `traces_service_graph_unpaired_spans_total`, or your graph is silently wrong**.

### On `saturation` — you were right to doubt it

**Not obtainable from stock Train Ticket.** Verified from `ts-order-service/pom.xml` and `application.yml`: **no Actuator, no Micrometer, no `management:` section.** There is no `/actuator/prometheus`, so HikariCP's pool metrics have nowhere to go.

**Use SkyWalking's JVM thread metrics as the proxy — free, works today, no rebuild:**

```
instance_jvm_thread_blocked_state_thread_count        ← saturation proxy
instance_jvm_thread_timed_waiting_state_thread_count  ← pool-exhaustion proxy
instance_jvm_thread_live_count
instance_jvm_cpu, instance_jvm_memory_heap / _heap_max
```

When HikariCP exhausts its pool, requesting threads park in `TIMED_WAITING` on `getConnection()` — you will see it. Causally linked, not a direct gauge. **Say so explicitly in the write-up.** The alternative (add Actuator + Micrometer, rebuild 41 images, Spring Boot 1.5.x needs Micrometer 1.0.x) is only worth it if pool saturation becomes a headline variable.

### On "wandb, but for this?"

**W&B is the wrong shape.** W&B, MLflow, Comet and Aim are built around a *run emitting a time-series of scalars*. Your episode is a *record* — a structured document holding a graph. A 41-node JSON graph becomes an opaque artifact blob you cannot query.

Do the arithmetic: 3000 × 100 edges × 6 floats ≈ 1.8M numbers ≈ **25 MB**, maybe 400 MB with JSON overhead. **This is a small dataset.** Anything saying "Spark", "data lake" or "object store" is wrong by an order of magnitude. And **Neptune's hosted service shut down in March 2026** — do not build on it.

**Two tiers:**

- **Collection — SQLite** (single-process) or **Postgres + JSONB** (parallel collectors). The thing that will actually hurt you is a crash at episode 1,847, so write each episode transactionally with a `status` column the moment it completes.
- **Analysis — export flat `edges.parquet` / `nodes.parquet` / `episodes.parquet`, query with DuckDB.** Zero ingest, zero resident memory on an already-full box, and flat edge rows are exactly what PyTorch Geometric wants. This tier is throwaway and regenerable; all truth lives in tier 1.

**Not Neo4j.** Graph databases are for traversing *one big graph*. You have 3000 independent tiny ones and never traverse across them. It would cost 1–2 GB of RAM you do not have.

**Two design warnings that will bite you:**
1. Build **one global `service → node_index` map** across all episodes. Index per-episode and node 7 means a different service in different graphs, and the GNN learns nothing.
2. When a fault kills a pod, that service **vanishes from the SkyWalking topology**. Decide deliberately: drop it (variable node count) or keep it with zeroed features and an `is_alive` flag (constant node count). The latter is almost always right.

**Chaos Mesh's own dashboard does not replace this.** It records what was *injected*, never what *happened*. Every chaos tool tracks the independent variable; none tracks the dependent one. Your episode store exists to join them, and that join **is** your dataset. Do copy Chaos Mesh's resolved spec + `uid` + actual start/end into your `fault_spec` column — that is ground truth on what ran, which differs from what you intended when injection fails.

---

## Fault set — 12 types

Constraints: realistic, measurable but survivable, cleanly reversible in 8 minutes, **pod-scoped** so episodes stay isolated.

| # | Fault | Mechanism | Levels |
|---|---|---|---|
| 1 | Network delay | `NetworkChaos delay`, `direction: to` | 50 / 200 / 800 ms |
| 2 | Packet loss | `NetworkChaos loss` | 1 / 5 / 20 % |
| 3 | Bandwidth throttle | `NetworkChaos bandwidth` | 10 / 1 / 0.25 mbps |
| 4 | Service partition | `NetworkChaos partition`, `direction: both` | binary |
| 5 | External dependency timeout | `NetworkChaos delay` + `externalTargets` | 5 s / 30 s / partition |
| 6 | CPU saturation | `StressChaos cpu` | workers 1/2/4 × load 50/80/100 |
| 7 | Memory pressure | `StressChaos memory` + `oomScoreAdj` | 40 / 65 / 85 % of limit |
| 8 | Pod kill | `PodChaos pod-kill`, `gracePeriod: 0` | mode one / fixed:2 |
| 9 | Pod hang | `PodChaos pod-failure` | 60 / 180 / 300 s |
| 10 | Container kill | `PodChaos container-kill` | — |
| 11 | Config fault | `kubectl patch` env/ConfigMap | F3 `-Xmx` > limit; F15 body size 200 B; F16 upload cap |
| 12 | Code fault | `kubectl set image` to a faulty build / flagd flag | F6, F10, F12, F17, F20, F22 |

**Exclude:** IOChaos `mistake` (docs say "may damage your data"), IOChaos on DB volumes (EIO mid-write leaves inconsistent datafiles), DNSChaos (JVM DNS cache makes it non-deterministic), TimeChaos (corrupts JWTs *and your own telemetry*), KernelChaos (needs `CONFIG_BPF_KPROBE_OVERRIDE`, node-scoped, impossible on k3d), BlockChaos (hand-compiled kernel module).

**Restrict pod-kill to stateless services.** Killing a single-instance MySQL with a PVC gives unbounded InnoDB crash recovery.

**Adopt SREGym's ambient noise:** two low-impact disturbances every 5 minutes, each lasting 2 minutes, on services unrelated to the injected fault. Without it your model learns an unrealistically clean signal.

### The representativeness caveat you must state in the paper

**Only ~6 of the 22 Fudan industrial faults are reachable by infrastructure chaos** (F3, F5, F7, F15, F16, partly F4/F17). The other 16 are code and data faults. *Chaos-Mesh-only fault sets are not representative of the industrial distribution.* The flagd flags in the UIUC fork are the fix — they give you the real code faults without rebuilding.

### Pilot before designing around it

**JVMChaos is the most Java-relevant fault class and the most likely to fail.** Train Ticket's Dockerfiles use `FROM java:8-jre` — a JRE image has no attach tooling, and Chaos Mesh issues #3330, #2751, #3676 document Byteman attach failures when the Java PID is not 1. If you want it, rebuild on a JDK base with `-XX:+StartAttachListener`. Budget a day, and make it a hard go/no-go.

---

## Action set — 8 actions

The **collateral-damage mechanism is the substance of your thesis** — each row is a causal story the model should learn.

| # | Action | Call | Damage mechanism |
|---|---|---|---|
| **0** | **no-op** | *(record only)* | **Counterfactual baseline. Mandatory.** Without it you cannot separate "the action helped" from "the fault was self-limiting." Gunawi SoCC'16: 12% of documented fixes were no-action. **Over-sample to ~20%.** |
| 1 | restart-pod | `kubectl delete pod --grace-period=0 --force` | in-flight requests RST; **JVM cold start up to 10× slower for ~90 s**; JIT storm burns CPU on a saturated node; losing 1 of N replicas shifts load onto survivors — the classic path into a metastable retry storm |
| 2 | scale-up | `kubectl scale --replicas=R+2` | **Connection-pool storm.** Each pod runs its own Hikari pool; 10 replicas × pool 20 = 200 connections, which can exceed `max_connections`. **Train Ticket has exactly the topology for this — the cleanest damage story in the design.** |
| 3 | scale-down | `kubectl scale --replicas=R-1` | capacity removal under degradation → metastable tipping. Legitimate for quarantining a bad replica, so not a pure "bad action" — valuable signal |
| 4 | rollback | `kubectl rollout undo` | **Reintroduces the old bug.** F20 (shared-library enum skew across services) is the perfect illustration: rolling back one service desynchronises it from its unrolled peers. Plus full rolling cold start |
| 5 | resource-bump | `kubectl patch --subresource resize` (≥1.33) | scheduling pressure, node eviction. ⚠️ **On k8s < 1.33 this secretly triggers a full rolling restart** and is confounded with action 1 — check your version |
| 6 | circuit-break | Istio `DestinationRule outlierDetection` | **If the fault is systemic, every replica 5xxs and outlier detection ejects 100% of endpoints — partial degradation becomes total outage** |
| 7 | rate-limit | Istio `EnvoyFilter local_ratelimit` | **The 429s are themselves SLO violations.** Define SLO as success-rate AND latency, or load-shedding looks free. Limits are per-proxy, so effective limit is N× what you set |

**Without Istio,** substitute: circuit-break → a `NetworkPolicy` quarantining the sick service; rate-limit → scaling the load generator down. Less faithful, keeps the mechanism class.

**Exclude for v1:** cordon+drain (on k3d with `local-path` PVCs, DB pods pinned to the drained node **cannot reschedule at all**; `uncordon` does not bring pods back), clear-cache (irreversible, and Train Ticket's Redis usage is thin — verify there is a mechanism before including), failover-database (no replica exists to fail over to), abort-rollout (needs Argo Rollouts across 41 services).

**Pin `revisionHistoryLimit` explicitly** and seed each namespace with a known 2-revision history at episode start — the default of 10 means older revisions silently vanish.

---

## Sample the degenerate cells. Do not prune.

Roughly 35–40% of the 12 × 8 grid is "degenerate" — the action has no causal path to the fault's mechanism (rollback under network delay; scale-up under a partition). Sample them anyway, uniformly:

1. **Pruning destroys the randomisation.** The moment cells are pruned, fault and action are confounded and the model learns your pruning policy, not the causal effect. This is the one thing your design has that 2607.20005 does not — do not throw it away.
2. **Degenerate cells are where you learn the action's main effect.** ΔSLO(restart | unrelated fault) ≈ what a restart costs, full stop. You need that to decompose ΔSLO = f(action) + g(fault) + h(action×fault).
3. **"Obviously unrelated" is a hypothesis.** Restarting under CPU stress *helps*, because Chaos Mesh's stressor process lives in the old container and dies with it. The "wrong" action accidentally works. Prune on intuition and you prune exactly the interesting results.
4. **Real SREs take degenerate actions constantly** — Google's whole "generic mitigations" argument is *apply a broad mitigation before you know the root cause*. A predictor that has only seen well-matched pairs is useless for the case it exists to serve.

Practical: uniform over actions (~375 episodes each, ~31 per cell), no-op bumped to 20%, **randomise the action delay** (time from injection to action, uniform over 60–300 s) or you silently condition on it, and record `degenerate_expected` as a metadata **column, not a filter** so you can report it as an evaluation slice.

---

## Risks, ranked

| Risk | Severity |
|---|---|
| **23.4 GB laptop below the ~23 GiB the manifests request** | 🔴 Blocking — decide hardware this week |
| **arXiv:2607.20005 occupies the framing** | 🔴 Blocking — read it, then reposition on randomisation |
| **Chaos Mesh pointed at the wrong containerd socket → experiments silently succeed while killing nothing** | 🔴 High — would poison the dataset invisibly. k3s socket is `/run/k3s/containerd/containerd.sock` |
| Chaos-daemon loses the socket inode after a containerd restart mid-run (issue #3072) | 🟠 Silent partial corruption over a multi-day run. Add a per-episode canary: inject a trivial pod-kill on a scratch pod, assert it died |
| JVMChaos will not work on stock `java:8-jre` images | 🟠 Removes the most Java-relevant fault class |
| Only ~6 of 22 industrial faults are infra-injectable | 🟠 Representativeness claim |
| resource-bump is secretly a full restart on k8s < 1.33 | 🟠 Confounds two actions |
| 400 h serial wall-clock for 3000 episodes | 🟠 Plan parallel clusters now |

**Episode teardown must:** delete the chaos CR → poll until gone with a timeout → force the finalizer on timeout (`chaos-mesh.chaos-mesh.org/cleanFinalizer=forced`) → **assert cluster health against a baseline probe before the next episode** → redeploy the namespace if unhealthy. Without the last two you get correlated contamination across consecutive episodes, which destroys the i.i.d. assumption the model needs.

---

## This week, in order

1. **Read arXiv:2607.20005, 2604.09963, 2609.11264.** Everything else is premature until you know what is left to claim.
2. **Raise hardware with your guide.** Longest lead time, on the critical path.
3. **Pilot SREGym-Lite** (`kind`, 8 vCPU / 16 GB) on this laptop. Cheapest possible test of whether anything runs.
4. If it comes up: book a ticket by hand, then confirm `getGlobalTopology` (or Jaeger) returns ~40 nodes and ~100 edges. **That single check validates the entire agent → collector → topology pipeline.**
5. Install Chaos Mesh with the right socket path, inject one `NetworkChaos` delay, and watch the topology change. **This is the moment the project becomes real.** Do it together.

Stop there.

---

## Chase list — unverified, worth an hour each

- **arXiv:2604.11094 (E2E-REME)** — PDF would not parse. Name promises simulated remediation outcomes. **Could be very close. Chase first.**
- **DOI 10.1007/s44163-026-01213-3** — Springer, GNN service-dependency + failure-propagation prediction. Paywalled.
- **AIOps Challenge 2023** — reported to annotate **80 cascading propagation faults**. Closest public thing to impact labels.
- Whether Chaos Mesh **NetworkChaos** and **StressChaos** work under the WSL2 kernel. **Test before committing to the fault set.**
- Whether `make deploy` succeeds end-to-end on k3d today at all — issues #232/#233/#234/#252/#268/#293 suggest the MySQL chart is the blocker on k8s ≥ 1.25.
