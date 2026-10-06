# ARC — Measurement Specification

What every episode records, when, and why. Freeze this before collecting data.
Changing it later means regenerating episodes at 8 minutes each.

---

## The three snapshots

| | When | Duration | Shape | What it is |
|---|---|---|---|---|
| **B0** | before fault injection | 120 s | scalar aggregate | healthy baseline |
| **B1** | last 30 s of fault soak, immediately pre-action | 30 s | **time series** | **the model's input — the incident state** |
| **M** | action + 5 s grace, then 120 s | 120 s | **time series** | post-action, source of the label |

### Why B1 and M must be time series, not averages

The harm definition you're adopting is *"SLO regression >10% for more than 30 s."* **You cannot evaluate "for more than 30 seconds" from a single averaged number.** A restart produces a sharp spike then recovery; averaged over 120 s it looks mild, and you would systematically under-label exactly the damage you exist to predict.

Store M as **15 s buckets × 8**, per service, per channel. Derive from it:
- `peak_deviation` — worst bucket
- `seconds_above_threshold` — how long it stayed >10% degraded
- `mean_deviation` — for regression targets
- `recovered_by_end` — bool

B1 as time series matters for a different reason: it tells you whether the incident was **still worsening** at the moment of action. "Error rate 4% and flat" and "error rate 4% and doubling every 20 s" are different states that demand different actions. A scalar throws that away.

B0 can stay a scalar. It is context, not signal.

**Implication for Prometheus:** default 15 s scrape gives 8 points across M — workable but coarse. Set a **5 s scrape interval for the train-ticket namespace only** (24 points) and leave everything else at 15 s. Do this before collecting, not after.

---

## Per-service measurements (node features)

Collected for every service at B0, B1, M.

### RED — the SLO channels
| Field | Source | Notes |
|---|---|---|
| `request_rate` | trace-derived per-service calls/sec | |
| `error_rate` | failed / total | **SLO channel 1** |
| `latency_p50` / `p95` / `p99` | histogram | **SLO channel 2 — use p95** |

⚠️ **Define SLO as error rate AND latency, never latency alone.** A load-shedding action returns 429s, which cuts latency to near zero. Measure latency only and load-shedding looks free — you would train a model that recommends shedding as harmless.

### Resource
| Field | Source |
|---|---|
| `cpu_usage` | `rate(container_cpu_usage_seconds_total[1m])` per pod |
| `memory_working_set` | `container_memory_working_set_bytes` |
| `restart_count` | `increase(kube_pod_container_status_restarts_total[window])` — **kube-state-metrics only** |
| `oom_killed` | `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}` |

### Saturation (proxies — say so in the write-up)
Stock Train Ticket has no Actuator and no Micrometer, so HikariCP pool gauges do not exist. If SkyWalking is present:

| Field | Why it is a proxy |
|---|---|
| `jvm_threads_blocked` | lock contention |
| `jvm_threads_timed_waiting` | **threads park here on `getConnection()` when the pool exhausts** |
| `jvm_threads_live` | pins at `maxThreads` when Tomcat saturates |
| `jvm_heap_ratio` | heap used / max |
| `jvm_gc_time` | GC pressure |

If the chart ships Jaeger instead of SkyWalking, these are unavailable and saturation must come from CPU + latency alone. **Record which source was used per episode.**

### Lifecycle state
`replica_count`, `ready_replicas`, `is_alive`, `seconds_since_last_deploy`

**`is_alive` is not optional.** When a fault kills a pod the service vanishes from the topology. Keep the node with zeroed features and `is_alive=false` rather than dropping it — constant node count, clean per-node labels, and the disappearance is itself signal.

---

## Per-edge measurements

For every caller→callee pair, at B0, B1, M:

| Field | SkyWalking | OpenTelemetry |
|---|---|---|
| `call_rate` | `service_relation_client_cpm` | `rate(traces_service_graph_request_total)` |
| `error_ratio` | `1 − service_relation_client_call_sla/100` | `..._request_failed_total / ..._request_total` |
| `resp_time` | `service_relation_client_resp_time` | `traces_service_graph_request_client` histogram |

**`call_rate` is the single most important edge feature.** Two services one hop from the same neighbour look identical structurally; one breaks and one doesn't purely because one edge carries 380 calls/sec and the other carries less than one. Without it the graph earns nothing over a flat feature vector.

