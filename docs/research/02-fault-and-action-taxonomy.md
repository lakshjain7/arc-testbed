I have enough material. Here is the full report.

---

# Fault & Action Taxonomy for a Train-Ticket Blast-Radius Dataset

**Legend:** ✅ **VERIFIED** = directly supported by a cited source I read. 🟡 **BELIEVED** = my engineering inference, standard practice, or extrapolation — test it before you rely on it.

---

# PART A — FAULT TAXONOMY

## A.1 The empirical literature on real microservice / cloud failures

### A.1.1 The Fudan study behind Train Ticket (the canonical citation for your benchmark)

✅ **VERIFIED.** Zhou, Peng, Xie, Sun, Ji, Li, Ding — *"Fault Analysis and Debugging of Microservice Systems: Industrial Survey, Benchmark System, and Empirical Study"*, **IEEE TSE 47(2): 243–260, 2021** (online 2018).
- IEEE Xplore: https://ieeexplore.ieee.org/document/8580420/
- ACM DL: https://dl.acm.org/doi/10.1109/TSE.2018.2887384
- dblp: https://dblp.org/rec/journals/tse/ZhouPXSJLD21.html
- Project page: https://fudanselab.github.io/research/MSFaultEmpiricalStudy/
- PDF: https://cspengxin.github.io/publications/tse19-msdebugging.pdf

Method: **face-to-face interviews with 16 participants from 12 companies**, yielding **22 typical industrial fault cases**, replicated onto TrainTicket (**41 business microservices**, Java/Python/Node.js/Go, sync + async + message-queue interaction modes).

Replication repo: https://github.com/FudanSELab/train-ticket-fault-replicate

### A.1.2 The 22 industrial fault cases, enumerated

