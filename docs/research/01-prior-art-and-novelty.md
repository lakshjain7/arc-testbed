I've completed the research. Here is the report.

---

# ARC — Prior-Art and Novelty Report
### Counterfactual blast-radius prediction for remediation actions in microservices

**Bottom line up front:** the "predict the damage a remediation action will cause" framing is *not* unoccupied. Two 2026 arXiv preprints occupy it almost exactly, and one of them (`arXiv:2607.20005`) uses a 41-service Train Ticket deployment on Kubernetes with Chaos Mesh injection and partially-randomised action selection — i.e. your exact experimental setup. Neither is peer-reviewed, and both leave real gaps. Details in §3.

Throughout: **[C]** = confirmed, I fetched and read the source. **[S]** = from a search-result snippet only, not independently read. **[B]** = believed/inferred, flagged as such.

---

## 1. Industry systems that compute blast radius

### 1.0 The classification you asked for

| System | What it produces | Static topology / Measured post-hoc / **Predicted pre-action** | Conf. |
|---|---|---|---|
| AWS cell-based architecture | Design-time fault-isolation partition | **Static (design-time)** | [C] |
| AWS FIS | Runtime kill-switch on CloudWatch alarm | **Measured during** | [C] |
| Netflix ChAP | ΔSPS canary vs baseline | **Measured during/after** | [C] |
| Netflix Monocle | Criticality score ranking of dependencies | **Static heuristic prior** | [C] |
| Netflix Kayenta | Pass/fail score from Mann-Whitney U | **Measured post-hoc** | [C] |
| Meta Maelstrom | Constraint-satisfying drain plan + health feedback | **Static runbook + measured during** | [S] |
| LinkedIn LinkedOut/Waterbear | Request-scoped failure injection | **Static (scope is a control knob)** | [S] |
| MS Narya (OSDI'20) | Best mitigation action per predicted host failure | **Predicted, via online A/B bandits** | [S] |
| MS Gandalf (NSDI'20) | Is this rollout causing these faults? | **Measured, fast enough to gate** | [S] |
| Gremlin | Blast-radius *graph* (which hosts will be hit) | **Static target preview; user-set** | [C] |
| Steadybit | % of pods targeted + RBAC | **Static, user-set** | [S] |
| Harness Chaos | Chaos Guard policy gate; AI experiment suggestion | **Static policy** | [S] |
| Dynatrace Davis | Causal traversal of Smartscape → impact chain | **Measured post-hoc, topology-informed** | [S] |
| Datadog Watchdog RCA | "Impact" list of indirectly affected services | **Measured post-hoc (correlational)** | [S] |
| Causely | Blast radius = structurally dependent entities at risk | **Static reachability + fixed codebook** | [C] |
| New Relic Change Tracking | Change→golden-signal correlation | **Measured post-hoc** | [S] |
| Lightstep/SN Change Intelligence | Deployment regression ranking | **Measured post-hoc** | [S] |
| Komodor / Chronosphere | Change↔health correlation | **Measured post-hoc** | [S] |
| Overmind (Terraform) | Pre-apply blast radius over live resource graph | **Predicted pre-action (config-level)** | [C] |
| Datree / Kubescape | Admission-time policy lint | **Rule-based, no graph** | [S] |

**The crux, stated plainly:** nothing in commercial production computes a *counterfactual, per-service, quantitative ΔSLO forecast for a specific candidate remediation action*. Vendors do one of three things — bound the blast radius by architecture (AWS cells), let the operator choose it as a knob (Gremlin/Steadybit), or report it after the fact from a dependency graph (Dynatrace/Datadog/Causely). Overmind is the only commercial "predict before acting" product I found, and it predicts over *infrastructure resource dependencies*, not runtime service SLOs.

---

### 1.1 AWS

**Cell-based architecture.** The Well-Architected guidance *Reducing the Scope of Impact with Cell-Based Architecture*, published **20 September 2023**, extends the bulkhead best practice: partition the system so each replica serves a subset of clients, so a failure in one partition cannot reach the others. Blast radius here is an **architectural invariant decided at design time**, not a runtime computation. The document explicitly frames the win as "fault isolation, predictability, and testability." [C]
- https://docs.aws.amazon.com/wellarchitected/latest/reducing-scope-of-impact-with-cell-based-architecture/reducing-scope-of-impact-with-cell-based-architecture.html
- https://docs.aws.amazon.com/pdfs/wellarchitected/latest/reducing-scope-of-impact-with-cell-based-architecture/reducing-scope-of-impact-with-cell-based-architecture.pdf
- Related: AWS Fault Isolation Boundaries whitepaper; re:Invent 2018 ARC338 "How AWS Minimizes the Blast Radius of Failures" [S]
- Reference implementation: https://github.com/aws-solutions-library-samples/guidance-for-cell-based-architecture-on-aws
- Shuffle sharding writeup: https://hidekazu-konishi.com/entry/cell_based_architecture_and_shuffle_sharding_on_aws.html

**AWS Fault Injection Service (FIS).** Safety is entirely *reactive containment*: a **stop condition** is a CloudWatch alarm that aborts the experiment when a threshold trips; the **action duration** is itself a bound; and since **September 2024** there is an account/region-wide **safety lever** that halts all running experiments and blocks new ones. There is no impact forecast. [C/S]
- https://docs.aws.amazon.com/fis/latest/userguide/stop-conditions.html
- https://docs.aws.amazon.com/fis/latest/userguide/what-is.html
- https://aws.amazon.com/about-aws/whats-new/2024/09/aws-fault-injection-service-additional-safety-control
- Practitioner deep-dive: https://hidekazu-konishi.com/entry/chaos_engineering_on_aws_with_fault_injection_service.html

**Also worth citing for the project's motivation:** Tang, *Blast Radius Reduction for large-scale distributed systems*, SREcon24 EMEA — https://www.usenix.org/system/files/srecon24emea_slides-tang.pdf [S]

---

### 1.2 Netflix — the most detailed public system, and still not predictive

**ChAP (Chaos Automation Platform)** — Basiri et al., *Automating chaos experiments in production*, ICSE-SEIP 2019, **arXiv:1905.04648**. I read the full ar5iv rendering. [C]
- https://arxiv.org/abs/1905.04648 · https://ar5iv.labs.arxiv.org/html/1905.04648
- Netflix blog: https://netflixtechblog.com/chap-chaos-automation-platform-53e6d528371f

Mechanism: clone the target service into a **baseline** and a **canary** cluster, each ~1% of the original's size; Zuul routes a small treated population to the canary; FIT injects the fault on canary requests; Kayenta compares the two statistically.

Blast-radius controls are all **hard caps, not forecasts**:
- business hours only (weekdays 09:00–17:00)
- ≤ **5% of total traffic** across all concurrent experiments in any one region
- auto-abort on excessive customer impact
- no experiments during regional failovers

**Monocle** is the closest industrial thing to a "structural blast-radius prior." It fuses Atlas telemetry, Dapper-style tracing, and direct queries to running servers for config (timeouts, retry counts, thread-pool sizes), then auto-generates three experiment classes (hard failure; latency near the timeout; latency exceeding the timeout) and ranks them:

> **criticality score** = (dependency priority: RPC client = 1, Hystrix command = 100) × (max % of inbound requests triggering the dependency, 0–1000) × (retry factor = 1 + configured retries) × (number of wrapped interactions)
>
> **prioritization score** = criticality × safety score (±1) × experiment weight (failure = 3, latency = 2, latency-causing-failure = 1). Only positive-scored experiments run. [C]

This is a hand-designed static ranking over topology + config. It says *where risk plausibly lives*; it does not predict ΔSLO, and it is about *fault* injection, not about the damage of a *repair*.

**Kayenta / Automated Canary Analysis.** Two stages — metric retrieval and judgment. The default classifier uses a **Mann-Whitney U** test with a **98% confidence interval** that must fall entirely outside a tolerance band, plus an effect-size threshold (`allowedIncrease`/`allowedDecrease`) and a direction constraint. Final score = fraction of metrics classified Pass. Strictly post-hoc. [C/S]
- https://netflixtechblog.com/automated-canary-analysis-at-netflix-with-kayenta-3260bc7acc69
- https://spinnaker.io/docs/guides/user/canary/judge/
- Source: https://github.com/spinnaker/kayenta/blob/master/kayenta-judge/src/main/scala/com/netflix/kayenta/judge/classifiers/metric/MannWhitneyClassifier.scala

---

### 1.3 Meta — Maelstrom is the strongest industrial precedent for *action* safety

Veeraraghavan, Meza et al., *Maelstrom: Mitigating Datacenter-level Disasters by Draining Interdependent Traffic Safely and Efficiently*, **OSDI 2018**. [S — I could not parse the PDF; this is from the USENIX abstract, Meta Research page, and Morning Paper writeup]
- https://www.usenix.org/conference/osdi18/presentation/veeraraghavan
- https://tianyin.github.io/pub/maelstrom.pdf
- https://blog.acolyer.org/2018/10/24/maelstrom-mitigating-datacenter-level-disasters-by-draining-interdependent-traffic-safely-and-efficiently/
- https://research.facebook.com/publications/maelstrom-mitigating-datacenter-level-disasters-by-draining-interdependent-traffic-safely-and-efficiently/

Why it matters to ARC: **"drain traffic" is one of your candidate actions**, and Maelstrom's entire contribution is executing that action safely over a graph of *interdependent* drains, using health monitoring as feedback control so that specified constraints hold throughout. It is validated by full-datacenter drain drills and has mitigated 100+ outages over 4+ years.

But: the dependency structure and constraints are **encoded in human-authored runbooks**, and the feedback loop is **reactive** (observe health, slow down / stop), not a learned counterfactual predictor. Maelstrom answers "how do I execute this drain without breaking things"; ARC asks "how much would this drain break, before I run it."

---

### 1.4 LinkedIn

**Project Waterbear** is the umbrella resilience-engineering programme; **LinkedOut** is the request-level failure-injection framework under it. Triggers are injected via the LiX A/B framework or via a cookie propagated through the call stack by the Invocation Context (IC) framework. Failure modes: error, delay, timeout. Blast radius is bounded by **scoping injection to individual requests** — a containment mechanism, not a prediction. These are engineering blog posts, not papers. [S]
- https://engineering.linkedin.com/blog/2017/11/resilience-engineering-at-linkedin-with-project-waterbear
- https://www.infoq.com/news/2018/06/linkedout-failure-injection/

---

### 1.5 Microsoft — you didn't ask, but these are load-bearing for your related work

**Narya** — Levy et al., *Predictive and Adaptive Failure Mitigation to Avert Production Cloud VM Interruptions*, **OSDI 2020**. Predicts imminent host failure from multi-layer signals, then **decides which mitigation action to take** (live-migrate, soft-reboot, service-heal, etc.), and — critically — the decision engine uses an **online experimentation / bandit approach to continually estimate which mitigation works best**. 15 months in production, 26% reduction in VM interruptions vs. the previous static policy. [S]
- https://www.usenix.org/conference/osdi20/presentation/levy
- https://www.microsoft.com/en-us/research/wp-content/uploads/2020/10/osdi20_mitigation.pdf
- https://azure.microsoft.com/en-us/blog/advancing-failure-prediction-and-mitigation-introducing-narya/

**This is the strongest existing "learn the effect of a remediation action" system in production.** Differences from ARC: it operates at the **single physical host / VM** level with no service dependency graph; its outcome variable is VM interruption, not per-service ΔSLO; and effect is estimated by **online A/B in production**, not offline counterfactual prediction. Cite it and distinguish it explicitly — a reviewer will raise it.

**Gandalf** — Li et al., *Gandalf: An Intelligent, End-To-End Analytics Service for Safe Deployment in Large-Scale Cloud Infrastructure*, **NSDI 2020**. Spatial-temporal correlation of fault signals against ongoing rollouts, ensemble ranking to attribute blame, binary classifier for impact. 20 TB/day, 270K platform events/day, 2,000+ fault types. 92.4% precision / 100% recall for data-plane rollouts; 94.87% / 99.84% control-plane. [S]
- https://www.usenix.org/conference/nsdi20/presentation/li
- https://blog.acolyer.org/2020/02/28/microsoft-gandalf/

Gandalf is **attribution of an already-executing action**, not forecasting.

---

### 1.6 Chaos-engineering vendors — none of them predict blast radius

**Gremlin.** I read the glossary. Blast radius is defined as "the subset of a system that can be impacted by an experiment; the worst case impact of an experiment that discovers a flaw" and is explicitly a **user-set control** ("limit the blast radius to the smallest impact possible, then scale as you gain confidence"). Magnitude is the intensity knob. The "Blast Radius graph" in the UI is a **target-selection preview** — it shows which hosts/containers/K8s resources the experiment will touch, which is set enumeration, not impact prediction. Gremlin's genuinely automated features are **Detected Risks** (auto-identified misconfigurations / reliability anti-patterns) and a **Reliability Score** (0–100 per service; calculation not documented publicly). [C]
- https://www.gremlin.com/docs/resources-glossary
- https://www.gremlin.com/docs/fault-injection-scenarios
- https://aws.amazon.com/blogs/apn/how-gremlins-chaos-engineering-platform-validates-aws-operational-excellence-and-reliability/

**Steadybit.** Blast radius is a targeting percentage ("only target 10% of pods in a cluster") plus RBAC controls over who may run what. Not predictive. [S]
- https://steadybit.com/blog/blast-radius-and-access-control-strategies-for-a-safer-system/

**Harness Chaos Engineering** (built on **LitmusChaos**; ChaosNative was the Litmus commercial vendor and was acquired by Harness [B — not verified this session]). **Chaos Guard** is a policy layer that constrains which experiments may target what — a *permission* gate, not a forecast. Harness markets generative experiment suggestion ("analyse your architecture and operational data to suggest which experiments would teach you the most"), which is closer to Monocle's criticality ranking than to a damage predictor. [S]
- https://developer.harness.io/resilience-testing/chaos-engineering
- https://www.harness.io/blog/integrating-chaos-engineering-with-ai-ml-proactive-failure-prediction

**Verdict for §1:** No chaos vendor ships "blast radius prediction." Every one of them uses "blast radius" to mean *the scope you configure*, and the marketing verb is "limit," never "predict."

---

### 1.7 Observability / service-mesh vendors

**Dynatrace Davis AI.** Smartscape is a continuously-updated real-time dependency graph across applications, services, processes, hosts and network. Davis is described as a **deterministic, causation-based** reasoning engine that traverses Smartscape plus event timelines to find root cause and present the full impact chain. Dynatrace explicitly positions this against probabilistic correlation. But it operates on **problems that have already occurred**. Their newer messaging talks about AI agents proposing actions "constrained by what the platform definitively knows about upstream and downstream impact" — that is a constraint from static topology, not a learned action-effect model. [S]
- https://docs.dynatrace.com/docs/dynatrace-intelligence/root-cause-analysis/concepts
- https://www.dynatrace.com/news/blog/new-smartscape-make-better-decisions-with-real-time-dependency-graph-of-digital-systems/
- https://www.dynatrace.com/news/blog/build-trust-with-dynatrace-ai-driven-root-cause-and-impact-analysis/

**Datadog Watchdog RCA + Watchdog Impact Analysis.** Identifies interdependencies between APM anomalies, separates a "Critical Failure" from an "Impact" list of indirectly affected services, and cross-references RUM to find affected web/mobile pages. The docs' own phrasing gives the game away: "Any performance degradation listed in Impact is expected to recover once the Critical Failure is resolved" — i.e. impact is the observed downstream set of an **ongoing** incident. Commentary notes Watchdog "tends toward correlation rather than causation." [S]
- https://docs.datadoghq.com/watchdog/rca/
- https://docs.datadoghq.com/watchdog/impact_analysis/

**Causely** — the most interesting vendor for your purposes. I read their architecture docs. [C] Three data structures:
- **Topology graph**: continuously discovered horizontal connectivity + vertical layering.
- **Causality graph + Codebook**: a **built-in, static library of causal knowledge** — "a table where each column corresponds to a root cause and each row to a symptom," cells being P(symptom | cause). Environment-agnostic, instantiated over the discovered topology.
- **Attribute dependency graph**: functional relationships between measurable attributes (latency, throughput, utilisation, queue length), supporting learned functional relationships.

Causely does explicitly "compute the blast radius" — defined as *given entity foo is degraded, which entities are structurally dependent on it and therefore at risk*. **That is static reachability**, and their docs contain **no** description of predicting the impact of a proposed change before applying it. Notably, their own arXiv benchmark paper lists "what would happen if that change were made" as one of the *questions an agent reasoning over these layers could answer* — framed as a capability of the representation, not a shipped, evaluated feature. Read that as aspiration.
- https://docs.causely.ai/getting-started/how-causely-works/
- https://www.causely.ai/blog/semantics-in-observability
- Causely benchmark preprint: https://arxiv.org/abs/2605.18327

**New Relic.** Change Tracking correlates code/config/infra/CI-CD changes against golden signals, errors, anomalies and incidents, overlaid on performance graphs with a service dependency map. Applied Intelligence adds correlation and golden-signal classification. All **post-hoc correlation**. [S]
- https://newrelic.com/platform/change-tracking
- https://newrelic.com/platform/applied-intelligence

**Lightstep / ServiceNow Cloud Observability.** "Change Intelligence" ranks key operations by magnitude of performance change on the Deployments tab. Post-hoc regression attribution. **Note: being retired 1 March 2026** — don't lean on it as a live competitor. [S]
- https://lightstep.com/change-intelligence
- https://docs.lightstep.com/docs/view-individual-service-performance
- https://www.apica.io/blog/lightstep-cloud-observability-eol-keep-your-incident-management-workflows-running-with-apica-servicenow/

**Komodor.** Tracks every deployment/config/code change and correlates with node/pod/endpoint status. Change→effect correlation, post-hoc. Their rightsizing content uses "blast radius" informally to mean "how many services break if a recommendation is wrong" — an argument for caution, not a computed quantity. [S]
- https://komodor.com/learn/kubernetes-rightsizing-at-scale-without-breaking-reliability/

**Chronosphere.** Correlates metrics/logs/events to "understand the impact of system changes." Post-hoc. [S]
- https://chronosphere.io/solutions/infrastructure-observability/

---

### 1.8 Infra plan-impact and admission-time risk — adjacent, and the distinction matters

State the distinction in your paper roughly like this: **these tools reason over the *declared configuration graph*; ARC reasons over the *runtime behavioural graph*.** A Terraform dependency edge says "this security group is referenced by that instance." A service-dependency edge says "1,800 rps flow across this call and p99 there is coupled to p99 here." The former is exact and static; the latter is stochastic, workload-dependent, and is the only one that lets you talk about ΔSLO.

- **`terraform plan`** shows resource-level diffs only, with no notion of runtime consequence.
- **Overmind** is the strongest adjacent product: pre-apply, it queries the live AWS API read-only, maps dependencies across 100+ AWS resource types *and Kubernetes objects* (including resources created outside Terraform — console, CloudFormation), and combines that with "historical patterns learned from previous deployments." **This is genuinely predicted-before-acting**, at review time. It is still config-graph reachability + pattern heuristics, and it does not output a per-service SLO delta. [C]
  - https://overmind.tech/blog/difference-terraform-plan-and-overmind-blast-radius
- **Blast-Radius** (OSS Terraform graph visualiser): https://www.ibm.com/think/tutorials/blast-radius-review-the-impact-of-changes-in-your-terraform-files [S]
- **PreApply** (OSS deterministic TF risk scorer): https://github.com/akileshthuniki/PreApply [S]
- **Datree** — admission webhook blocking misconfigured K8s resources against a policy on create/apply/edit. Rule-based lint. https://www.datree.io/ [S]
- **Kubescape** — CNCF posture scanner + admission controller, increasingly via CEL ValidatingAdmissionPolicy. Rule-based. https://kubescape.io/blog/2024/08/04/cel-and-kubescape/ , https://kubernetes.io/blog/2023/03/30/kubescape-validating-admission-policy-library/ [S]

---

## 2. Academic literature

### 2.1 Work that predicts the effect of a *repair action* — the critical category

**Yes, it exists. Here it is, ranked by how close it is to ARC.**

---

**#1 — Dai, Yan, Lei, Li, Zhang. *Safe Remediation as Risk-Constrained Intervention Decision in Microservice Systems*. arXiv:2607.20005 [cs.AI], 22 July 2026.** [C — read in full]
- https://arxiv.org/abs/2607.20005 · https://arxiv.org/html/2607.20005v1
- Affiliations: Univ. of Sydney, TU Munich, ANU, Fujian Normal, Northeastern University (corresponding).

**This is, for practical purposes, your project.** What it does:
- Reformulates remediation as a **CMDP**: maximise repair success subject to a bounded **false remediation rate** (FRR ≤ ε_safe). Action space `𝒜 = 𝒜_exec ∪ {escalate, wait, no-op}`, with 12 named remediation actions (examples given: `restart_stateful`, `drain_connections`, `restart_db`), 4–6 applicable per fault type.
- **Three-dimensional risk decomposition**, per action:
  - **Blast radius `b(s,a)`** — a **learned diffusion kernel over graph powers**:

    `b(s,a) = (1/|V|) Σ_{v∈V} σ_b( Σ_{k=0}^{K_diff} α_k (A^k)_{v, tgt(a)} )`

    with row-normalised adjacency `A`, learnable `α_k ≥ 0` summing to 1, learned monotone sigmoid `σ_b`. **Fitted by binary cross-entropy against binary labels of whether service `v` showed a health-metric deviation within 60 s of the action.**
  - **Reversibility `ρ(s,a)`** — P(successful rollback within budget), trained on historical rollback logs; risk contribution `1 − ρ`.
  - **Epistemic uncertainty `u(s,a)`** — disagreement across an ensemble of 5 outcome predictors (mean L2 deviation from ensemble mean).
- **Offline RL backbone: Conservative Q-Learning (CQL) with Lagrangian constraint relaxation.** Retrieval-augmented outcome estimator. Per-dimension thresholding `τ(s)`. Contextual escalation gate over on-call load, business criticality, confidence.
- **Benchmark: Train Ticket, 41 services, Kubernetes (3 nodes, 8 vCPU / 32 GB each), Chaos Mesh, 11 fault categories aligned to the RCAEval taxonomy** (CPU, memory, disk I/O, socket, network delay/loss/partition, pod kill, HTTP abort, clock skew, DNS error). Prometheus 15 s metrics + Fluentd logs + Jaeger traces over 90 s windows. **8,320 decision records from 1,664 fault injections**, 70/15/15 split. Each action run in an isolated replica with full state reset, labelled resolved / partial / false-remediation on 60 s recovery.
- **Data-generating policy:** a deliberately *suboptimal operator policy* — softmax over action compatibilities (T = 0.12) with **25% uniform exploration** and load-dependent escalation probability.
- Results at ε_safe = 0.10: success 0.786 (+2.5 pts over Rule-Runbook), **FRR 0.112 (−39% vs Rule-Runbook's 0.183)**, escalation 36.5%, TTR 126 ± 3 s. Baselines: Rule-Runbook, LLM-Remediation without risk gating, Behaviour Cloning, CQL, CPO, CMDP-vanilla.
- **Its own gap statement, verbatim:** *"Blast radius and reversibility have been studied for static dependency and configuration analysis; no prior remediation work operationalizes these dimensions within a constrained decision framework."*

**Caveat, and it's an important one:** this is an unrefereed arXiv preprint, ~2 months old at time of writing, with no code or dataset link surfaced in the HTML I read. Its blast-radius model is a **shallow polynomial diffusion kernel on a static adjacency matrix with a binary per-service label** — not a GNN, not a regression on ΔSLO magnitude, and not conditioned on incident state beyond the action target. Verify it exists as described before citing; then attack it on exactly those points (see §3).

---

**#2 — Bindschaedler (MPI-SWS). *Rebooting Microreboot: Architectural Support for Safe, Parallel Recovery in Microservice Systems*. arXiv:2604.09963, April 2026.** [C — read in detail]
- https://arxiv.org/html/2604.09963

**This paper gives you your motivating numbers and your harm metric, and it validates the premise of your project.** Its thesis: the original microreboot assumption — that restarting one component is localised and safe — is false in modern microservices, because "restarting a single service can induce timeouts, retry storms, and cascading failures."

- **Blast radius definition:** "services that one restart affects." Measured on the **Alibaba cluster-trace-microservices-v2021** dataset (5,459 services, 11,690 edges): **median 8, P99 59, max 177.** Median fan-in for the most-connected service = 74 callers; median fan-out = 113 callees.
- **Harm definition** (use this verbatim in your paper): *"a remediation action that causes a service-level objective (SLO) regression of more than 10% for more than 30 seconds relative to the pre-action baseline."* SLOs: p99 latency < 100 ms, error rate < 0.1%. Baseline = 60 s pre-action mean. 5 s grace period after action initiation. Regression flagged if breach is continuous for 30 s after grace.
- **Seven-action ISA:** Restart, Drain, RestoreTraffic, CircuitBreak, RateLimit, Scale, RollbackConfig — each with explicit rollback semantics (restartable / reversible / compensatable). **Compare your action set to this.**
- **Recovery-group inference (§5.2):** build weighted call graph from trace spans in the failure window → traverse downstream from the symptom service → compute SCCs (restart-coupled components) with MAX_GROUP_SIZE = 30 → condense to a DAG for topological restart ordering; mark high-fan-in services (> 20 callers) as requiring drain. O(V+E); median 3.1 ms, P99 21 ms on the Alibaba graph.
- **Crucially: it does NOT predict harm before execution.** Offline analysis uses **post-hoc simulation propagating action effects through the call graph under worst-case assumptions**; online validation measures harm empirically after Chaos Mesh injection on DeathStarBench (Social Network, Hotel Reservation). The microkernel enforces *scope* and *effect-type* constraints; it does not forecast downstream impact of an approved action.
- Result: typed actuation reduces agent-caused harm by 95% in simulation (77% → 4%) and 0% harm online vs 90% for unconstrained agents.
- Also validated on a **Meta trace (392 services)**.

**This is the single most useful paper for your intro.** It establishes the problem is real and quantified, and its solution is *deterministic graph reachability + worst-case simulation* — which is precisely the baseline a learned counterfactual predictor should beat.

---

**#3 — Cai, Yu, Pi, Sun, Ma. *Can AI Remediate Backend Failures Safely? GuardedAct with Blast-Radius-Aware Sandboxing*. arXiv:2609.11264, 10 September 2026.** [C — abstract read]
- https://arxiv.org/abs/2609.11264
- Four phases: (1) ingest diagnosis report with topology + telemetry; (2) LLM generates ranked remediation candidates; (3) **simulate each action in a lightweight digital-twin sandbox that estimates blast radius and assigns a risk label**; (4) rollback-confidence gate auto-executes low-risk, escalates high-risk to humans.
- Benchmark: **DeathStarBench social-network**, 5 injected fault scenarios.
- Result: 87.4% recovery, **collateral damage 25.6% → 5.2% (−79.7%)**, at ~8 s added MTTR.
- Note: **simulation-based**, not a learned predictor, and the benchmark is small (5 scenarios). Also an unrefereed 2-week-old preprint at time of research.

---

**#4 — Wu, Tordsson, Acker, Kao. *MicroRAS: Automatic Recovery in the Absence of Historical Failure Data for Microservice Systems*. IEEE/ACM UCC 2020, pp. 227–236.** [S — abstract and secondary descriptions; IEEE full text not accessible]
- https://ieeexplore.ieee.org/document/9302828
- Author's page: https://lillywu.github.io/publications/

**The true intellectual ancestor of ARC, from 2020.** Model-driven recovery-action selection that trades off action effectiveness against recovery time. Critically: *"estimates the effectiveness of an action in terms of its effects of recovering the pinpointed faulty service **and its effects of interfering with other services**."* Components: a **graph-based system-state model (attributed graph) that tracks propagation of action effects**, an **action-effect estimator**, and a **fuzzy selector**. Uses real-time monitoring rather than historical failure traces. Results: 94.7% faulty-service recovery, **≥44.3% reduction in interference to other services** vs. baselines.

**This is the paper you must cite and differentiate against.** ARC's honest positioning relative to MicroRAS is: MicroRAS propagates effects through a hand-specified attributed-graph model with fuzzy rules; ARC *learns* the propagation function from injected data. That is a legitimate delta, but it is an incremental one.

Same group, adjacent: MicroRCA (NOMS 2020, code at https://github.com/elastisys/MicroRCA), MicroDiag (ICSE 2021), and Wu's PhD thesis *Automatic performance diagnosis and recovery in cloud microservices* (2022).

---

**#5 — *CRRL: A Causality-Based Reinforcement Learning Framework for Autonomous System Recovery*. arXiv:2607.03177, July 2026.** [C — partial, PDF extraction was lossy]
- https://arxiv.org/abs/2607.03177
- Causal graph of component dependencies + RL; intervenes on root causes rather than symptoms; explicitly aims to "distinguish between beneficial and harmful recovery actions." State = component health + metrics; actions = restart, config adjustment, component reset. **Uses Train Ticket**, with simulation-based failure injection and monitored recovery outcomes. Positions itself as advancing beyond MicroRAS-style trial-and-error by modelling causality explicitly.

---

**#6 — Bondaruk, Shkarupylo, Artemchuk. *From Anomaly Detection to Cause-Aware Response: Counterfactual Resilience Control for Cloud-Native Microservices*. Zenodo v4.1, 6 September 2026, DOI 10.5281/zenodo.22548162.** [C — Zenodo record read]
- https://zenodo.org/records/22548162
- **12,200 episode specifications; 109,800 paired counterfactual action rollouts; nine bounded response actions.** Ten independently regenerated master-seed benchmarks. Covers cause-aware response selection, baseline strategies, distribution shift, mixed incident mechanisms, **conformal uncertainty gating**, utility sensitivity.
- **The decisive caveat, in their own words:** it is *"an abstract mechanism-controlled microservice availability-response simulator"* — **all data are synthetic**, and *"the results therefore support reproducible comparison of response-selection strategies under the documented simulator assumptions, but do not establish production Kubernetes effectiveness."*
- **This is a direct, exploitable gap for ARC:** they have the counterfactual-action framing but no real system. You have the real system.
- No venue or arXiv link found; affiliation is G.E. Pukhov Institute (Ukraine).

---

**#7 — *R2Act*: *Can LLMs Really Recover Microservice Failures? A Recovery-Aware Evaluation of Diagnosis-to-Action Reasoning*. arXiv:2607.04623, July 2026.** [C]
- https://arxiv.org/html/2607.04623
- 302 quality-audited Kubernetes incidents on **Online Boutique**, 6 services, 8 fault categories. **Seven recovery operations: restart service, scale out, roll back deployment, increase memory limit, roll back config, repair DNS/dependency, no action** — nearly identical to your action set.
- **Explicitly does NOT measure collateral damage, blast radius, or side effects on other services.** Validity checking is confined to "targets the correct service and operation type," and live replay only checks that "the replay restores service health" of the *directly affected* service, not downstream impact. The authors flag this as a scope limitation.
- **Quotable as the gap.** This is a 2026 recovery-action benchmark that concedes it ignores exactly what ARC measures.

---

**#8 — Other action-side work**
- **MicroRemed: Benchmarking LLMs in Microservices Remediation** — arXiv:2511.01166, 3 Nov 2025; 24 pp. Live interactive environment that launches real microservice systems, injects controlled failures, and requires the model to generate executable remediation code. Also proposes **ThinkRemed**, a multi-agent SRE-emulating framework. Code: https://github.com/LLM4AIOps/MicroRemed [S]
- **E2E-REME: Towards End-to-End Microservices Auto-Remediation via Experience-Simulation Reinforcement Fine-Tuning** — Zhang, Zhai, Jia, He, Duan, Liu, Ding, Li; arXiv:2604.11094, April 2026. The name promises simulation of remediation outcomes. **[Unverified — the PDF would not parse; I could extract only title/authors/keywords. Chase this one down, it may be very close.]** https://arxiv.org/abs/2604.11094
- **STRATUS: A Multi-agent System for Autonomous Reliability Engineering of Modern Clouds** — arXiv:2506.02009. Specialised agents (detection/diagnosis/mitigation) in a state machine, with a formal safety specification called **Transactional No-Regression (TNR)**: segment agent interventions into transactionally bounded stages, each non-regressing w.r.t. a measurable health metric. A *verification* discipline rather than a predictor, but the right kind of related work for your safety-gate framing. [S] https://arxiv.org/abs/2506.02009
- **He, Shao, Wang, Shi, Chen, Wang. *Predicting Effect and Cost of Microservice System Evolution Using Graph Neural Network*.** ICSOC 2023, LNCS 14419, DOI 10.1007/978-3-031-48421-6_8. Uses a GNN over historical data to predict the **effect and cost of candidate evolution schemes** before applying them to the real system. The *design-time architectural* analogue of ARC. [S] https://link.springer.com/chapter/10.1007/978-3-031-48421-6_8
- **Learning from Change: Predictive Models for Incident Prevention in a Regulated IT Environment** — ICSE-SEIP 2026, DOI 10.1145/3786583.3786876, arXiv:2604.13462. LightGBM on change metadata to predict whether a deployment will cause an incident; emphasises *actionable* features an engineer can change before deploying. Tabular, no dependency graph. [S]

---

### 2.2 RCA on service dependency graphs — the diagnosis line (all of it diagnoses; none of it predicts action effect)

| System | Paper | Venue / Year | Link |
|---|---|---|---|
| MicroScope | Identifying causes of performance issues by cause-effect graph | ICSOC 2018 | [S] |
| MicroRCA | Root Cause Localization of Performance Issues in Microservices | IEEE/IFIP NOMS 2020 | https://dl.acm.org/doi/10.1109/NOMS47738.2020.9110353 · code https://github.com/elastisys/MicroRCA |
| MicroRAS | Automatic Recovery in the Absence of Historical Failure Data | IEEE/ACM UCC 2020 | https://ieeexplore.ieee.org/document/9302828 |
| Sage | Practical & Scalable ML-Driven Performance Debugging in Microservices | **ASPLOS 2021** | https://research.google/pubs/sage-practical-scalable-ml-driven-performance-debugging-in-microservices/ · extended: https://arxiv.org/abs/2112.06263 |
| MicroHECL | High-Efficient RCA in Large-Scale Microservice Systems | ICSE-SEIP 2021 | [S] |
| MicroRank | (trace-based RCA, spectrum + PageRank) | **WWW 2021** | [S] |
| TraceRCA | (trace-based RCA) | IWQoS 2021 | [S] |
| MicroDiag | Fine-grained performance diagnosis for microservice systems | ICSE 2021 | https://lillywu.github.io/publications/ |
| Groot | Event-graph-based Approach for RCA in Industrial Settings | **ASE 2021** | https://ieeexplore.ieee.org/document/9678708 · https://innovation.ebayinc.com/stories/groot-ebays-event-graph-based-approach-for-root-cause-analysis/ |
| DejaVu | Actionable and Interpretable Fault Localization for Recurring Failures | **FSE 2022** | DOI 10.1145/3540250.3549092 · arXiv:2207.09021 · code https://github.com/NetManAIOps/DejaVu |
| CIRCA | Causal Inference-Based RCA for Online Service Systems with Intervention Recognition | **KDD 2022** | arXiv:2206.05871 · code https://github.com/NetManAIOps/CIRCA |
| Eadro | End-to-end troubleshooting for microservices on multi-source data | **ICSE 2023** | [S] |
| Nezha | Interpretable Fine-Grained Root Causes Analysis on Multi-modal Observability Data | **FSE 2023** | [S] |
| DiagFusion | Robust Failure Diagnosis of Microservice System through Multimodal Data | IEEE TSC 2023 | arXiv:2302.10512 · https://nkcs.iops.ai/wp-content/uploads/2023/12/TSC23-DiagFusion.pdf |
| CausIL | Causal Graph for Instance Level Microservice Data | **WWW 2023** | DOI 10.1145/3543507.3583274 |
| CausalRCA | Causal inference based fine-grained root cause localization | JSS vol. 203, 2023 | DOI 10.1016/j.jss.2023.111724 |
| Murphy | Performance Diagnosis of Distributed Cloud Applications | **SIGCOMM 2023** | [S] |
| TraceDiag | Adaptive, Interpretable, Efficient RCA on Large-Scale Microservice Systems | 2023 | arXiv:2310.18740 |
| RUN | Root Cause Analysis in Microservice Using Neural Granger Causal Discovery | **AAAI 2024** | https://ojs.aaai.org/index.php/AAAI/article/view/27772 |
| BARO | Robust RCA via Multivariate Bayesian Online Change Point Detection | **FSE 2024** (PACMSE) | DOI 10.1145/3660805 · arXiv:2405.09330 |
| DeepHunt | Interpretable Failure Localization for Microservice Systems | TOSEM 2024 | https://nkcs.iops.ai/wp-content/uploads/2024/10/24_TOSEM_DeepHunt.pdf |
| — | RCA for Microservice System based on Causal Inference: How Far Are We? | **ASE 2024** | arXiv:2408.13729 · DOI 10.1145/3691620.3695065 |
| DynaCausal | Dynamic Causality-Aware RCA for Distributed Microservices | 2025 | arXiv:2510.22613 |

Surveys worth citing:
- **Failure Diagnosis in Microservice Systems: A Comprehensive Survey and Analysis** — arXiv:2407.01710 (98 papers, 2003–present; compiles datasets, toolkits, metrics). [C — abstract only; the full PDF has the taxonomy tables you'd want]
- **A Comprehensive Survey on Root Cause Analysis in (Micro) Services** — arXiv:2408.00803
- **AI for IT Operations (AIOps) on Cloud Platforms: Reviews, Opportunities and Challenges** — arXiv:2304.04661
- **SoK: Microservice Architectures from a Dependability Perspective** — arXiv:2503.03392
- **Resilient Microservices: A Systematic Review of Recovery Patterns, Strategies, and Evaluation Frameworks** — arXiv:2512.16959
- Curated list: https://github.com/OpsPAI/awesome-AIOps [C]

**The observation that makes ARC's case:** across ~25 systems in this table, the output is always *a ranked list of suspect components*. Zero of them output *what will happen if I do X*. Their action model is implicit and terminal: "we found the culprit, a human will now do something."

---

### 2.3 GNNs for failure propagation / performance prediction in microservices

- **A Survey on Graph Neural Networks for Microservice-Based Cloud Applications** — Sensors 22(23):9492, MDPI 2022. https://www.mdpi.com/1424-8220/22/23/9492 [S]
- **GRAF: Graph Neural Network-Based SLO-Aware Proactive Resource Autoscaling Framework for Microservices** — IEEE/ACM Transactions on Networking, 2024, DOI 10.1109/TNET.2024.3393427. Uses front-end workload + distributed tracing + GNN to **estimate the impact of traffic changes and make proactive allocation decisions**. [S] — **This is the closest "learned action-effect model" in the autoscaling literature and you should cite it**: it predicts the SLO consequence of a *scaling* decision. Difference: single action type, benefit-oriented (will SLO be met), not damage-oriented, and no incident context.
- **Graph-PHPA: Graph-based Proactive Horizontal Pod Autoscaling for Microservices using LSTM-GNN** — arXiv:2209.02551 [S]
- **Graph Neural Networks for Metrics Prediction in Microservice Architecture** — Springer, DCRNN-based; predicts well with and without anomalies. DOI 10.1007/978-3-031-65308-7_24 [S]
- **Utilizing Graph Neural Networks for Effective Link Prediction in Microservice Architectures** — GAT over call graphs, arXiv:2501.15019 [S]
- **Service dependency modeling and failure propagation prediction in distributed systems based on graph neural networks** — *Discover Artificial Intelligence*, 2026, DOI 10.1007/s44163-026-01213-3. **[Unverified — Springer redirected to an auth gate; I could not read it.]** From the snippet: GNN framework for service-dependency modelling + failure-propagation prediction, high precision/recall, reduced detection time. **This is the one to chase for "GNN predicts which services a failure reaches."** Note it appears to predict propagation of *faults*, not of *actions*.
- **STLGT: Scalable Trace-Based Linear Graph Transformer for Tail Latency Prediction in Microservices** — arXiv:2604.26422 [S]
- **Multi-Level Service Performance Forecasting via Spatiotemporal GNNs** — arXiv:2508.07122 [S]
- **Joint Temporal-Structural Representation Learning for Distributed Fault Discrimination in Microservice Architectures** — arXiv:2605.01776 [S]
- **Robust Failure Diagnosis of Microservice System through Multimodal Data** (DiagFusion) — GNN learns failure propagation between service instances. arXiv:2302.10512 [S]
- **AID: Efficient Prediction of Aggregated Intensity of Dependency in Large-scale Cloud Systems** — arXiv:2109.04893 [S]

---

### 2.4 Counterfactual / causal inference for cloud systems

- **Sage** (ASPLOS 2021) — the most important one for you. Sage uses **counterfactuals to determine causal effects, asking what outcomes would be if a microservice's state had been different**, generating realistic counterfactuals from historical tracing data (CVAE + causal Bayesian network over the service graph) and predicting the resulting end-to-end latency, then applying corrective actions. [S/C-partial]
  - https://research.google/pubs/sage-practical-scalable-ml-driven-performance-debugging-in-microservices/
  - Extended: https://arxiv.org/abs/2112.06263 · NSF copy: https://par.nsf.gov/servlets/purl/10323345

  **Sage is ARC's mirror image: it is counterfactual over *fault states* (what if service X were healthy?), ARC is counterfactual over *actions* (what if I restarted X?).** That is a clean, defensible way to position yourself, and Sage gives you an architectural template (learned generative model over the dependency graph) plus a credible ASPLOS-grade validation methodology.
- **NetCause: Counterfactual Learning for Root Cause Analysis in Large-Scale Networks** — arXiv:2606.13543. Models incidents as graph-temporal processes, uses **counterfactual simulation** to rank candidate root causes. [S]
- **Robust Root Cause Diagnosis using In-Distribution Interventions** — arXiv:2505.00930. IDI predicts root causes as nodes satisfying (a) anomaly and (b) *fix*: had the node assumed usual values, the target would not be anomalous. Explicitly a counterfactual-repair criterion — but for *diagnosis*. [S]
- **Formalizing and falsifying causal pathways of rare events** — arXiv:2605.31254 [S]
- **When Graph Neural Network Meets Causality: Opportunities, Methodologies and An Outlook** — arXiv:2312.12477 [S]
- **Graph Neural Networks for Treatment Effect Prediction** — arXiv:2403.19289. Generic ITE-on-graphs methodology; useful for your estimator design and for the standard critique that ITE evaluation "renders the use of simulated data imperative" — which is exactly why your randomised-action injection design is defensible. [S]
- **Agent-Specific Effects: A Causal Effect Propagation Analysis in Multi-Agent MDPs** — arXiv:2310.11334 [S]

---

### 2.5 Chaos engineering + ML

Honest assessment: **this literature is thin and mostly vendor content.** The one real paper is the Netflix ChAP/Monocle paper (§1.2, arXiv:1905.04648, ICSE-SEIP 2019). Beyond that:
- Harness blog, *Integrating Chaos Engineering with AI/ML for Proactive Failure Prediction* — https://www.harness.io/blog/integrating-chaos-engineering-with-ai-ml-proactive-failure-prediction [S]
- **FaultForge: A Business-Semantics-Driven Cross-Layer Fault Injection Framework for Microservice** — Zenodo record 21695950 [S]
- **FastFI: Enhancing API Call-Site Robustness in Microservice-Based Systems with Fault Injection** — arXiv:2601.14800 [S]
- **Resilience Evaluation of Kubernetes in Cloud-Edge Environments via Failure Injection** — arXiv:2507.16109 [S]
- **A measurement substrate for agentic Kubernetes operations** — arXiv:2605.23058 [S]

Beware: searching "chaos engineering + machine learning" is heavily polluted by *chaotic-dynamical-systems* ML papers (Lorenz attractors, reservoir computing). Filter them out.

---

### 2.6 Safe action selection / offline RL / auto-remediation safety gates

- **CQL + Lagrangian CMDP** as applied to remediation — arXiv:2607.20005 (§2.1 #1). Its baselines (Behaviour Cloning, CQL, CPO, CMDP-vanilla) are the right baseline set for you too.
- **Safe Deployment of Offline Reinforcement Learning via Input Convex Action Correction** — arXiv:2507.22640; also *Computers & Chemical Engineering* S0098135425005381. Deployment-time safety via a learned **state-conditioned cost model convex in the action** (PICNN), enabling principled correction of unsafe actions. Domain is chemical process control, but **the technique transfers directly to ARC**: your damage predictor *is* a state-conditioned action cost model, and PICNN convexity would give you tractable safe-action search. [S]
- **Guiding Offline RL Using a Safety Expert** — CODS-COMAD 2024, DOI 10.1145/3632410.3632423 [S]
- **Offline Goal-Conditioned RL for Safety-Critical Tasks with Recovery Policy** — arXiv:2403.01734 [S]
- **VeriGuard: Enhancing LLM Agent Safety via Verified Code Generation** — arXiv:2510.05156 [S]
- **STRATUS / Transactional No-Regression** — arXiv:2506.02009 [S]
- **From Risk Classification to Action Plan Remediation: A Guardrail Feedback Driven Framework for LLM Agents** — arXiv:2606.05805 [S]
- **Safety-Contract Graph Multi-Agent RL for Autonomous Network Security Response** — arXiv:2606.13832 [S]
- Microsoft patent, *Safe-operation-constrained reinforcement-learning-based application manager* — US 11,042,640 [S]

**Gap note:** there is essentially **no offline-RL-for-cloud-operations literature with real system data**. Everything either uses a simulator or is a single-institution production system with unreleased data. That is a genuine opening.

---

### 2.7 Papers that use Train Ticket

**Origin.** Zhou, Peng, Xie, Sun, Ji, Liu et al., *Fault Analysis and Debugging of Microservice Systems: Industrial Survey, Benchmark System, and Empirical Study*, **IEEE TSE 47(2):243–260** — the paper that produced Train Ticket. **Best Paper Award.** DOI 10.1109/TSE.2018.2887384. [S]

**Repo facts** [C, from the GitHub README]: 41 microservices in the current version; polyglot — Java (Spring Boot / Spring Cloud), Node.js (Express), Python (Django), Go (Webgo); MongoDB + MySQL. Companion query/load-generation repo: **https://github.com/FudanSELab/train-ticket-auto-query**. Serverless variant: https://github.com/FudanSELab/serverless-trainticket.
- Main repo: https://github.com/FudanSELab/train-ticket · Wiki: https://github.com/fudanselab/train-ticket/wiki

**Service-count warning — this will bite you in review.** Different papers report **41**, **50**, and **64** services for Train Ticket depending on version and on whether databases/infrastructure pods are counted. The README says 41; RCAEval and TORAI say 64; the fault-propagation benchmark says 50. **State your version tag and your counting rule explicitly.**

**Notable papers using it:**

| Paper | Venue/Year | What it measured on Train Ticket |
|---|---|---|
| Zhou et al., Fault Analysis and Debugging of Microservice Systems | TSE 2021 | 22 industrial fault cases replicated; debugging-practice empirical study |
| Delta Debugging Microservice Systems | ASE 2018 | Minimising failure-inducing config/deployment deltas |
| Latent Error Prediction and Fault Localization ... from System Trace Logs | FSE 2019 | Latent-error prediction from trace logs |
| MicroHECL | ICSE-SEIP 2021 | Root-cause localisation efficiency at scale |
| DeepTraLog: Trace-Log Combined Microservice Anomaly Detection via Graph-based DL | ICSE 2022 | Graph-based anomaly detection on unified trace-log graphs |
| Enjoy your observability: an industrial survey of microservice tracing and analysis | EMSE 2022 | Tracing practice survey |
| Nezha | FSE 2023 | Fine-grained RCA; released a TrainTicket + OnlineBoutique multimodal dataset |
| Eadro | ICSE 2023 | End-to-end anomaly detection + RCA; "Eadro-TT" dataset, call depth 3 |
| BARO | FSE 2024 | RCA on TT + Sock Shop + Online Boutique, 1 master + 5 worker K8s |
| RCAEval | WWW'25 Companion | TT in RE1/RE2/RE3; 6 fault types on TT in RE2 |
| Fault Propagation-Aware Benchmark (Fang et al.) | 2025/2026 | 1,430 validated failure cases from 9,152 injections; TT at 50 services; max call depth 7 |
| TORAI | arXiv:2604.13522 | Multi-source RCA, TT on 5-worker K8s |
| FastFI | arXiv:2601.14800 | API call-site robustness via fault injection |
| Safe Remediation (2607.20005) | arXiv 2026 | **41-service TT + Chaos Mesh, 1,664 injections, remediation risk** |
| CRRL (2607.03177) | arXiv 2026 | Causality-based RL recovery |
| Automated assessment of microservice architecture and performance | JSS 2026 | 4 structurally distinct TT releases + DeathStarBench |

Also relevant: **Benchmarks for End-to-End Microservices Testing** — arXiv:2306.05895, and **DeathStarBench** (ASPLOS 2019, DOI 10.1145/3297858.3304013), the standard alternative benchmark that Rebooting Microreboot and GuardedAct both use.

---

## 3. The novelty gap — honest assessment

### 3.1 What has already been done

Be clear-eyed. Every individual ingredient of ARC exists:

1. **"Blast radius" as a quantified, per-service, SLO-denominated harm metric for remediation actions** — done. *Rebooting Microreboot* (arXiv:2604.09963, Apr 2026) defines harm as >10% SLO regression for >30 s and measures blast-radius distributions (median 8, P99 59, max 177) on Alibaba traces.
2. **A learned model that maps (state, action) → blast radius on a service graph** — done. arXiv:2607.20005 (Jul 2026) fits a learned graph-diffusion kernel `b(s,a)` with learnable weights over powers of the adjacency matrix, supervised by per-service health deviation within 60 s of the action.
3. **On Train Ticket, 41 services, Kubernetes, Chaos Mesh, with partially randomised action selection** — done. Same paper: 1,664 fault injections → 8,320 decision records, softmax policy with 25% uniform exploration.
4. **Counterfactual paired action rollouts at scale** — done. Bondaruk et al. (Zenodo 22548162): 109,800 paired counterfactual rollouts over 9 actions — **but entirely in a synthetic simulator, disclaimed by the authors as not establishing production K8s effectiveness.**
5. **Pre-execution simulation of action impact with a risk label** — done. GuardedAct (arXiv:2609.11264, Sep 2026), digital-twin sandbox, DeathStarBench, collateral damage 25.6%→5.2%.
6. **Estimating a recovery action's interference with non-target services** — done, and long ago. MicroRAS (UCC 2020): attributed-graph state model + action-effect estimator + fuzzy selector, ≥44.3% interference reduction.
7. **Learning which mitigation action works, in production** — done. Narya (OSDI 2020), via online bandits at host granularity.
8. **Predicting the SLO effect of a scaling action** — done. GRAF (IEEE/ACM ToN 2024).
9. **Counterfactual generative modelling over a microservice dependency graph** — done. Sage (ASPLOS 2021), but counterfactual over *fault states*, not actions.

**If you submit "we predict the blast radius of a remediation action on Train Ticket using injected faults," a competent reviewer will find arXiv:2607.20005 and reject it as concurrent-or-prior work.** You should assume this.

### 3.2 What is actually still unclaimed

There are five real gaps. Ranked by defensibility:

**(a) Unconfounded data from uniformly random action selection.** This is your strongest card and I suspect you haven't realised it. arXiv:2607.20005 generates its data with a *softmax-over-compatibility policy* (T = 0.12) with only 25% uniform exploration. That means action choice is **correlated with incident state**, so the learned `b(s,a)` is fitted on confounded observational data and its "counterfactual" claim is not identified — it is a conditional-association model wearing causal clothes. **Your design — RANDOMLY chosen actions — gives you a genuine randomised controlled trial over the action space, which makes the causal estimand identified by construction.** No existing work on real microservice systems has this. Lead with it. Frame ARC as *the first randomised-intervention dataset and estimator for remediation-action damage on a real microservice deployment*, and show empirically how much the biased-policy estimator is off by (you can simulate their policy on your own data as an ablation — that is a killer experiment).

**(b) Per-service ΔSLO regression, not a scalar or binary label.** 2607.20005's blast radius collapses to a scalar in [0,1], supervised by a **binary** per-service "deviation yes/no" label. Rebooting Microreboot's harm is binary too (>10% for >30 s). **Predicting the magnitude vector — ΔSLO per service — is genuinely unclaimed**, and it is strictly more useful operationally (it lets you say "this rollback will cost service X 40 ms of p99 and service Y nothing").

**(c) A released public dataset of (incident state, action, per-service ΔSLO).** I searched specifically for this and found nothing. RCAEval, Nezha, GAIA, AIOps-challenge, the fault-propagation benchmark — **all label root causes, none label action outcomes.** R2Act has actions but explicitly no collateral-damage labels. The only action-outcome corpus is synthetic (Zenodo 22548162). **This may be ARC's most durable contribution, above the model.** Plan to release it.

**(d) Architecture: action-conditioned GNN vs fixed diffusion kernel.** 2607.20005 uses a shallow polynomial `Σ α_k A^k` on a *static* adjacency matrix. That cannot represent workload-dependent propagation, asymmetric edges, retry/timeout configuration, or the difference between "restart a stateless replica" and "restart the database." A message-passing GNN conditioned on the action type and target, over a *traffic-weighted, runtime-derived* graph, is a clear technical delta — and you can use their kernel as a baseline.

**(e) Generalisation to unseen topology / calibrated uncertainty.** Nobody has shown a damage predictor that transfers to a service graph it was not trained on. If ARC trains on Train Ticket and evaluates zero-shot on Online Boutique / Sock Shop / DeathStarBench, that is a strong, checkable, unclaimed result. Likewise, calibrated predictive intervals on ΔSLO (conformal prediction — the Bondaruk work uses conformal gating in simulation, nobody has done it on real data).

**(f) Separating damage from efficacy.** Almost all prior work conflates "did the action fix the fault" with "was the action safe." 2607.20005 does separate them (success vs FRR) but its FRR is a binary. Treating **damage as an independent predicted quantity, orthogonal to efficacy**, and showing the Pareto frontier between them, is clean and defensible.

### 3.3 Recommended positioning

Do not claim "first system to predict blast radius of remediation actions." That claim is dead.

Claim instead, roughly: *"Prior work estimates remediation risk from observational logs generated by biased operator policies, or from deterministic graph reachability, and reduces impact to a binary or scalar. We construct the first randomised-intervention corpus of remediation actions on a real 41-service Kubernetes deployment, and show that (i) estimators trained on policy-biased data systematically mis-rank action damage, and (ii) an action-conditioned GNN predicting per-service ΔSLO magnitude outperforms static reachability, diffusion-kernel, and worst-case-simulation baselines, and transfers zero-shot to unseen topologies."*

Baselines you are now obliged to include: static downstream reachability (Rebooting Microreboot §5.2), the learned diffusion kernel (2607.20005), worst-case call-graph propagation simulation, and a no-graph tabular regressor. That set makes for a convincing paper regardless of which way the results go.

---

## 4. Datasets

### 4.1 Microservice fault datasets with labelled root causes (none label action impact)

| Dataset | Systems | Scale | Modalities | Link | Conf. |
|---|---|---|---|---|---|
| **RCAEval** (RE1/RE2/RE3) | Online Boutique (12 svc), Sock Shop (15), Train Ticket (64) | 735 cases total: RE1 375 (5 fault types, metrics), RE2 270 (6 types, M+L+T), RE3 90 (5 code-level faults, M+L+T) | metrics, logs, traces | https://github.com/phamquiluan/RCAEval · arXiv:2412.17015 · DOI 10.1145/3701716.3715290 | [C] |
| **Fault Propagation-Aware Benchmark** (Fang et al.) | Train Ticket (50 svc, max call depth 7) | **1,430 validated failure cases from 9,152 injections**, 25 fault types in 6 categories (Resource, Network, HTTP, Code/JVM, DNS, Time), hierarchical ground truth (service/pod/container/code) | multimodal | arXiv:2510.04711 · DOI 10.1145/3797100 — **release promised, was "under construction" at submission** | [C] |
| **Nezha** | Train Ticket + Online Boutique | CPU contention/consumption, network delay, plus Java/Python code-defect injections | logs, metrics, traces | FSE 2023; dataset via NetManAIOps | [S] |
| **Eadro-TT** | Train Ticket | call depth 3 | multimodal | ICSE 2023 | [S] |
| **GAIA** | MicroSS simulation (10 service instances: mobile, log, web, DB, Redis) | max propagation depth **2** — a known weakness; root cause often coincides with the obvious symptom | metrics, logs, traces | https://github.com/CloudWise-OpenSource/GAIA-DataSet | [C/S] |
| **AIOps Challenge 2020** | China Mobile Zhejiang production microservices | — | metrics, traces | http://iops.ai/dataset_list/ | [S] |
| **AIOps Challenge 2021** | Two large commercial banking systems (Tsinghua) | — | logs, metrics, traces, **topology** | http://iops.ai/dataset_list/ | [S] |
| **AIOps Challenge 2022** | Hipster Shop (Tsinghua) | — | logs, metrics, traces, topology | http://iops.ai/dataset_list/ | [S] |
| **AIOps Challenge 2023** | 50 services / 200 pods | **80 cascading propagation faults annotated** (e.g. service-timeout chain from a DB failure) | metrics, logs, traces | — | [S] — **chase this; annotated *cascades* are the closest public thing to impact labels** |
| **LO2** | Microservice API anomaly dataset | — | logs + metrics | arXiv:2504.12067 | [S] |
| **Constructing Large-Scale Real-World Benchmark Datasets for AIOps** | — | — | — | arXiv:2208.03938 | [S] |

### 4.2 Production traces (topology + workload, no faults)

- **Alibaba cluster-trace-microservices-v2021** — ~20,000 microservices, >10,000 bare-metal nodes, 12 hours; call dependencies, response time, call rates. https://github.com/alibaba/clusterdata/blob/master/cluster-trace-microservices-v2021/README.md — **this is the graph Rebooting Microreboot measured blast radius on (5,459 services, 11,690 edges after filtering).** [C/S]
- **Alibaba cluster-trace-microservices-v2022** — 13 days, adds service ID within call graph. https://github.com/alibaba/clusterdata/tree/master/cluster-trace-microservices-v2022 [S]
- Caveat: **Systemizing and Mitigating Topological Inconsistencies in Alibaba's Microservice Call-graph Datasets**, ICPE 2024, DOI 10.1145/3629526.3645043 — the raw traces have topology errors; reconstruction tooling at https://github.com/docc-lab/casper. Read this before you use the Alibaba data. [S]
- **Azure Public Dataset** — VM traces (2017, 2019), Azure Functions invocation + blob traces. https://github.com/Azure/AzurePublicDataset [S]
- **Google cluster-data** — https://github.com/google/cluster-data [S]
- **Huawei Cloud serverless traces** — https://github.com/sir-lab/data-release [S]
- **Pre-processed Tracing Data for Popular Microservice Benchmarks** (Illinois Data Bank IDB-6738796) — https://databank.illinois.edu/datasets/IDB-6738796 [S]
- **Loghub** — https://github.com/logpai/loghub [S]

### 4.3 Action-outcome datasets (the category ARC would fill)

Only two exist, and both are unsatisfying:
- **Bondaruk et al. counterfactual resilience benchmark** — 12,200 episodes, 109,800 paired counterfactual rollouts, 9 actions, 10 master-seed regenerations. **Fully synthetic**, DOI 10.5281/zenodo.22548162. [C]
- **R2Act** — 302 Kubernetes incidents on Online Boutique, 7 recovery operations, real replay validation — **but no collateral-damage labels**. arXiv:2607.04623. [C]
- **MicroRemed** — live interactive environment rather than a static dataset; you can generate outcomes from it. https://github.com/LLM4AIOps/MicroRemed [S]

**There is no public dataset of (incident, action, per-service ΔSLO) from a real microservice deployment.** I searched for this directly. Building and releasing one is a contribution in itself.

---

## 5. Confidence ledger

**Read in full or in substantial part (high confidence):** ChAP/Monocle paper (arXiv:1905.04648); Safe Remediation (arXiv:2607.20005, incl. the blast-radius formula, data generation, and gap statement); Rebooting Microreboot (arXiv:2604.09963, incl. harm definition, recovery-group algorithm, blast-radius statistics, and explicit statement that it does not predict); GuardedAct abstract (arXiv:2609.11264); R2Act (arXiv:2607.04623); Bondaruk Zenodo record incl. the synthetic-data disclaimer; RCAEval structure (arXiv:2412.17015v5); Fault-Propagation-Aware Benchmark (arXiv:2510.04711v2); Gremlin glossary; Causely architecture docs; Overmind blast-radius page; AWS cell-based architecture intro; Train Ticket README; awesome-AIOps dataset list; Li (Lilly) Wu publication list; arXiv:2608.07440 (confirmed *irrelevant* — it's an LLM context-management paper that happens to be called "Blast Radius").

**From search snippets only (medium confidence — verify before citing):** all Maelstrom details; Narya details; Gandalf details; LinkedIn Waterbear/LinkedOut; Steadybit and Harness specifics; Dynatrace, Datadog, New Relic, Lightstep, Komodor, Chronosphere mechanisms; MicroRAS's fuzzy-selector/attributed-graph mechanism (IEEE full text not reachable); all venue/year assignments in the §2.2 table except those with a DOI shown; AIOps Challenge 2020–2023 contents; Alibaba/Azure dataset details; GRAF.

**Explicitly unverified, flagged:**
- **E2E-REME (arXiv:2604.11094)** — PDF would not parse. Name suggests simulated remediation outcomes; **could be very close to ARC. Chase it first.**
- **Springer *Discover AI* 2026, GNN failure-propagation prediction (DOI 10.1007/s44163-026-01213-3)** — paywalled/auth-gated. Chase it second.
- **Maelstrom PDF** — binary parse failure; all detail is secondhand.
- **ChaosNative → Harness acquisition** — asserted from memory, not verified this session.
- **Whether arXiv:2607.20005 and arXiv:2609.11264 are substantive work or low-quality preprints.** Both are recent, unrefereed, single-version arXiv postings with no released artefacts that I could find. Their technical content as rendered is coherent and specific. **Verify they exist and read them yourself before building your related-work section around them — but plan as if they are real, because if they are, they are your closest competition.**

**Sources:**

[Netflix ChAP TechBlog](https://medium.com/netflix-techblog/chap-chaos-automation-platform-53e6d528371f) · [Automating chaos experiments in production (ar5iv)](https://ar5iv.labs.arxiv.org/html/1905.04648) · [Kayenta TechBlog](https://netflixtechblog.com/automated-canary-analysis-at-netflix-with-kayenta-3260bc7acc69) · [Spinnaker canary judgment](https://spinnaker.io/docs/guides/user/canary/judge/) · [Kayenta MannWhitneyClassifier](https://github.com/spinnaker/kayenta/blob/master/kayenta-judge/src/main/scala/com/netflix/kayenta/judge/classifiers/metric/MannWhitneyClassifier.scala) · [AWS Reducing Scope of Impact with Cell-Based Architecture](https://docs.aws.amazon.com/wellarchitected/latest/reducing-scope-of-impact-with-cell-based-architecture/reducing-scope-of-impact-with-cell-based-architecture.html) · [AWS FIS stop conditions](https://docs.aws.amazon.com/fis/latest/userguide/stop-conditions.html) · [AWS FIS safety lever](https://aws.amazon.com/about-aws/whats-new/2024/09/aws-fault-injection-service-additional-safety-control) · [AWS cell-based guidance samples](https://github.com/aws-solutions-library-samples/guidance-for-cell-based-architecture-on-aws) · [SREcon24 Blast Radius Reduction](https://www.usenix.org/system/files/srecon24emea_slides-tang.pdf) · [Maelstrom USENIX OSDI'18](https://www.usenix.org/conference/osdi18/presentation/veeraraghavan) · [Maelstrom PDF](https://tianyin.github.io/pub/maelstrom.pdf) · [Maelstrom morning paper](https://blog.acolyer.org/2018/10/24/maelstrom-mitigating-datacenter-level-disasters-by-draining-interdependent-traffic-safely-and-efficiently/) · [LinkedIn Waterbear](https://engineering.linkedin.com/blog/2017/11/resilience-engineering-at-linkedin-with-project-waterbear) · [LinkedOut InfoQ](https://www.infoq.com/news/2018/06/linkedout-failure-injection/) · [Narya OSDI'20](https://www.usenix.org/conference/osdi20/presentation/levy) · [Narya PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2020/10/osdi20_mitigation.pdf) · [Gandalf NSDI'20](https://www.usenix.org/conference/nsdi20/presentation/li) · [Gandalf morning paper](https://blog.acolyer.org/2020/02/28/microsoft-gandalf/) · [Gremlin glossary](https://www.gremlin.com/docs/resources-glossary) · [Gremlin scenarios](https://www.gremlin.com/docs/fault-injection-scenarios) · [Steadybit blast radius & RBAC](https://steadybit.com/blog/blast-radius-and-access-control-strategies-for-a-safer-system/) · [Harness chaos engineering](https://developer.harness.io/resilience-testing/chaos-engineering) · [Dynatrace RCA concepts](https://docs.dynatrace.com/docs/dynatrace-intelligence/root-cause-analysis/concepts) · [Dynatrace Smartscape](https://www.dynatrace.com/news/blog/new-smartscape-make-better-decisions-with-real-time-dependency-graph-of-digital-systems/) · [Datadog Watchdog RCA](https://docs.datadoghq.com/watchdog/rca/) · [Datadog Watchdog Impact Analysis](https://docs.datadoghq.com/watchdog/impact_analysis/) · [How Causely Works](https://docs.causely.ai/getting-started/how-causely-works/) · [Causely arXiv benchmark](https://arxiv.org/abs/2605.18327) · [New Relic Change Tracking](https://newrelic.com/platform/change-tracking) · [Lightstep Change Intelligence](https://lightstep.com/change-intelligence) · [Komodor rightsizing](https://komodor.com/learn/kubernetes-rightsizing-at-scale-without-breaking-reliability/) · [Chronosphere infra observability](https://chronosphere.io/solutions/infrastructure-observability/) · [Overmind vs terraform plan](https://overmind.tech/blog/difference-terraform-plan-and-overmind-blast-radius) · [IBM Blast Radius Terraform tutorial](https://www.ibm.com/think/tutorials/blast-radius-review-the-impact-of-changes-in-your-terraform-files) · [PreApply](https://github.com/akileshthuniki/PreApply) · [Datree](https://www.datree.io/) · [Kubescape CEL](https://kubescape.io/blog/2024/08/04/cel-and-kubescape/) · [Safe Remediation arXiv:2607.20005](https://arxiv.org/abs/2607.20005) · [Rebooting Microreboot arXiv:2604.09963](https://arxiv.org/html/2604.09963) · [GuardedAct arXiv:2609.11264](https://arxiv.org/abs/2609.11264) · [MicroRAS IEEE](https://ieeexplore.ieee.org/document/9302828) · [Li (Lilly) Wu publications](https://lillywu.github.io/publications/) · [CRRL arXiv:2607.03177](https://arxiv.org/abs/2607.03177) · [Counterfactual Resilience Control (Zenodo)](https://zenodo.org/records/22548162) · [R2Act arXiv:2607.04623](https://arxiv.org/html/2607.04623) · [MicroRemed arXiv:2511.01166](https://arxiv.org/abs/2511.01166) · [MicroRemed code](https://github.com/LLM4AIOps/MicroRemed) · [E2E-REME arXiv:2604.11094](https://arxiv.org/abs/2604.11094) · [STRATUS arXiv:2506.02009](https://arxiv.org/abs/2506.02009) · [Predicting Effect and Cost of Microservice System Evolution (ICSOC'23)](https://link.springer.com/chapter/10.1007/978-3-031-48421-6_8) · [Learning from Change arXiv:2604.13462](https://arxiv.org/html/2604.13462v1) · [Sage (Google Research)](https://research.google/pubs/sage-practical-scalable-ml-driven-performance-debugging-in-microservices/) · [Sage extended arXiv:2112.06263](https://arxiv.org/pdf/2112.06263) · [Groot ASE'21](https://ieeexplore.ieee.org/document/9678708) · [Groot eBay blog](https://innovation.ebayinc.com/stories/groot-ebays-event-graph-based-approach-for-root-cause-analysis/) · [DejaVu FSE'22](https://dl.acm.org/doi/10.1145/3540250.3549092) · [DejaVu code](https://github.com/NetManAIOps/DejaVu) · [CIRCA code](https://github.com/netmanaiops/circa) · [BARO FSE'24](https://dl.acm.org/doi/10.1145/3660805) · [RUN AAAI'24](https://ojs.aaai.org/index.php/AAAI/article/view/27772) · [MicroRCA NOMS'20](https://dl.acm.org/doi/abs/10.1109/NOMS47738.2020.9110353) · [CausIL WWW'23](https://dl.acm.org/doi/10.1145/3543507.3583274) · [DiagFusion TSC'23](https://nkcs.iops.ai/wp-content/uploads/2023/12/TSC23-DiagFusion.pdf) · [Failure Diagnosis survey arXiv:2407.01710](https://arxiv.org/abs/2407.01710) · [RCA survey arXiv:2408.00803](https://arxiv.org/html/2408.00803v1) · [awesome-AIOps](https://github.com/OpsPAI/awesome-AIOps) · [GNN for Microservices survey (Sensors)](https://www.mdpi.com/1424-8220/22/23/9492) · [GRAF ToN 2024](https://dl.acm.org/doi/10.1109/TNET.2024.3393427) · [GNN link prediction arXiv:2501.15019](https://arxiv.org/html/2501.15019v1) · [GNNs for Treatment Effect Prediction arXiv:2403.19289](https://arxiv.org/html/2403.19289v1) · [In-Distribution Interventions arXiv:2505.00930](https://arxiv.org/pdf/2505.00930) · [NetCause arXiv:2606.13543](https://arxiv.org/pdf/2606.13543) · [Safe offline RL via ICNN action correction arXiv:2507.22640](https://arxiv.org/html/2507.22640v1) · [VeriGuard arXiv:2510.05156](https://arxiv.org/abs/2510.05156) · [Train Ticket repo](https://github.com/FudanSELab/train-ticket) · [Train Ticket auto-query](https://github.com/FudanSELab/train-ticket-auto-query) · [TSE Fault Analysis and Debugging](https://dl.acm.org/doi/10.1109/TSE.2018.2887384) · [RCAEval arXiv:2412.17015](https://arxiv.org/html/2412.17015v5) · [RCAEval code](https://github.com/phamquiluan/RCAEval) · [Fault-propagation-aware benchmark arXiv:2510.04711](https://arxiv.org/html/2510.04711v2) · [ACM version](https://dl.acm.org/doi/10.1145/3797100) · [Alibaba clusterdata](https://github.com/alibaba/clusterdata) · [Alibaba microservices v2021](https://github.com/alibaba/clusterdata/blob/master/cluster-trace-microservices-v2021/README.md) · [CASPER call-graph reconstruction](https://github.com/docc-lab/casper) · [Azure Public Dataset](https://github.com/Azure/AzurePublicDataset) · [GAIA dataset](https://github.com/CloudWise-OpenSource/GAIA-DataSet) · [AIOps challenge datasets](http://iops.ai/dataset_list/) · [DeathStarBench ASPLOS'19](https://dl.acm.org/doi/10.1145/3297858.3304013)