---

## Derived topology features

Computed from the B1 graph with networkx, not measured:

`in_degree`, `out_degree`, `weighted_in_degree` (by call rate), `betweenness`, `hops_from_fault_target`, `hops_from_action_target`, `is_fault_target`, `is_action_target`, `reachable_from_action_target`

`hops_from_action_target` and static reachability together **are your baseline model.** Compute them from day one so the baseline is free.

---

## Per-episode metadata

```
episode_id, started_at, ended_at
status                  ok | discarded | failed
discard_reason

fault_type, fault_target, fault_params
chaos_cr_uid            # what Chaos Mesh ACTUALLY ran
fault_started_at, fault_ended_at
fault_verified          # bool — canary confirmed injection took effect

action_type, action_target, action_params
action_delay_seconds    # RANDOMISED 60-300s; see below
action_applied_at
action_applied          # bool — post-conditions verified
degenerate_expected     # metadata column, NEVER a filter

workload_spec           # scenario mix, concurrency, rps
ambient_noise_spec      # the SREGym-style background disturbances

telemetry_source        # skywalking | jaeger+otel
chart_version, image_digests
generator_version, delta_slo_spec_version
seed_fault, seed_action
```

**`action_delay_seconds` must be randomised, not fixed.** A restart at t=30 s and at t=300 s have very different consequences. Hold it fixed and you have silently conditioned on it; randomise it uniformly and it becomes an identifiable covariate you can control for.

**`delta_slo_spec_version`** exists because the ΔSLO formula is the least battle-tested thing here — you are writing it before seeing a single real measurement. When it changes, bump the version and recompute every row. Never leave a dataset where some labels came from v1 and some from v2.

---

## The label

Per service `s`, computed from **M relative to B1** — never relative to B0.

```
delta_error_rate(s) = mean_error_M(s) − mean_error_B1(s)
delta_p95_ratio(s)  = p95_M(s) / max(p95_B1(s), FLOOR_MS)      # clipped at 10x
harm(s)             = seconds_above_10pct_regression(s) > 30    # binary
```

**Why B1 and not B0:** `M − B0` conflates the damage the *fault* did with the damage the *action* did. You would be predicting the incident, not the action.

**What B1 still leaves in:** the fault's own continued evolution. Some faults worsen on their own, and the action gets blamed for it.

**That is what no-op episodes are for.** They are not a trivial baseline — they are the **counterfactual arm**:

```
causal effect of action a = ΔSLO(a) − E[ΔSLO(noop) | same fault, same state]
```

That expectation is estimated **across episodes**, not within one. It is the reason no-op gets ~20% of samples rather than 12.5%, and the reason action assignment has to be random — without random assignment that expectation is not identified.

**Also record efficacy separately from damage:**
```
fault_resolved   # did the original symptom clear
```
Hypothesis H4 is that damage and efficacy are separable. If they turn out perfectly correlated, "predict damage" collapses into "predict success" and the framing needs rethinking. You can only find that out if you measure both.

### Label v1: what 10 no-op episodes taught us (2026-09-29)

Implemented in `harness/compute_labels.py` (v1) and `harness/calibrate_noise.py`. The v0 formula above (average of per-5 s p95, "10% worse for 30 s") flagged **2–6 of ~17 services as harmed in episodes where nothing was done**. Three reasons:

1. **Quiet services see a handful of requests per 5 s step** at the 2 req/s episode load (payment ≈ 0.2 req/s), so a per-step p95 is essentially "the slowest request". **v1 pools every request in the window** from raw bucket counters (`counters.csv.gz`, exporter v2) and computes one p95 per window.
2. **A 50 ms floor applied only to the baseline** made fast services (~10 ms) look 80% faster. v1 applies the floor to both sides.
3. **"10% worse" is inside normal variation for quiet services.** v1 fits **per-service thresholds** on no-fault no-op episodes: `median + 3·MAD` of the noise, never below +25% latency or +2 pts errors. Measured noise thresholds (worst 30 s block of M vs B1, p95 ratio): busy services (seat, order, config, station, route, train, price) **1.25**, basic 1.40, travel 1.71, preserve 2.06, gateway 2.67, contacts 2.95, order-other 3.45, security 4.18, inside-payment 4.49, payment 5.63.