✅ **VERIFIED** against two independent Fudan sources: the repo README (https://github.com/FudanSELab/train-ticket-fault-replicate) and the wiki (https://github.com/FudanSELab/train-ticket/wiki/Fault-Description).

⚠️ **Caveat:** the wiki/README descriptions and the project-page descriptions **disagree on several IDs** (notably F1↔F2, F11, F14, F15, F16, F20). The project page (https://fudanselab.github.io/research/MSFaultEmpiricalStudy/) describes the *original industrial* fault; the repo describes the *TrainTicket replication*. Where they differ I give both.

| ID | Repo branch name | Repo/wiki description (TrainTicket replication) | Project-page description (original industrial fault) | Injectable by infra chaos? |
|---|---|---|---|---|
| **F1** | `ts-error-process-seq-F1` | Asynchronous tasks in a single request sent without message-sequence control → out-of-order completion. Services: Ticket-Cancel, Inside-Payment, Order | "Messages are displayed in wrong order" — async messaging lacks sequence control | ❌ code-level |
| **F2** | `ts-error-reportui-F2` | Multiple requests return in a different order than sent; UI shows stale/incorrect info (no order validation) | Report data returns in unexpected order across multiple requests | ❌ code-level (🟡 approximable by per-call NetworkChaos delay) |
| **F3** | `ts-error-docker-JVM-F3` | **JVM `-Xmx` larger than the Docker/cgroup memory limit** → periodic OOM-kill and service unavailability | "JVM configurations are inconsistent with Docker configurations" | ✅ **config-level, directly reproducible** |
| **F4** | `ts-error-ssl-F4` | SSL/TLS offloading at fine granularity → very long response times for complex requests | SSL offloading per Docker instance | 🟡 approximable by latency injection |
| **F5** | `ts-error-cross-timeout-status(chance)-F5` | **Thread-pool exhaustion**: high load of request type A starves type B → timeouts. Service: Basic-Info | "High load of a type of requests causes the timeout failure of another type" | ✅ **approximable (noisy-neighbour load + CPU stress)** |
| **F6** | `ts-error-F6` | SQL errors trigger **endless recursive retries** of a microservice → timeout failure. Service: Voucher | Same | 🟡 approximable (fault-inject DB errors + existing retry code) |
| **F7** | `ts-external-normal-F7` | **Third-party/external service timeout** (payment / external ticket service) | Third-party overload → denial of service | ✅ **NetworkChaos `externalTargets` partition/delay** |
| **F8** | `ts-error-redis-F8` | Wrong/missing **key/token read from Redis** delivered to dependent services (VIP auth) | Request keys not propagated to dependent microservices | ❌ code/data-level |
| **F9** | `ts-error-F9` | CSS **bidirectional (RTL) text display error** in login module | Same | ❌ UI-only, no SLO signal |
| **F10** | `ts-error-logic-F10` | Incorrect API invocation in an unhandled special case. Service: Contacts | API returns unexpected output during BOM updates | ❌ code-level |
| **F11** | `ts-error-bomupdate-F11` | Uncontrolled value-setting sequence + inconsistent recheck → intermittent fault in order-cancellation | BOM tree becomes erroneous after updates | ❌ code-level |
| **F12** | `ts-error-processes-seq-status(chance)-F12-Final` | **State-dependent rejection**: locked stations / thread-pool size cause request rejection. Service: Order | Microservice output not handled in call chain | 🟡 partial |
| **F13** | `ts-error-queue-F13` | Fast successive requests processed **out of order** when dependent on prior results | Price-optimization steps execute in unexpected order | ❌ code-level |
| **F14** | `ts-error-F14` | Wrong **price-calculation** methodology | Locked products wrongly included in CPI calculation | ❌ silent-corruption, no SLO signal |
| **F15** | `ts-error-F15` | **nginx `client_max_body_size`/JSON post size capped at 200 bytes** → valid requests blocked (food/consignment ordering) | Spark actor misconfigured instead of system actor | ✅ **config-level, directly reproducible** |
| **F16** | `ts-error-F16` | **Spray `max-content-length` = 2 MB** → bulk route upload rejected | Same as project page | ✅ config-level |
| **F17** | `ts-error-F17` | **Too many nested SELECT/FROM** → query exceeds client timeout. Service: Voucher | Same | 🟡 approximable (IOChaos latency on DB volume / JVMChaos mysql latency) |
| **F18** | `ts-error-F18` | UI chart JSON contains **null** and consumer assumes non-null → render error (train food) | Same | ❌ code-level |
| **F19** | `ts-error-F19` | **French locale price formatting** wrong (package consignment) | Same | ❌ no SLO signal |
| **F20** | `ts-error-F20` | **Shared-library version mismatch**: same order status has different enum value across services | JBoss classpath missing DB2 jar | ❌ code/deps-level (🟡 *very* relevant to "rollback reintroduces bug" action) |
| **F21** | `ts-error-F21` | Missing/unlocatable `aria-labelledby` → screen reader fails (login verification code) | JAWS cannot locate aria element | ❌ no SLO signal |
| **F22** | `ts-error-F22` | **Wrong column name** in constructed SQL → voucher printing fails | Same | ❌ code-level |

**What this tells you for dataset design (🟡 my read):** only **~6 of 22** industrial faults are reachable by infrastructure-level chaos (F3, F5, F7, F15, F16, and partially F4/F17). The other 16 are *code and data* faults. This is the single most important honest caveat for your paper: **Chaos-Mesh-only fault sets are not representative of the Fudan industrial distribution.** Two mitigations:
1. Use the `train-ticket-fault-replicate` branches as a *second* fault family — each branch is a deployable image, so "inject fault" = `kubectl set image` to the faulty build. This is fully reversible (set image back), fits in 8 minutes, and gives you genuinely realistic code faults.
2. Include at least the config-level faults (F3, F15, F16) which are one-line ConfigMap/env edits.

### A.1.3 Other empirical failure studies worth citing

| Study | Venue / URL | Scale | Key numbers you can cite |
|---|---|---|---|
| **Gunawi et al., "Why Does the Cloud Stop Computing? Lessons from Hundreds of Service Outages"** | SoCC'16 — https://dl.acm.org/doi/10.1145/2987550.2987583 · PDF https://ucare.cs.uchicago.edu/pdf/socc16-cos.pdf · summary http://muratbuffalo.blogspot.com/2016/11/why-does-cloud-stop-computing-lessons.html | **597 outages, 32 services, 2009–2015**, 1247 postmortems/news reports | ✅ Root causes ranked: **UPGRADE > NETWORK > BUGS > CONFIG > LOAD > CROSS-service**; POWER 6%, natural disaster 3%; **59% unknown root cause**. Impact: full outage 59%, essential-ops failure 22%, **performance glitch 14%**, data loss 2%. **Fix procedures (only 24% documented): fix-software 22%, fix-hardware 22%, restore-data 14%, add-resources 10%, rollback-software 8%, fix-misconfig 7%, restart 4%, no-action 12%.** ← *this is a citable empirical prior over your ACTION set* |
| **Liu, Lu, Musuvathi, Nath — "What bugs cause production cloud incidents?"** | HotOS'19 — https://dl.acm.org/doi/10.1145/3317550.3321438 · PDF https://people.cs.uchicago.edu/~shanlu/paper/hotos19_azure.pdf | **112 high-severity Azure incidents**, Mar–Sep 2018 | ✅ **~40% of incidents caused by software bugs.** Among fault-related incidents: **error component 43%, unresponsive/hanging component 29%, silent corruption 17%** |
| **Dogga et al., "AutoARTS: Taxonomy, Insights and Tools for Root Cause Labelling of Incidents in Microsoft Azure"** | USENIX ATC'23 — https://www.usenix.org/conference/atc23/presentation/dogga · taxonomy browser https://autoarts-rca-taxonomy.github.io/ | **2000+ incidents, 450+ Azure services** | ✅ Hierarchical taxonomy with **346 root-cause categories** (e.g. `Architecture.ColdStart`); argues single-root-cause labelling is inadequate — incidents are multi-label |
| **Ghosh et al., "How to Fight Production Incidents? An Empirical Study on a Large-scale Cloud Service"** | SoCC'22 — https://www.microsoft.com/en-us/research/publication/how-to-fight-production-incidents-an-empirical-study-on-a-large-scale-cloud-service/ · PDF https://www.microsoft.com/en-us/research/wp-content/uploads/2022/09/3542929.3563482.pdf | Hundreds of high-sev Azure incidents | ✅ Focuses on detection/triage/mitigation lifecycle |
| **Bronson, Aghayev, Charapko, Zhu — "Metastable Failures in Distributed Systems"** | HotOS'21 — https://sigops.org/s/conferences/hotos/2021/papers/hotos21-s11-bronson.pdf · https://dl.acm.org/doi/10.1145/3458336.3465286 · follow-up ;login: https://www.usenix.org/publications/loginonline/metastable-failures-wild | — | ✅ **Directly load-bearing for your thesis.** A metastable failure = self-sustaining congestive collapse: the system degrades under a transient trigger and **fails to recover after the trigger is removed**, because of a *sustaining effect* (retry storms, cache-miss amplification). This is the precise mechanism by which a *remediation action* can be the trigger that pushes a vulnerable system into a permanent-overload state. Also: Isaacs & Alvaro, "Analyzing Metastable Failures", HotOS'25 — https://sigops.org/s/conferences/hotos/2025/papers/hotos25-106.pdf |
| **Zhou et al. / Fudan (above)** | TSE'21 | 22 cases | see A.1.2 |
| **Peer benchmarks that chose fault sets for Train Ticket** | | | See A.1.4 |

### A.1.4 What *other researchers* actually inject into Train Ticket (best prior art for your fault set)

| Benchmark | Fault set | URL |
|---|---|---|
| **RCAEval** (ASE'24 / WWW'25 / FSE'26) | RE1: **CPU, MEM, DISK, DELAY, LOSS** × 5 services × 5 reps. RE2 adds **SOCKET**. RE3: code-level faults. Total **735 failure cases, 11 fault types** across 3 suites | https://arxiv.org/pdf/2412.17015 · https://github.com/phamquiluan/RCAEval |
| **Nezha** (multimodal RCA, TrainTicket + OnlineBoutique) | **CPU contention, CPU consumption, network delay** + **code-level return-value and exception injection** for Java and Python | https://github.com/IntelligentDDS/Nezha |
| **AIOpsLab** (MSR / Berkeley / UIUC / IISc) | network partitions, resource exhaustion, misconfigurations; 4 tasks incl. **mitigation** where the agent may "update configuration or rollback to a previous version"; orchestrator can "scale-up, redeploy" via helm/kubectl. Mitigation runs averaged ~216 s | https://arxiv.org/pdf/2501.06706 · https://www.microsoft.com/en-us/research/blog/aiopslab-building-ai-agents-for-autonomous-clouds/ |
| **SREGym** (2026, uses Train Ticket) | ✅ **closest precedent to your design.** Table-1 taxonomy: *process/container* (kill pods, temporal pod failures), *hardware/OS* (resource stress = fail-slow, eBPF syscall failure, disk-sector corruption), *config* (service mis-deployment, app config error, k8s config error), *application* (code bugs, operator misconfig, service overload), *network* (latency, packet drop, jitter). Plus **ambient noise: two noise patterns randomly injected every 5 minutes, each lasting 2 minutes** (pod crashes, dropped requests, noisy neighbours) so agents must distinguish signal from background. Apps: DeathStarBench Hotel/Social, **Train Ticket**, Astronomy Shop, 2 in-house | https://arxiv.org/pdf/2605.07161 · https://arxiv.org/html/2605.07161v1 |
| **ITBench** (IBM) | 59 Kubernetes incident tasks (40 public + 19 private) | https://github.com/itbench-hub/ITBench |

🟡 **Recommendation:** adopt SREGym's **ambient-noise idea**. Without background noise your model will learn an unrealistically clean ΔSLO signal.

### A.1.5 Industry outage taxonomies

✅ **Gremlin** — https://www.gremlin.com/docs/fault-injection-experiments — three categories, 11+ experiments:

| Category | Experiments |
|---|---|
| **Resource** | CPU (cores, load %), Memory (size), GPU, IO (ops/sec), Disk (fill %), Process Exhaustion (PID count) |
| **State** | Shutdown (+optional reboot), Time Travel (clock offset), Process Killer |
| **Network** | Blackhole (drop all matching traffic), Latency (delay + jitter), Packet Loss (%), DNS (block DNS servers), Certificate Expiry |

✅ **Google SRE** — the "generic mitigations" framing (see Part B.1) is the industry-standard *response* taxonomy: https://sre.google/workbook/incident-response/ · https://www.oreilly.com/content/generic-mitigations/

---

## A.2 What Chaos Mesh can actually inject — precise CRD reference

Chaos types available: `awschaos, azurechaos, blockchaos, dnschaos, gcpchaos, httpchaos, iochaos, jvmchaos, kernelchaos, networkchaos, physicalmachinechaos, podchaos, stresschaos, timechaos` (✅ https://chaos-mesh.org/docs/basic-features/ · API ref https://chaos-mesh.dev/reference/master/).

### A.2.1 PodChaos ✅
Docs: https://chaos-mesh.org/docs/simulate-pod-chaos-on-kubernetes/

| Field | Values |
|---|---|
| `action` | `pod-failure` \| `pod-kill` \| `container-kill` |
| `mode` | `one` \| `all` \| `fixed` \| `fixed-percent` \| `random-max-percent` (+ `value`) |
| `duration` | e.g. `"30s"` |
| `gracePeriod` | int64, **pod-kill only**, default 0 |
| `containerNames` | []string, **container-kill only** |
| `selector` | namespaces + labelSelectors |

**Mechanism & gotchas (✅ from docs):**
- `pod-failure` works by **replacing the container image with a pause image** (`gcr.io/google-containers/pause:latest` by default). ⚠️ **Download time eats into the experiment duration.** ⚠️ **On an air-gapped or bandwidth-limited k3d cluster this can silently fail or be very slow** — pre-pull the pause image into the k3d image store (`k3d image import`) and override `--set controllerManager.podChaos.podFailure.pauseImage=`.
- ⚠️ Containers **without `command`, `livenessProbe`, or `readinessProbe` can appear `Running`/`Ready` while functionally dead**. Train Ticket's stock manifests are thin on probes — 🟡 you should add readiness probes or your ΔSLO ground truth will be inconsistent with pod status.
- `pod-kill` on a bare Pod (no ReplicaSet) never recovers. Train Ticket uses Deployments, so fine.
- ⚠️ Known bug: pod stuck in `Terminating` prevents the pause-image patch — https://github.com/chaos-mesh/chaos-mesh/issues/4519

**k3s/containerd:** ✅ works, but see A.2.11.

### A.2.2 NetworkChaos ✅
Docs: https://chaos-mesh.org/docs/simulate-network-chaos-on-kubernetes/

| Action | Required params | Optional |
|---|---|---|
| `delay` | `latency` (e.g. `"200ms"`) | `correlation` 0–100, `jitter` (default `0ms`), `reorder{reorder, correlation, gap}` |
| `loss` | `loss` "0"–"100" | `correlation` |
| `duplicate` | `duplicate` "0"–"100" | `correlation` |
| `corrupt` | `corrupt` "0"–"100" | `correlation` |
| `bandwidth` | `rate` (e.g. `"1mbps"`), `limit` (bytes in queue), `buffer` (max instantaneous bytes) | `peakrate`, `minburst` |
| `partition` | — | `direction`, `target`, `externalTargets` |

Common: `direction` = `to` \| `from` \| `both` (default `to`); `target` (second selector — the *other* side of the pair); `externalTargets` (IPs/domains **outside** the cluster — this is how you reproduce **F7, third-party payment timeout**); `device` (NIC name).

**Gotchas:**
- ⚠️ `partition` direction semantics are buggy / behave like `both` in some versions — https://github.com/chaos-mesh/chaos-mesh/issues/4477 and https://github.com/chaos-mesh/chaos-mesh/issues/3204
- ⚠️ `error while flushing ip sets for containerID` on containerd — https://github.com/chaos-mesh/chaos-mesh/issues/3275
- ⚠️ NetworkChaos sometimes fails to recover — https://github.com/chaos-mesh/chaos-mesh/discussions/4019
- 🟡 `delay` is applied with `tc netem` on the pod's netns **egress**. If you inject on caller A `direction: to, target: B`, you delay A→B. To delay everything into B, inject on B with `direction: from` — but given the direction bugs, **prefer injecting egress delay on the caller and verifying with a probe.**

### A.2.3 StressChaos ✅
Docs: https://chaos-mesh.org/docs/simulate-heavy-stress-on-kubernetes/

```yaml
spec:
  mode: one
  duration: "120s"
  selector: {namespaces: [tt], labelSelectors: {app: ts-order-service}}
  stressors:
    cpu:    {workers: 2, load: 80, options: []}      # total load = workers × load
    memory: {workers: 1, size: "256MB", time: "10s", oomScoreAdj: -1000, options: []}
  stressngStressors: "--clone 2"     # raw stress-ng passthrough
  containerNames: ["ts-order-service"]
```
- ✅ Chaos Mesh uses a **custom memory stress tool** (not stress-ng's, to avoid the CPU cost of read/write pressure) that consumes real memory.
- ⚠️ 🟡 **The stressor runs inside the target container's cgroup.** With Train Ticket's `-Xmx200m` JVMs in small-limit containers, a memory stressor will trigger **OOMKill of the container, not a graceful slowdown** — and the OOMKill victim may be the *JVM*, not the stressor, unless you set `oomScoreAdj`. This makes memory stress **not cleanly reversible** (it becomes an implicit container-kill + JVM cold start, contaminating your ΔSLO attribution). Set `oomScoreAdj` high (positive = more likely to be killed) on the stressor so it dies first, and size it to ~50–70% of headroom.

### A.2.4 IOChaos ✅
Docs: https://chaos-mesh.org/docs/simulate-io-chaos-on-kubernetes/

| Action | Params |
|---|---|
| `latency` | `delay` (e.g. `100ms`) |
| `fault` | `errno` (e.g. `5` = EIO) |
| `attrOverride` | `attr{perm,size,uid,gid,...}` |
| `mistake` | `mistake{filling: zero\|random, maxOccurrences, maxLength}` — READ/WRITE only |

Plus `volumePath` (**must be the root of the mount**, not a subdir), `path` (glob), `percent`, `methods` (READ, WRITE, ...), `containerNames`, `mode`, `duration`.

- ✅ **No sidecar injection** — implemented via chaos-daemon manipulating namespaces + a **FUSE** program (https://chaos-mesh.org/blog/implement-chaos-engineering-in-k8s/).
- ⚠️ Docs explicitly warn: **"IOChaos may damage your data."** The `mistake` action is **NOT reversible** — it writes garbage.
- ⚠️ Multiple reports of IOChaos not working / failing: https://github.com/chaos-mesh/chaos-mesh/issues/2438, https://github.com/chaos-mesh/chaos-mesh/issues/2305, https://github.com/chaos-mesh/chaos-mesh/issues/1081
- 🟡 **Only useful on Train Ticket for the MySQL/MongoDB pods' data volumes.** Java service pods write almost nothing to disk, so IOChaos on them produces no SLO signal.

### A.2.5 TimeChaos ✅
Docs: https://chaos-mesh.org/docs/simulate-time-chaos-on-kubernetes/
- Fields: `timeOffset` (e.g. `-10m100ns`), `clockIds` (default `["CLOCK_REALTIME"]`, also `CLOCK_MONOTONIC`), `containerNames`.
- ⚠️ ✅ **Only affects PID 1 and its children** — a process started by `kubectl exec` is unaffected. Fine for Train Ticket (java is PID 1).
- 🟡 **Do not include in your fault set.** Clock skew in a JWT/session-bearing Java app breaks token validation, MySQL/Mongo timestamps, and Jaeger/Prometheus timestamps — i.e. **it corrupts your own telemetry**, which is the thing you are measuring ΔSLO from. Implemented via vDSO rewriting; not all architectures supported.

### A.2.6 DNSChaos ✅
Docs: https://chaos-mesh.org/docs/simulate-dns-chaos-on-kubernetes/ · plugin https://github.com/chaos-mesh/k8s_dns_chaos
- Actions: `random` (return random IP) and `error` (resolution failure). `patterns` selects domains.
- ⚠️ Requires a **Chaos DNS Server** deployed (✅ **deployed by default since Chaos Mesh v2.6**).
- ⚠️ ✅ **Only supports A and AAAA records.** Java's SRV-based discovery or Mongo `mongodb+srv://` URIs are unaffected.
- ⚠️ 🟡 **Big Java gotcha: JVM DNS caching.** `java.security.networkaddress.cache.ttl` defaults to caching successful lookups (historically forever with a SecurityManager, 30 s otherwise) and `networkaddress.cache.negative.ttl` defaults to 10 s. Long-lived Spring Boot services resolve peer hostnames once and cache them, so **DNSChaos frequently has no effect on an already-warm JVM, and when it does, the poisoned entry can survive past the experiment window** — a non-reversible fault in practice. **Recommend excluding DNSChaos or explicitly setting `-Dsun.net.inetaddr.ttl=0` in the images** (which changes the SUT).

### A.2.7 HTTPChaos ✅
Docs: https://chaos-mesh.org/docs/simulate-http-chaos-on-kubernetes/

| Field | Notes |
|---|---|
| `target` | `Request` \| `Response` |
| `port` | **required** — the TCP port the target listens on |
| `method`, `path` | matchers (path supports wildcards) |
| `abort` | bool — interrupt the connection |
| `delay` | e.g. `"10s"` |
| `replace` | `{body (base64), headers{}, code}` — `code` Response-only |
| `patch` | `{headers{}, body{type: JSON, value}}` |
| `code` | match on response status (Response-only) |

- ⚠️ ✅ **HTTPS is not supported** — HTTPS access must be disabled.
- ⚠️ ✅ Implemented via **`rs-tproxy` + iptables**; requires **non-reused TCP sockets** to be effective — 🟡 this is a serious problem for Train Ticket, whose Spring `RestTemplate`/Apache HttpClient connections are pooled and long-lived. **Expect HTTPChaos to be flaky on warm Java services.**
- ⚠️ Chaos Mesh's own controller-manager must not run on the target pods.
- ⚠️ **Non-idempotent requests (POST) risk incomplete recovery** — per the docs.
- ✅ Auto-recovers at `duration` expiry.

🟡 **Verdict:** HTTPChaos is the *most semantically appealing* fault for Train Ticket (per-endpoint 500s, per-endpoint latency) but the *least reliable* on pooled-connection Java. Pilot it on 20 episodes before committing.

### A.2.8 JVMChaos ⚠️ — **the one you care about, and the one most likely to fail**
Docs: https://chaos-mesh.org/docs/simulate-jvm-application-chaos/ · chaosd equivalent https://chaos-mesh.org/docs/simulate-jvm-application-chaos-in-physical-nodes/

| Action | Required fields |
|---|---|
| `latency` | `class`, `method`, `latency` (ms) |
| `return` | `class`, `method`, `value` |
| `exception` | `class`, `method`, `exception` (e.g. `java.io.IOException("BOOM")`) |
| `stress` | `cpuCount` **or** `memType` (`stack`\|`heap`) |
| `gc` | — (forces a full GC) |
| `ruleData` / `rule-file` | raw Byteman rule |
| `mysql` | `mysqlConnectorVersion`, `database`, `table`, `sqlType`, + `exception` or `latency` |

Global: `port` (agent port, default **9288**), `pid`, `uid`. ✅ Docs state **Linux kernel ≥ 4.1**.

**Mechanism:** ✅ Chaos Mesh injects faults via **Byteman** (https://github.com/chaos-mesh/byteman-helper); a ChaosAgent attaches to the JVM. Helpers include `GCHelper` (gc) and `StressHelper` (stress); `stress` installs a rule spawning CPU-busy threads for the duration, then removes the rule.

**⚠️ CRITICAL BLOCKER for Train Ticket (✅ verified):**
Train Ticket's Java Dockerfiles use **`FROM java:8-jre`** with entrypoint `java -Xmx200m -jar /app/ts-<svc>-1.0.jar`:
- https://raw.githubusercontent.com/FudanSELab/train-ticket/master/ts-station-service/Dockerfile
- https://raw.githubusercontent.com/FudanSELab/train-ticket/master/ts-order-service/Dockerfile

A **JRE image has no `tools.jar` / attach tooling**, and the HotSpot dynamic attach handshake (`/proc/<pid>/root/tmp/.java_pid<pid>`) is fragile in containers. Known open issues:
- `AttachNotSupportedException ... target process doesn't respond within 10500ms or HotSpot VM not loaded` — https://github.com/chaos-mesh/chaos-mesh/issues/3330 (reporter had to add `-XX:+StartAttachListener`; root cause was **PID mismatch between chaos-daemon and the in-container Java PID**)
- **byteman inject fails when the Java PID is not 1** — https://github.com/chaos-mesh/chaos-mesh/issues/2751
- **no support for pods with multiple containers** — https://github.com/chaos-mesh/chaos-mesh/issues/3676
- stress action throws — https://github.com/chaos-mesh/chaos-mesh/issues/3195
- fails on OpenShift — https://github.com/chaos-mesh/chaos-mesh/issues/3408

🟡 **Recommendation:** if you want JVM-level faults you must **rebuild the Train Ticket Java images** on a JDK base (e.g. `eclipse-temurin:8-jdk` / `17-jdk`) with `-XX:+StartAttachListener`, single-container pods, java as PID 1. Budget ~1 day. **Do a hard go/no-go pilot on JVMChaos before designing the fault set around it.** If it fails, use the `train-ticket-fault-replicate` faulty images as your code-fault family instead — strictly more realistic anyway.

### A.2.9 KernelChaos ❌ — exclude
✅ https://www.mintlify.com/chaos-mesh/chaos-mesh/chaos/kernelchaos
- Uses **eBPF** to inject `should_failslab`, `should_fail_alloc_page`, `should_fail_bio`.
- Requires **Linux kernel ≥ 4.18** and boot config **`CONFIG_BPF_KPROBE_OVERRIDE`**, plus install-time **`bpfki.create=true`**.
- ⚠️ 🟡 **Will not work on k3d.** k3d nodes are containers sharing the *host* kernel; you cannot set a boot kernel config, and on Docker Desktop / WSL2 the kernel almost certainly lacks `CONFIG_BPF_KPROBE_OVERRIDE`. It is also **node-scoped, not pod-scoped** — a kernel fault blast-radiuses your whole cluster, destroying episode isolation.

### A.2.10 BlockChaos ❌ — exclude
✅ https://chaos-mesh.org/docs/simulate-block-chaos-on-kubernetes/
- Actions: `delay`, `freeze`.
- ⚠️ `delay` **depends on the `chaos-driver` kernel module, which you must compile and install manually** (uses `ioem`/`ioem-mq` I/O scheduler).
- ⚠️ `freeze` **affects all processes using the block device, not just the target container.**
- 🟡 Both are disqualifying on k3d.

### A.2.11 k3s / k3d / containerd configuration — the setup gotcha that wastes a week

✅ **k3s uses its own containerd socket at `/run/k3s/containerd/containerd.sock`**, not `/run/containerd/containerd.sock`.

```bash
helm install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh --create-namespace \
  --set chaosDaemon.runtime=containerd \
  --set chaosDaemon.socketPath=/run/k3s/containerd/containerd.sock
```

⚠️ **If you point Chaos Mesh at the wrong socket, pod-kill experiments silently "succeed" while killing nothing** — the controller reports success and no pods die. Sources: https://palark.com/blog/chaos-mesh-in-kubernetes/ · https://chaos-mesh.org/docs/production-installation-using-helm/ · https://www.vcluster.com/blog/chaos-mesh-with-vcluster

Other k3s/containerd issues:
- ⚠️ **Inode of the containerd socket changes after a containerd restart** and the chaos-daemon doesn't notice → https://github.com/chaos-mesh/chaos-mesh/issues/3072. In a 3000-episode run over days, this *will* bite you. 🟡 Add a per-episode canary check (inject a trivial pod-kill on a scratch pod and assert it died) and restart the chaos-daemon DaemonSet if it fails.
- ⚠️ **Rootless k3s is incompatible** (`/dev/shm` mount permission denied) → https://github.com/chaos-mesh/chaos-mesh/issues/2845. Run k3d rootful.
- ⚠️ chaos-daemon needs privileged + hostPID + hostNetwork.

### A.2.12 Reversibility / cleanup ✅
https://chaos-mesh.org/docs/clean-up-chaos-experiments/
- Chaos Mesh uses a **finalizer**: on delete, the controller first restores the injected faults on all targets; the finalizer is removed only once all faults are recovered.
- ⚠️ If recovery fails (e.g. the target pod no longer exists), **deletion blocks** and the object lingers with a `deletionTimestamp`.
- Force clean: `kubectl annotate networkchaos <name> chaos-mesh.chaos-mesh.org/cleanFinalizer=forced`

🟡 **Episode-loop requirement:** every episode teardown must (1) delete the chaos CR, (2) poll until it's gone with a timeout, (3) on timeout force the finalizer, (4) **assert cluster health against a baseline probe before starting the next episode**, and (5) if unhealthy, tear down and redeploy the namespace. Without (4)/(5) you will get correlated contamination across consecutive episodes, which destroys the i.i.d. assumption your model needs.

### A.2.13 Scheduling ✅
`Schedule` CRD: `schedule` (cron, `@every 1h30m10s` supported), `historyLimit`, `concurrencyPolicy` (`Forbid` default / `Allow`), `startingDeadlineSeconds`, `type` (UpperCamel, e.g. `NetworkChaos`) + matching lowercase spec field. Name ≤ 51 chars when it creates Workflows. https://chaos-mesh.org/docs/define-scheduling-rules/

🟡 For a 3000-episode driver I'd **not** use `Schedule` — drive it from your own Python/Go harness applying and deleting CRs, so you control reset and health-gating.

---

## A.3 Tool comparison for a 41-service, Java-heavy k3d cluster

| | **Chaos Mesh** | **LitmusChaos** | **Chaos Toolkit** | **Istio fault injection** |
|---|---|---|---|---|
| Model | CRD-per-fault-type, operator + privileged DaemonSet | CRD + ChaosEngine/ChaosExperiment, Argo-Workflow-based orchestration, ChaosCenter portal | Python CLI, JSON/YAML experiment files, driver plugins | Config, not chaos: `VirtualService.http.fault` |
| Fault depth | ✅ Deepest: kernel, block device, FUSE I/O, tproxy HTTP, **Byteman JVM** | Broadest catalog: **50+ experiments** incl. AWS/GCP/Azure/VMware infra chaos | Thinnest by itself; orchestrates others | Only **delay** + **abort** |
| Java-specific | ✅ **JVMChaos (Byteman): method latency / return / exception / gc / JVM stress / MySQL-client faults** — unique among these | No first-class JVM chaos found in the hub | via plugins | none |
| k3s/containerd | ✅ works with correct `socketPath`; rootless k3s ✗ | ✅ works | ✅ (no node access needed) | ✅ but Train Ticket ships **no Istio** |
| Programmatic control for 3000 runs | ✅ `kubectl apply/delete` of a CR; deterministic finalizer-based revert | ✅ but heavier (Argo workflows per run) | ✅ nicest Python API | ✅ trivial (`kubectl apply` a VirtualService) |
| Extra cluster cost | ~1 controller + 1 daemon/node | ChaosCenter + Argo + MongoDB — nontrivial on a laptop-scale k3d running 41 services | ~0 (runs outside cluster) | **+1 Envoy sidecar per pod ≈ 0.2 vCPU & 60 MB at 1k RPS** (✅ https://istio.io/latest/docs/ops/deployment/performance-and-scalability/) → **41 sidecars ≈ 8 vCPU / 2.5 GB just for the mesh** |

Sources: https://chaos-mesh.org/docs/basic-features/ · https://hub.litmuschaos.io/ · https://blog.container-solutions.com/comparing-chaos-engineering-tools · https://arxiv.org/html/2505.13654v1 (Chaos Engineering in the Wild: Findings from GitHub) · https://istio.io/latest/docs/tasks/traffic-management/fault-injection/

### 🟡 Recommendation

**Chaos Mesh as primary.** Reasons: (a) it is the only one of the four with a JVM fault primitive, and Train Ticket is Java-dominant; (b) CRD-per-experiment maps 1:1 onto "one episode = apply CR, delete CR", with finalizer-guaranteed revert — exactly the reset semantics a 3000-episode loop needs; (c) lowest control-plane footprint, which matters when 41 services already fill your k3d box (✅ measured requirement: **0.2–1 vCPU and 200 MB–1 GB RAM per service** — https://arxiv.org/pdf/2306.05895).

**Plus a thin second channel:**
1. **`kubectl set image` to `train-ticket-fault-replicate` branches** for realistic code faults (no tool needed, perfectly reversible).
2. **ConfigMap/env patches** for F3/F15/F16-style config faults.
3. **Istio, but only if you want the traffic-shifting / circuit-breaker *actions*** (Part B). If you install Istio you get its fault injection for free — but budget the sidecar cost and consider **ambient mode** to avoid 41 sidecars.

**Reject Litmus** here: ChaosCenter+Argo+Mongo is a lot of control plane for a resource-tight k3d box, and its advantage (cloud-provider infra chaos) is irrelevant to you. **Reject Chaos Toolkit as primary**: you'd end up driving Chaos Mesh from it anyway; your own harness is simpler.

---

## A.4 Recommended fault set (12 types)

Design constraints: realistic (grounded in A.1), measurable but survivable ΔSLO, cleanly reversible in an 8-minute loop, pod-scoped (not node-scoped) so episodes stay isolated.

| # | Fault | CRD / mechanism | Parameter levels | Maps to literature | Reversible? |
|---|---|---|---|---|---|
| **1** | **Network delay (downstream call latency)** | `NetworkChaos action: delay`, `direction: to`, `target:` callee | latency **50 / 200 / 800 ms**, jitter = 0.25×latency, correlation 25 | Gunawi NETWORK; RCAEval DELAY; Nezha network delay; F4/F7 | ✅ clean (tc rule removed) |
| **2** | **Network packet loss** | `NetworkChaos action: loss` | **1 / 5 / 20 %**, correlation 25 | RCAEval LOSS; Gremlin Packet Loss | ✅ clean |
| **3** | **Bandwidth throttle** | `NetworkChaos action: bandwidth` | rate **10 / 1 / 0.25 mbps**, limit 20971520, buffer 10000 | Gunawi NETWORK; fail-slow | ✅ clean |
| **4** | **Service partition (dependency blackhole)** | `NetworkChaos action: partition`, `direction: both` | binary | Gunawi CROSS-service; SREGym network; Gremlin Blackhole | ✅ clean; ⚠️ direction bugs — use `both` |
| **5** | **External dependency timeout** | `NetworkChaos action: delay`, `externalTargets: [<payment host/IP>]` | 5 s / 30 s / partition | ✅ **F7 exactly** | ✅ clean |
| **6** | **CPU saturation (noisy neighbour / fail-slow)** | `StressChaos stressors.cpu` | workers 1/2/4 × load **50/80/100** | RCAEval CPU; Nezha CPU contention; SREGym fail-slow; **F5** | ✅ clean (process killed) |
| **7** | **Memory pressure** | `StressChaos stressors.memory` + `oomScoreAdj` | size **40 / 65 / 85 %** of container limit | RCAEval MEM; **F3** | 🟡 **conditionally** — see flags |
| **8** | **Pod kill (crash)** | `PodChaos action: pod-kill`, `gracePeriod: 0` | mode `one` / `fixed:2` | Gremlin Process Killer; SREGym process layer; Liu et al. "error component" 43% | ✅ ReplicaSet recreates; ⚠️ JVM cold start (~10× slower for ~90 s) |
| **9** | **Pod hang / unresponsive** | `PodChaos action: pod-failure` (pause image) | duration 60 / 180 / 300 s | ✅ **Liu et al. "unresponsive component" 29%** | ✅ auto-restores; ⚠️ pre-pull pause image |
| **10** | **Container kill (single container)** | `PodChaos action: container-kill` + `containerNames` | — | SREGym; Gremlin | ✅ kubelet restarts |
| **11** | **Config fault (JVM/heap/body-size/timeout)** | `kubectl patch` env or ConfigMap + rolling restart | `-Xmx` > limit (**F3**); nginx body size 200 B (**F15**); upload cap 2 MB (**F16**); client timeout ↓ | ✅ **F3, F15, F16**; Gunawi CONFIG; AutoARTS config classes | ✅ patch back + restart |
| **12** | **Code fault (buggy build)** | `kubectl set image ...=<fault-replicate branch image>` | one of F6, F10, F12, F17, F20, F22 | ✅ **the actual Fudan industrial faults** | ✅ `set image` back |

**Optional 13–14 (pilot first):**
- **JVMChaos** `exception` / `latency` / `gc` on a hot service method — ✅ maps to Liu et al.'s error-component class and is the most *semantically* microservice-y fault. **Only after you rebuild images on a JDK base.** (A.2.8)
- **HTTPChaos** `abort` (500s at N%) / `delay` per endpoint — ✅ cleanest endpoint-scoped SLO degradation. **Only after you confirm it fires on pooled connections.** (A.2.7)

**Plus ambient noise** (adopt from SREGym ✅): two randomly chosen low-impact disturbances per 5 minutes, each 2 minutes, on services *unrelated* to the injected fault.

### ⚠️ Faults flagged as NOT cleanly reversible

| Fault | Why it doesn't reset cleanly |
|---|---|
| **StressChaos memory (#7)** | If sized wrong, the **JVM** is OOMKilled instead of the stressor → becomes an unintended container-kill + cold start, contaminating ΔSLO attribution. Mitigate with `oomScoreAdj` on the stressor and a cap at ~70% of headroom. Pilot per-service. |
| **IOChaos `mistake`** | ✅ Docs: "may damage your data." Writes garbage into files. **Exclude.** |
| **IOChaos `fault`/`latency` on DB volumes** | 🟡 EIO mid-write to MySQL/Mongo can leave an inconsistent datafile requiring a full namespace redeploy (minutes). **Exclude, or only on read paths with `methods: [READ]`.** |
| **DNSChaos** | 🟡 JVM DNS cache means the poisoned/failed resolution can outlive the experiment window, or never take effect. Non-deterministic. **Exclude.** |
| **TimeChaos** | 🟡 Corrupts JWT/session validity, DB timestamps, and your own Prometheus/Jaeger telemetry. **Exclude.** |
| **KernelChaos** | ✅ Node-scoped, needs `CONFIG_BPF_KPROBE_OVERRIDE`; impossible on k3d. **Exclude.** |
| **BlockChaos** | ✅ `delay` needs a hand-compiled kernel module; `freeze` hits all processes on the device. **Exclude.** |
| **`pod-kill` on a DB pod** | 🟡 Single-instance MySQL/Mongo with a PVC — recovery time is unbounded and may require InnoDB crash recovery. **Restrict pod-kill to stateless Java/Node/Python/Go services.** |
| **Any chaos whose CR finalizer wedges** | ✅ Deletion blocks; requires `cleanFinalizer=forced`. Handle in teardown. |

### 🟡 Throughput reality check
3000 episodes × 8 min = **400 hours ≈ 16.7 days serial**, before reset overhead. Train Ticket wants **0.2–1 vCPU / 200 MB–1 GB per service × 41 services** (✅ https://arxiv.org/pdf/2306.05895). Plan for **N parallel k3d clusters on one or more beefy hosts** (each cluster ≈ 12–20 vCPU, 32–48 GB) — 4 parallel clusters gets you to ~4 days. Budget a teardown+health-gate of 60–90 s per episode on top of the 8 min.

---

# PART B — ACTION / REMEDIATION TAXONOMY

## B.1 What real SRE teams and auto-remediation systems actually do

### The single best citation: Google's "generic mitigations" ✅
Jennifer Mace, O'Reilly / Google SRE — https://www.oreilly.com/content/generic-mitigations/ · https://sre.google/workbook/incident-response/

The seven generic mitigations, quoted:
1. **Rollback** — "reverts your service—most commonly, your binary, but there are other options—to a known-good state"
2. **Data rollback** — reverts just the data layer
3. **Degrade** — "Having a way to do less work but stay up is a huge improvement over crashing"
4. **Upsize** — "Add more replicas. It's expensive, but cheaper than pissing off users with an outage"
5. **Block list** — "Got a query of death? Single spammy user taking out a zone? Block them"
6. **Drain** — "Move your traffic to a different place"
7. **Quarantine** — "Isolate a given unit of your usage…so whatever bug it is hitting stops breaking others"

Rationale: **"time to mitigate" matters more than "time to fix"**; *"It is far easier to build mitigations with broad application than it is to make root-causing faster."* Google SREs have since defined **a closed set of standard mitigation classes: drain traffic, rollback, restart, add capacity** — ✅ which is essentially your action set, and is a strong citation that a *small finite action set* is the right modelling choice.

### Empirical action distribution ✅
Gunawi SoCC'16 fix-procedure distribution (of the 24% of outages documenting a fix): fix-software 22%, fix-hardware 22%, restore-data 14%, **add-resources 10%**, **rollback-software 8%**, fix-misconfig 7%, **restart-components 4%**, **no-action 12%**. → an empirical prior you can cite for sampling weights (though for causal validity you want *uniform* sampling; see Part C).

### Auto-remediation platforms ✅
| System | What it is | URL |
|---|---|---|
| **StackStorm** | "IFTTT for Ops" — event-driven auto-remediation; rules engine + workflows; **160 integration packs, 6000+ actions** on StackStorm Exchange | https://stackstorm.com/2015/10/05/auto-remediation-out-of-disk-space/ · https://github.com/StackStorm/st2 |
| **PagerDuty Rundeck** | Runbook automation; common auto-remediation = restart a service, gather logs/status, diagnose+resolve | https://docs.rundeck.com/docs/learning/solutions/automated-diagnostics/automation-beyond-triage.html |
| **Shoreline.io** | Incident automation / self-healing; **library of 120+ Runbooks** | https://www.wwt.com/blog/shoreline-data-driven-aiops |
| **Keptn** | Event-driven remediation at microservice level; **pluggable "action providers"**; reusable atomic actions; SLO-triggered rollback and scaling | https://medium.com/keptn/closed-loop-remediation-with-custom-integrations-43bde377b796 · https://github.com/keptn/keptn.github.io/blob/master/content/docs/0.1.1/usecases/runbook-automation-and-self-healing/index.md |
| **Rootly** | Automated remediation with IaC & Kubernetes | https://rootly.com/sre/rootly-automated-remediation-with-iac-kubernetes |
| **AIOpsLab** | Agent mitigation task: "update the configuration, or rollback to a previous version"; orchestrator can "scale-up, redeploy" via helm/kubectl | https://arxiv.org/pdf/2501.06706 |
| **K8s self-healing survey (2026)** | Enumerates the action menu: **rollback, restart, IAM rotation, certificate renewal, cache flush, replica scale, traffic shift**; cordon+drain; and an automation taxonomy L1/L2/L3 | https://www.ijert.org/automated-fault-remediation-and-self-healing-in-kubernetes-a-survey-of-failure-scope-llm-roles-and-post-remediation-verification-ijertv15is090091 |
| **Netflix** | Prioritized/progressive **load shedding**; Hystrix circuit breaking + bulkheads; **Zuul-based progressive regional traffic evacuation** (trickle → 100%) | https://netflixtechblog.com/keeping-netflix-reliable-using-prioritized-load-shedding-6cc827b02f94 · https://github.com/Netflix/Hystrix/wiki/how-it-works · https://opensource.com/article/18/4/how-netflix-does-failovers-7-minutes-flat |

---

## B.2 Candidate action catalogue with collateral-damage mechanisms

This is the core table. **The "collateral damage mechanism" column is the substance of your thesis** — each row is a causal story your model should be able to learn.

| # | Action | How applied | Time to take effect | Reversible? | **Collateral damage mechanism** |
|---|---|---|---|---|---|
| **A0** | **No-op** | — | 0 | n/a | **None — this is your counterfactual baseline.** Without it ΔSLO is unidentifiable: you cannot separate "the action helped" from "the fault was self-limiting." ✅ Gunawi: 12% of documented fixes were "no action". **Mandatory, and should get an oversized share of samples (≥20%).** |
| **A1** | **Delete pod (hard restart)** | `kubectl delete pod <p> --grace-period=0 --force` | Deletion instant; **new pod Ready in ~20–60 s** (image cached) + **~90 s JVM warm-up** | ✅ self-healing via ReplicaSet | 🟡 **(a) In-flight requests dropped**: `--grace-period=0` skips SIGTERM/preStop entirely, so open HTTP connections are RST. ✅ (b) **JVM cold start: up to 10× slower than a warmed JVM, first-request latency up to ~10 s, interpreted mode for the first ~90 s** — https://medium.com/nordnet-tech/from-cold-start-to-high-load-tuning-spring-boot-for-resilience-autoscaling-on-kubernetes-31e161352405 · https://www.xflowpay.com/blog/best-practices-to-solve-java-warmup-issues-in-kubernetes. (c) **JIT compilation storm** burns CPU on a possibly-already-saturated node. (d) The new pod reopens its Hikari pool → connection churn on the DB. (e) Losing 1 of N replicas shifts 1/N of load onto survivors during warm-up — **the classic path into a metastable retry storm** (HotOS'21). |
| **A2** | **Rolling restart (graceful)** | `kubectl rollout restart deploy/<d>` | Respects `maxSurge`/`maxUnavailable`; **`terminationGracePeriodSeconds` default 30 s** per pod; whole deployment ~1–3 min | ✅ | Milder than A1: ✅ SIGTERM + preStop hooks fire, in-flight requests get the grace window to drain — https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/. 🟡 But still **every replica cold-starts in sequence**, so the deployment spends minutes at partially-warm capacity. Worse than A1 when only one replica was sick. |
| **A3** | **Scale up replicas** | `kubectl scale deploy/<d> --replicas=N` | Pod scheduled in seconds; **Ready + warm in 60–150 s** (JVM) | ✅ (scale back) | 🟡 ✅ **Connection-pool storm.** Each pod runs its own pool: "a deployment with 10 replicas means 10 separate pools… If each pod has pool size 20, that's 200 connections, which may exceed `max_connections`" — https://codefarm.in/guides/kubernetes/07-scenarios-and-interviews/the-thundering-herd · https://cubeapm.com/blog/postgresql-connection-pool-exhausted-kubernetes/. Documented cascade: "connections queued, requests timed out, the health endpoint started failing, and pods that had connections couldn't get queries through because the database was saturated." **This is the single cleanest collateral-damage story in your whole design, and Train Ticket has exactly the topology for it (shared per-service MySQL, Spring Boot Hikari pools).** Also: (b) new pods steal node CPU from warm ones during JIT storm; (c) on a resource-tight k3d box, scale-up may leave pods `Pending`, or evict others. |
| **A4** | **Scale down replicas** | `kubectl scale deploy/<d> --replicas=N-1` | Termination begins immediately, 30 s grace | ✅ | 🟡 Obvious: **less capacity under an already-degraded condition** → pushes a "vulnerable" system into "metastable overload" (HotOS'21). Also drops the in-flight requests on the terminated pod if preStop/readiness draining isn't wired (Train Ticket's stock manifests are thin here). Legitimate in real life for *quarantining* a bad replica or relieving DB connection pressure — so it is not a pure "bad action", which makes it valuable signal. |
| **A5** | **Rollback deployment** | `kubectl rollout undo deploy/<d>` (or `--to-revision=K`) | New ReplicaSet scales up per rolling-update policy; **~1–3 min for the deployment** | ✅ (`rollout undo` again) | ✅ **Only fields captured in the pod template are reverted; external dependencies (e.g. ConfigMaps updated out-of-band) are not** — https://www.plural.sh/blog/kubectl-rollout-undo-deployment/. ⚠️ Default `revisionHistoryLimit` is **10**. 🟡 (a) **Reintroduces whatever bug the previous revision had** — and Fudan **F20 (shared-library enum version mismatch across services)** is the perfect illustration: rolling back *one* service to an older lib version desynchronises enum values with its unrolled peers, converting a local fault into a cross-service data fault. (b) Full cold-start cost on every replica. (c) If the fault was *not* caused by a deploy, rollback is pure cost — a degenerate pairing you should still sample (Part C). |
| **A6** | **Increase resource limits / requests** | k8s ≥1.33: `kubectl patch pod <p> --subresource resize -p '{"spec":{"containers":[{"name":"x","resources":{"limits":{"cpu":"2"}}}]}}'`. Otherwise `kubectl set resources deploy/<d> --limits=cpu=2,memory=1Gi` | In-place: seconds. Deployment patch: **full rolling restart** | ✅ | ✅ **Critical version dependency:** in-place pod resize is **beta and on-by-default in k8s 1.33**, **GA in 1.35** — https://kubernetes.io/blog/2025/05/16/kubernetes-v1-33-in-place-pod-resize-beta/ · https://kubernetes.io/blog/2025/12/19/kubernetes-v1-35-in-place-pod-resize-ga. 🟡 **On older k3s, patching resources on the Deployment mutates the pod template and triggers a full rolling restart** — so "bump limits" secretly *is* "restart everything," with all of A2's cold-start damage. Check your k3d/k3s version; if <1.33 this action's damage profile is dominated by the restart, which confounds your model. Other collateral: raising requests can make pods unschedulable on a full k3d node (`Pending`), or push the node into memory pressure → **kubelet evicts other pods**, blast radius far beyond the target. |
| **A7** | **Shift traffic away (Istio)** | `VirtualService` weighted routing: `route: [{destination: {subset: v1}, weight: 0}, {subset: v2, weight: 100}]`; or drop a subset | ✅ Istio docs: config propagation takes **"several seconds"** across pods | ✅ (reapply original VS) | 🟡 **Requires Istio; Train Ticket ships none.** (a) Concentrates all load on the remaining subset → can overload it (Netflix does this *progressively* for exactly this reason). (b) Existing long-lived connections are not necessarily re-routed. (c) With only one deployment per service in stock Train Ticket, there is nowhere to shift to unless you deploy v1/v2 subsets — **budget for that.** |
| **A8** | **Enable circuit breaker (Envoy outlier detection)** | Istio `DestinationRule.trafficPolicy.outlierDetection: {consecutive5xxErrors, interval, baseEjectionTime, maxEjectionPercent}` | Ejection after `consecutive5xxErrors` (**default 5**) within `interval` | ✅ (remove DR) | ✅ https://istio.io/latest/docs/reference/config/networking/destination-rule/. 🟡 **Ejecting an endpoint removes capacity.** If `maxEjectionPercent` is high and the fault is systemic (e.g. the shared DB is slow, so *all* replicas 5xx), outlier detection **ejects every endpoint → 100% failure**, converting a partial degradation into a total outage. Also: `connectionPool` limits (`http1MaxPendingRequests`, `http2MaxRequests`, `maxRetries` — all default 2³²−1) turn queueing into immediate 503s once set. **Great collateral-damage story.** |
| **A9** | **Rate-limit / load-shed** | Istio `EnvoyFilter` with `envoy.filters.http.local_ratelimit` (token bucket: `max_tokens`, `tokens_per_fill`, `fill_interval`) → over-limit requests get **429** | Seconds (xDS push) | ✅ (delete EnvoyFilter) | ✅ https://istio.io/latest/docs/tasks/policy-enforcement/rate-limit/ · https://learncloudnative.com/blog/2022-09-08-ratelimit-istio. 🟡 (a) **Local (per-proxy) limits, not aggregate** — with N replicas the effective limit is N× what you configured, so it's easy to mis-set. (b) The 429s *are* SLO violations: you trade latency for availability, which your ΔSLO metric must be able to represent (**define SLO as success-rate AND latency, not just latency**, or load-shedding will look free). (c) If the limiter sits upstream of a healthy service, it's pure self-inflicted damage. |
| **A10** | **Cordon + drain node** | `kubectl cordon <n>` then `kubectl drain <n> --ignore-daemonsets --delete-emptydir-data` | Eviction respects **PDBs** and `terminationGracePeriodSeconds`; **can block indefinitely if a PDB can't be satisfied** | ✅ `kubectl uncordon` — but **rescheduling back does not happen automatically** | ✅ https://kubernetes.io/docs/concepts/workloads/pods/disruptions/ · https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/. 🟡 **Highest blast radius by far**: on a 3-node k3d cluster, draining one node relocates ~1/3 of all 41 services at once → mass simultaneous JVM cold start, mass DB reconnection, and possible `Pending` pods if the remaining nodes lack capacity. If a DB pod with a `local-path` PVC lives on that node, **it cannot reschedule at all** (node-affine PV) → hard outage. **⚠️ This is the action most likely to break your 8-minute episode budget.** |
| **A11** | **Clear cache** | `kubectl exec <redis> -- redis-cli FLUSHALL`, or restart the cache pod | Instant | ❌ data gone (but regenerable) | 🟡 **Cache-miss storm**: every subsequent request goes to the DB, multiplying DB load by the former hit ratio — a textbook *sustaining effect* that can push the system into metastable collapse (HotOS'21). **Caveat: stock Train Ticket's Redis usage is thin (F8 references it for VIP tokens).** Verify before including; if there's no meaningful cache, this action has no mechanism and becomes noise. |
| **A12** | **Failover database** | — | — | — | ⚠️ **Not available in stock Train Ticket.** Each service gets a single-instance MySQL/Mongo (optionally one per service via `--independent-db`). There is no replica to fail over to. To include this you'd have to deploy a real MySQL operator with replicas. 🟡 **Recommend dropping it**, or substituting "restart the DB pod" as an explicitly high-damage action. |
| **A13** | **Roll forward (redeploy current/new image)** | `kubectl set image deploy/<d> <c>=<image>:<newtag>` | Rolling update, 1–3 min | ✅ | Same cold-start cost as A5, plus 🟡 you are deploying an *unvalidated* artifact under duress — in a synthetic benchmark this is really "restart with a different tag," so its damage profile ≈ A2 unless the new image genuinely differs. **Low marginal information; deprioritise.** |
| **A14** | **Abort a progressive rollout** | `kubectl argo rollouts abort <rollout>` | Traffic shifts back to stable within seconds (canary+traffic-routing) or a replica rollback | Partially | ✅ **"Abort does not rewrite `.spec.template`. The desired template still names the rejected version, so the Rollout is normally Degraded: stable is serving, but live capacity does not match the desired revision."** — https://oneuptime.com/blog/post/2026-08-02-argo-rollouts-abort-vs-rollback/view. 🟡 **Requires installing Argo Rollouts and converting Deployments → Rollouts for 41 services.** Only worth it if progressive delivery is part of your story. **Recommend excluding for v1.** |

---

## B.3 Recommended action set (8 actions) with exact calls

Chosen for: (1) ≥6 distinct, *non-overlapping* collateral mechanisms; (2) all reversible inside 8 min; (3) all implementable on k3d with at most one added component (Istio).

| # | Action | Exact call | Reset call | Primary damage mechanism it teaches |
|---|---|---|---|---|
| **0** | **no-op** | *(none — record `action=noop`)* | — | *counterfactual baseline* |
| **1** | **restart-pod** | `kubectl -n tt delete pod <pod> --grace-period=0 --force` | none (ReplicaSet) | dropped in-flight requests + JVM cold start + JIT storm |
| **2** | **scale-up** | `kubectl -n tt scale deploy/<svc> --replicas=$((R+2))` | `kubectl -n tt scale deploy/<svc> --replicas=$R` | **connection-pool storm on shared MySQL** + node CPU contention |
| **3** | **scale-down** | `kubectl -n tt scale deploy/<svc> --replicas=$((R-1))` (floor 1) | scale back to `$R` | capacity removal → overload / metastable tipping |
| **4** | **rollback** | `kubectl -n tt rollout undo deploy/<svc>` + `kubectl -n tt rollout status deploy/<svc> --timeout=180s` | `kubectl -n tt rollout undo deploy/<svc>` (again) | **reintroduces old bug (F20-style cross-service version skew)** + full rolling cold start |
| **5** | **resource-bump** | ≥1.33: `kubectl -n tt patch pod <pod> --subresource resize --patch '{"spec":{"containers":[{"name":"<c>","resources":{"limits":{"cpu":"2","memory":"1Gi"},"requests":{"cpu":"500m","memory":"512Mi"}}}]}}'` <br> <1.33: `kubectl -n tt set resources deploy/<svc> --limits=cpu=2,memory=1Gi` | patch/set back to baseline | scheduling pressure / node eviction; **on <1.33 also a hidden full restart** |
| **6** | **circuit-break** | `kubectl apply -f dr-outlier.yaml` — `DestinationRule` with `outlierDetection: {consecutive5xxErrors: 3, interval: 10s, baseEjectionTime: 30s, maxEjectionPercent: 100}` | `kubectl delete destinationrule <name>` | **ejects all endpoints when the fault is systemic → total outage** |
| **7** | **rate-limit / load-shed** | `kubectl apply -f ef-localratelimit.yaml` — `EnvoyFilter` with `local_ratelimit` token bucket (`max_tokens: 50, tokens_per_fill: 50, fill_interval: 1s`) | `kubectl delete envoyfilter <name>` | **429s are themselves SLO violations**; per-proxy limit ≠ aggregate limit |

**Optional 8th/9th if you can afford them:**
- **traffic-shift** (A7) — needs v1/v2 subsets per target service.
- **cordon+drain** (A10) — highest-signal, highest-risk; see flags below.

🟡 **Note on 6 & 7:** both require Istio. If you decline Istio, substitute:
- circuit-break → **`NetworkPolicy` that blocks the sick service** (a crude "quarantine"), reversible by deleting the NetworkPolicy;
- rate-limit → **`kubectl scale` the load generator down** (a crude global load-shed), or set `spec.replicas` on a gateway.

These are less faithful but keep the *mechanism class* (isolation; demand reduction) in the action space.

### ⚠️ Actions flagged as NOT safely reversible within an 8-minute episode

| Action | Problem |
|---|---|
| **cordon + drain node (A10)** | ✅ Eviction blocks on PodDisruptionBudgets and honours full grace periods; `uncordon` does **not** reschedule pods back. On k3d with `local-path` PVCs, **DB pods pinned to the drained node cannot reschedule at all** → permanent namespace damage. 🟡 If you include it: restrict to a dedicated "sacrificial" agent node hosting only stateless services, set `--force --delete-emptydir-data --timeout=120s`, and make the reset a full `kubectl rollout restart` of everything on that node. Budget 3–4 min of the episode for reset alone. |
| **clear cache / FLUSHALL (A11)** | Irreversible by definition (data is gone). Tolerable *if* the cache is purely derived — verify for Train Ticket. Cache-miss storm may persist past the episode window. |
| **failover database (A12)** | Not available; the substitute (restart DB pod) risks InnoDB crash recovery of unbounded duration and possible data-file corruption. **Exclude.** |
| **abort rollout (A14)** | ✅ Leaves the Rollout `Degraded` with template ≠ live state — requires an extra `promote`/`set image` to fully reset. Adds an infra dependency (Argo Rollouts across 41 services). **Exclude for v1.** |
| **resource-bump on k8s < 1.33** | Reversible, but the revert is *also* a full rolling restart, so the episode's "reset" is itself a large perturbation. 🟡 **Check `kubectl version`; if <1.33, either upgrade k3d's k3s channel or accept that this action is confounded with restart.** |
| **rollback (A5)** when the base revision is >10 deploys old | ✅ `revisionHistoryLimit` default 10 — older revisions are gone. Pin `revisionHistoryLimit` explicitly and seed each namespace with a known 2-revision history at episode start. |

---

# PART C — Degenerate fault × action pairings

## C.1 Which pairings are degenerate

Using the 12 faults × 8 actions grid. "Degenerate" = 🟡 my judgement that the action has **no plausible causal path to the fault's mechanism**, so ΔSLO should be ≈ the action's *unconditional* damage (a main effect with no interaction term).

| Fault | Clearly degenerate actions | Why |
|---|---|---|
| Network delay / loss / bandwidth (1–3) | **rollback**, **resource-bump**, **scale-down** | `tc netem` rules live in the pod netns and are reapplied to *new* pods by the chaos-daemon; no image, CPU limit, or replica count touches them. Rollback changes the binary, not the network. |
| Service partition (4) | **rollback**, **resource-bump**, **scale-up**, **circuit-break** | Partition is total and symmetric; adding replicas adds more blocked replicas. Circuit-breaking an already-unreachable endpoint is a no-op on outcome. |
| External dependency timeout (5) | **rollback**, **resource-bump**, **restart-pod**, **scale-up/down** | The fault is outside the cluster. **Exception:** circuit-break and rate-limit are the *correct* actions here (fail fast / shed), so keep those. |
| CPU saturation (6) | **rollback** | The stressor process is not in the image. (resource-bump and scale-up are genuinely relevant; scale-down is relevant-but-harmful.) |
| Memory pressure (7) | **rollback**, **rate-limit**, **circuit-break** | The stressor isn't demand-driven, so shedding demand doesn't relieve it. |
| Pod kill (8) | **rollback**, **circuit-break**, **rate-limit**, **resource-bump** | The pod is already gone and the ReplicaSet already replaced it — every action here is pure added damage on top of self-healing. |
| Pod hang / pod-failure (9) | **rollback**, **resource-bump**, **scale-down** | The pause-image swap is reapplied by Chaos Mesh for the duration regardless. **Exception:** restart-pod is interestingly *non*-degenerate — see C.3. |
| Container kill (10) | all except no-op | kubelet already restarted it in seconds. |
| Config fault (11) | **rollback** is the *correct* action if you injected the config by patching the Deployment (it's in the revision history!); **restart-pod** is degenerate (the bad config comes right back) | |
| Code fault (12) | **scale-up/down**, **resource-bump**, **rate-limit** | A logic bug is replica-invariant. **rollback is the correct action** (that's exactly what `set image` back is). |

**Rough count:** ~35–40% of the 96 cells are degenerate. That is normal and fine.

## C.2 Why you should sample them anyway — my opinion

**Yes. Sample the full grid uniformly at random. Do not prune.** Five reasons:

1. **Uniform random assignment of action, independent of fault, is what makes this a randomized controlled trial.** The moment you prune cells you have introduced a confound between fault and action, and every ΔSLO estimate becomes observational. Your model would learn the *pruning policy*, not the causal effect. This is the whole reason you chose random actions in the first place — pruning throws it away.

2. **The degenerate cells are where you learn the action's main effect.** ΔSLO(restart | network-delay) with no causal path ≈ pure "what does a restart cost." You need a clean estimate of that cost to decompose ΔSLO = f(action) + g(fault) + h(action×fault). Without degenerate cells you cannot identify f, and the model will over-attribute action cost to fault interaction.

3. **"Obviously unrelated" is a hypothesis, not a fact — and some of the surprises are the interesting results.** Examples from this grid: restarting a pod under CPU stress *does* help, because Chaos Mesh's stressor process lives in the old container and dies with it — the "wrong" action accidentally works. Scaling up under network *delay* can help (more concurrency hides latency) or hurt (more DB connections). Circuit-breaking under a systemic fault ejects 100% of endpoints and makes things catastrophically worse. If you prune on intuition you will prune exactly these.

4. **Real SRE behaviour is full of degenerate actions.** Under pressure, humans restart things that don't need restarting and roll back deploys that weren't the cause — Google's whole "generic mitigations" argument is *"apply a broad mitigation before you know the root cause"* (https://www.oreilly.com/content/generic-mitigations/). A blast-radius predictor that has only ever seen well-matched pairs is useless for the deployment scenario it's meant for: **predicting the cost of an action a human or agent is *considering* but might be wrong about.**

5. **Negative/null results are the safety property you're selling.** A model that can say "this action will not help and will cost you 40 s of p99" is more operationally valuable than one that only ranks good actions.

## C.3 Practical sampling recommendations

- **Uniform over actions** (12.5% each with 8 actions) → ~375 episodes/action, ~31 per (fault, action) cell at 12×8. That is thin for a cell-level estimate but adequate if your model shares strength across cells (which is the point of learning a model rather than a lookup table).
- 🟡 **Slightly over-sample `no-op`** — bump it to ~20% (≈600 episodes). Every other action's ΔSLO is measured *relative* to no-op, so no-op's variance enters every contrast. This is the one deviation from uniform I'd defend, and it's defensible because it's a *pre-registered, fault-independent* reweighting, so it doesn't confound.
- **Record `degenerate_expected: bool` as a metadata column, not a filter.** Then you can report "model accuracy on expected-degenerate cells" as a separate evaluation slice — and any cell where the model is confidently wrong is a finding.
- **Stratify, don't prune.** Use a randomized block design: block on fault type, randomize action within block. Guarantees balanced cells without breaking randomization.
- **Also randomize the action *delay*** (time from fault injection to action). A restart at t=30 s and at t=300 s have very different ΔSLO. If you hold it fixed you'll silently condition on it; if you randomize it uniformly over, say, 60–300 s, it becomes an identifiable covariate.
- **Include the SREGym-style ambient noise**, and log it, so the model learns ΔSLO under realistic background variance rather than in a vacuum.

---

# Appendix: Summary of the biggest risks to this project

| Risk | Severity | Evidence |
|---|---|---|
| **JVMChaos will not work on stock Train Ticket images** (`java:8-jre`, Byteman attach issues) | 🔴 High — removes the most Java-relevant fault class | ✅ Dockerfiles + Chaos Mesh issues #3330, #2751, #3676 |
| **Chaos Mesh pointed at the wrong containerd socket → silent no-op experiments** | 🔴 High — would poison the dataset invisibly | ✅ k3s socket is `/run/k3s/containerd/containerd.sock` |
| **Chaos-daemon loses the containerd socket inode after a restart mid-run** | 🟠 Medium — silent partial corruption over a multi-day run | ✅ issue #3072 |
| **Only ~6 of 22 Fudan industrial faults are infra-injectable** | 🟠 Medium — representativeness claim | ✅ A.1.2 |
| **resource-bump is secretly a full restart on k8s < 1.33** | 🟠 Medium — confounds two actions | ✅ in-place resize beta in 1.33 |
| **HTTPChaos unreliable on pooled Java connections; DNSChaos defeated by JVM DNS cache** | 🟠 Medium | ✅ docs (non-reused sockets) / 🟡 JVM caching |
| **cordon/drain + local-path PVCs → unrecoverable episode** | 🟠 Medium | ✅ PDB/eviction semantics |
| **400 h serial wall-clock for 3000 episodes** | 🟠 Medium — plan parallel clusters | 🟡 arithmetic + ✅ per-service resource figures |
| **Missing readiness probes → pod-failure looks Ready while dead** | 🟡 Low-Medium — inconsistent labels | ✅ Chaos Mesh PodChaos docs |

---

## Sources

- [Fault Analysis and Debugging of Microservice Systems (IEEE TSE 2021)](https://ieeexplore.ieee.org/document/8580420/) · [ACM DL](https://dl.acm.org/doi/10.1109/TSE.2018.2887384) · [PDF](https://cspengxin.github.io/publications/tse19-msdebugging.pdf) · [project page](https://fudanselab.github.io/research/MSFaultEmpiricalStudy/) · [dblp](https://dblp.org/rec/journals/tse/ZhouPXSJLD21.html)
- [FudanSELab/train-ticket-fault-replicate](https://github.com/FudanSELab/train-ticket-fault-replicate) · [Fault Description wiki](https://github.com/FudanSELab/train-ticket/wiki/Fault-Description) · [train-ticket README](https://github.com/FudanSELab/train-ticket) · [ts-station-service Dockerfile](https://raw.githubusercontent.com/FudanSELab/train-ticket/master/ts-station-service/Dockerfile) · [ts-order-service Dockerfile](https://raw.githubusercontent.com/FudanSELab/train-ticket/master/ts-order-service/Dockerfile)
- [Why Does the Cloud Stop Computing? (SoCC'16)](https://dl.acm.org/doi/10.1145/2987550.2987583) · [PDF](https://ucare.cs.uchicago.edu/pdf/socc16-cos.pdf) · [summary](http://muratbuffalo.blogspot.com/2016/11/why-does-cloud-stop-computing-lessons.html)
- [What bugs cause production cloud incidents? (HotOS'19)](https://dl.acm.org/doi/10.1145/3317550.3321438) · [PDF](https://people.cs.uchicago.edu/~shanlu/paper/hotos19_azure.pdf) · [the morning paper](https://blog.acolyer.org/2019/06/21/what-bugs-cause-cloud-production-incidents/)
- [AutoARTS (USENIX ATC'23)](https://www.usenix.org/conference/atc23/presentation/dogga) · [taxonomy browser](https://autoarts-rca-taxonomy.github.io/) · [How to Fight Production Incidents? (SoCC'22)](https://www.microsoft.com/en-us/research/publication/how-to-fight-production-incidents-an-empirical-study-on-a-large-scale-cloud-service/)
- [Metastable Failures in Distributed Systems (HotOS'21)](https://sigops.org/s/conferences/hotos/2021/papers/hotos21-s11-bronson.pdf) · [Metastable Failures in the Wild](https://www.usenix.org/publications/loginonline/metastable-failures-wild) · [Analyzing Metastable Failures (HotOS'25)](https://sigops.org/s/conferences/hotos/2025/papers/hotos25-106.pdf)
- [RCAEval](https://arxiv.org/pdf/2412.17015) · [RCAEval repo](https://github.com/phamquiluan/RCAEval) · [Nezha](https://github.com/IntelligentDDS/Nezha) · [AIOpsLab](https://arxiv.org/pdf/2501.06706) · [AIOpsLab blog](https://www.microsoft.com/en-us/research/blog/aiopslab-building-ai-agents-for-autonomous-clouds/) · [SREGym](https://arxiv.org/pdf/2605.07161) · [SREGym HTML](https://arxiv.org/html/2605.07161v1) · [ITBench](https://github.com/itbench-hub/ITBench) · [Benchmarks for End-to-End Microservices Testing](https://arxiv.org/pdf/2306.05895)
- Chaos Mesh: [Basic Features](https://chaos-mesh.org/docs/basic-features/) · [PodChaos](https://chaos-mesh.org/docs/simulate-pod-chaos-on-kubernetes/) · [NetworkChaos](https://chaos-mesh.org/docs/simulate-network-chaos-on-kubernetes/) · [StressChaos](https://chaos-mesh.org/docs/simulate-heavy-stress-on-kubernetes/) · [IOChaos](https://chaos-mesh.org/docs/simulate-io-chaos-on-kubernetes/) · [TimeChaos](https://chaos-mesh.org/docs/simulate-time-chaos-on-kubernetes/) · [DNSChaos](https://chaos-mesh.org/docs/simulate-dns-chaos-on-kubernetes/) · [HTTPChaos](https://chaos-mesh.org/docs/simulate-http-chaos-on-kubernetes/) · [JVMChaos](https://chaos-mesh.org/docs/simulate-jvm-application-chaos/) · [chaosd JVM](https://chaos-mesh.org/docs/simulate-jvm-application-chaos-in-physical-nodes/) · [KernelChaos](https://www.mintlify.com/chaos-mesh/chaos-mesh/chaos/kernelchaos) · [BlockChaos](https://chaos-mesh.org/docs/simulate-block-chaos-on-kubernetes/) · [Clean up experiments](https://chaos-mesh.org/docs/clean-up-chaos-experiments/) · [Scheduling rules](https://chaos-mesh.org/docs/define-scheduling-rules/) · [Helm install](https://chaos-mesh.org/docs/production-installation-using-helm/) · [Architecture blog](https://chaos-mesh.org/blog/implement-chaos-engineering-in-k8s/) · [FAQs](https://chaos-mesh.org/docs/faqs/) · [byteman-helper](https://github.com/chaos-mesh/byteman-helper) · [k8s_dns_chaos](https://github.com/chaos-mesh/k8s_dns_chaos)
- Chaos Mesh issues: [#3330 AttachNotSupported](https://github.com/chaos-mesh/chaos-mesh/issues/3330) · [#2751 byteman pid≠1](https://github.com/chaos-mesh/chaos-mesh/issues/2751) · [#3676 multi-container](https://github.com/chaos-mesh/chaos-mesh/issues/3676) · [#3195 stress throws](https://github.com/chaos-mesh/chaos-mesh/issues/3195) · [#3408 OpenShift](https://github.com/chaos-mesh/chaos-mesh/issues/3408) · [#3072 containerd inode](https://github.com/chaos-mesh/chaos-mesh/issues/3072) · [#2845 rootless k3s](https://github.com/chaos-mesh/chaos-mesh/issues/2845) · [#3275 ipset flush](https://github.com/chaos-mesh/chaos-mesh/issues/3275) · [#4477 partition direction](https://github.com/chaos-mesh/chaos-mesh/issues/4477) · [#3204 external targets](https://github.com/chaos-mesh/chaos-mesh/issues/3204) · [#4519 pod-failure stuck](https://github.com/chaos-mesh/chaos-mesh/issues/4519) · [#4019 NetworkChaos recovery](https://github.com/chaos-mesh/chaos-mesh/discussions/4019) · [#2438](https://github.com/chaos-mesh/chaos-mesh/issues/2438) · [#2305](https://github.com/chaos-mesh/chaos-mesh/issues/2305) · [#1081](https://github.com/chaos-mesh/chaos-mesh/issues/1081)
- k3s/Chaos Mesh setup: [Palark](https://palark.com/blog/chaos-mesh-in-kubernetes/) · [vCluster](https://www.vcluster.com/blog/chaos-mesh-with-vcluster)
- Tool comparisons: [Container Solutions](https://blog.container-solutions.com/comparing-chaos-engineering-tools) · [Chaos Engineering in the Wild (arXiv)](https://arxiv.org/html/2505.13654v1) · [Loft Labs top-5](https://www.vcluster.com/blog/analyzing-five-popular-chaos-engineering-platforms) · [LitmusChaos Hub](https://hub.litmuschaos.io/generic/pod-delete) · [Gremlin experiments](https://www.gremlin.com/docs/fault-injection-experiments)
- Istio: [Fault injection](https://istio.io/latest/docs/tasks/traffic-management/fault-injection/) · [DestinationRule reference](https://istio.io/latest/docs/reference/config/networking/destination-rule/) · [Rate limits](https://istio.io/latest/docs/tasks/policy-enforcement/rate-limit/) · [Local rate limit walkthrough](https://learncloudnative.com/blog/2022-09-08-ratelimit-istio) · [Performance and scalability](https://istio.io/latest/docs/ops/deployment/performance-and-scalability/)
- Kubernetes: [HPA](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/) · [Disruptions/PDB](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/) · [Safely drain a node](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/) · [In-place pod resize beta 1.33](https://kubernetes.io/blog/2025/05/16/kubernetes-v1-33-in-place-pod-resize-beta/) · [GA 1.35](https://kubernetes.io/blog/2025/12/19/kubernetes-v1-35-in-place-pod-resize-ga) · [rollout undo safely](https://www.plural.sh/blog/kubectl-rollout-undo-deployment/)
- SRE practice: [Generic mitigations (O'Reilly)](https://www.oreilly.com/content/generic-mitigations/) · [Google SRE Workbook incident response](https://sre.google/workbook/incident-response/) · [Netflix prioritized load shedding](https://netflixtechblog.com/keeping-netflix-reliable-using-prioritized-load-shedding-6cc827b02f94) · [Hystrix how it works](https://github.com/netflix/hystrix/wiki/how-it-works) · [Netflix 7-minute failover](https://opensource.com/article/18/4/how-netflix-does-failovers-7-minutes-flat) · [StackStorm auto-remediation](https://stackstorm.com/2015/10/05/auto-remediation-out-of-disk-space/) · [Rundeck automated diagnostics](https://docs.rundeck.com/docs/learning/solutions/automated-diagnostics/automation-beyond-triage.html) · [Shoreline](https://www.wwt.com/blog/shoreline-data-driven-aiops) · [Keptn closed-loop remediation](https://medium.com/keptn/closed-loop-remediation-with-custom-integrations-43bde377b796) · [K8s self-healing survey (IJERT)](https://www.ijert.org/automated-fault-remediation-and-self-healing-in-kubernetes-a-survey-of-failure-scope-llm-roles-and-post-remediation-verification-ijertv15is090091) · [Argo Rollouts abort vs rollback](https://oneuptime.com/blog/post/2026-08-02-argo-rollouts-abort-vs-rollback/view)
- Collateral mechanisms: [Thundering herd / connection pools](https://codefarm.in/guides/kubernetes/07-scenarios-and-interviews/the-thundering-herd) · [Pool exhaustion in k8s](https://cubeapm.com/blog/postgresql-connection-pool-exhausted-kubernetes/) · [Spring Boot cold start & autoscaling](https://medium.com/nordnet-tech/from-cold-start-to-high-load-tuning-spring-boot-for-resilience-autoscaling-on-kubernetes-31e161352405) · [Java warmup in Kubernetes](https://www.xflowpay.com/blog/best-practices-to-solve-java-warmup-issues-in-kubernetes)