Result: 0–2 false harms per no-op episode (mean ≈ 0.9 of 17, ≈ 5% per service), measured on the same episodes the thresholds were fitted on, so the out-of-sample rate will be somewhat higher. Every no-op episode collected later refines the thresholds, and the no-op arm estimates the false-positive rate directly. **Consequence to state in the paper:** at 2 req/s on a laptop, quiet services only register large damage (≥ ~4×); busy services register ≥ 25%.

Other v1 rules:
- `harm = lat_peak > thr_lat OR err_peak > thr_err`, where `lat_peak` / `err_peak` use the **worst 30 s block of M** (so a short restart spike isn't averaged away over 120 s). The whole-M ratio is also stored.
- A service with fewer than 5 requests in B1 or M gets `status = insufficient`: no verdict, and it isn't counted as harmless.
- **System-wide stalls** are flagged from the load generator's side: a 15 s slice with ≥ 2 timeouts or a median > 1 s. 1 of 10 no-op episodes had one: a ~20 s freeze of every service with no Kubernetes event behind it. It inflated 9 services' numbers. Stalled episodes are excluded from calibration and carry `stall_in_B1` / `stall_in_M` flags, so they can be discarded or analysed separately. **The stall rate (~10% of episodes) is itself a health metric for the laptop.**
- **Continuous background load** is required. Episodes run against a load generator that is never stopped. Starting load per episode left the JVMs still speeding up during the episode, and every service looked 25–80% faster in M than in B1.
- Known limitation: gateway latency depends on the request mix (bookings ~700 ms, searches ~150 ms), so a window with more bookings looks slower. Per-operation latency (span name) is the planned fix.

---

## Episode outcome: never judge by HTTP status alone

Added 2026-09-28, after a booking that returned `504` from the UI still completed in the backend. The order was in the database, and a retry created a second one. A gateway can time out *after* the backend has committed. So "the client saw an error" and "the business operation failed" are different facts. Record them separately:

| Signal | Source | Why |
|---|---|---|
| `client_outcome` | load generator: HTTP status + latency | what a user experiences |
| `service_outcome` | per-service error rate / latency from traces | where the damage actually is |
| `business_outcome` | database state, e.g. did the order row get written, exactly once | ground truth for "did it work" |
| `trace_complete` | did the trace reach every expected span | a request dropped mid-chain looks different from a slow one |
| `fault_verified` | Chaos Mesh CR status + injection canary | the fault really happened |
| `recovery_seconds` | time until per-service SLOs return within 10% of B0 | how long the damage lasted |

Duplicates count as damage too. A retry after a gateway timeout that creates a second order is a business-level failure even though every HTTP call eventually returned 200.

---

## Cleanliness gates

An episode is only a data point if all of these pass. Otherwise `status=discarded`.

| Gate | When | Guards against |
|---|---|---|
| **Health gate** | episode start | Episode N+1 inheriting N's damage. Compare against a stored healthy probe; redeploy the namespace on failure. |
| **Injection canary** | after fault apply | Chaos Mesh silently no-op'ing — wrong containerd socket, or daemon lost the socket inode mid-run. Kill a scratch pod, assert it died. |
| **Warm-up** | after any pod (re)start, before B0 | **Measured 2026-09-28:** the same search took 60+ s, then 30 s, then 0.9 s on freshly started services. Send warm-up traffic through every endpoint the workload uses until latency is stable, or B0 measures cold start instead of health. This applies after the *action* too: a restart action's damage includes its cold start, but B0 must not. |
| **Steady-state check** | before B0 | JVMs still warming, pools still filling. Assert request-rate variance below threshold. |
| **Action post-condition** | after action apply | `rollout undo` hit a missing revision; `scale` left pods Pending. Set `action_applied`. |
| **Teardown confirm** | episode end | Chaos CR finalizer wedged. Poll until gone, force with `cleanFinalizer=forced` on timeout. |

**Track the discard rate as a first-class metric.** 10–20% early is normal. A rising rate means the cluster is degrading — it is your earliest warning that a multi-day run is going bad, and far more informative than any single episode.

---

## What is deliberately NOT collected

**Application logs.** ΔSLO comes from error rates and latency, which come from traces and metrics. Logs contribute nothing to the label. They matter only much later, when the Investigator agent needs evidence to cite. Adding Loki now spends a day on something the harness does not use.
