# 05 — How to formulate ARC's damage label (ΔSLO v2)

*Research pass 2026-09-29. Inputs: `harness/MEASUREMENT-SPEC.md` (incl. "Label v1"), `harness/compute_labels.py`, `harness/calibrate_noise.py`, `research/00`, `research/01`, plus web sources below.*

Tags: **[V]** = VERIFIED, seen in the source during this pass (a fetched page, or a search-result snippet quoting it, marked "snippet"). **[B]** = BELIEVED, from general statistical knowledge or my own reasoning/arithmetic. Not checked against a source.

---

## TL;DR

Change the label from "latency ratio OR error delta" to **one per-request "bad" judgement**: a request is bad if it errored **or** was slower than a fixed per-(service, operation) healthy threshold. This is the Google SRE good-events/valid-events SLI and Apdex's rule that errors count as frustrated. With that one change, a fast failure and a slow success count the same, which fixes the fail-fast problem.

From the bad-request counts:
- **Magnitude:** signed change in bad-ratio, B1 → M.
- **Harm:** a three-way verdict (harm / no-harm / inconclusive) from a test that allows for extra variance. Its false-positive rate is set on no-fault no-op episodes (A-A tests).
- **Causal effect:** estimated only against the no-op arm, never per episode.

---

## (a) Survey — how each source defines degradation / harm

| Source | Definition of "bad" / harm | Statistic & threshold | Low traffic | Tag |
|---|---|---|---|---|
| **Google SRE Workbook, *Implementing SLOs*** — https://sre.google/workbook/implementing-slos/ | SLI = good events / total events. Latency SLI = "proportion of requests that were faster than some threshold", e.g. 90% < 450 ms, 99% < 900 ms | ratio vs target | notes individual customers "can fail to meet their SLO for uninteresting reasons" at low volume | [V] |
| **SRE Workbook, example SLO document** — https://sre.google/workbook/slo-document/ | Availability: "Any HTTP status other than 500–599 is considered successful" (4xx = good). Latency: "proportion of sufficiently fast requests", < 400 ms / < 850 ms | ratio vs target | — | [V] |
| **SRE Book ch. 6, four golden signals** — https://sre.google/sre-book/monitoring-distributed-systems/ | "distinguish between the latency of successful requests and the latency of failed requests… a slow error is even worse than a fast error". Use histogram buckets, not means | — | — | [V] |
| **SRE Workbook, *Alerting on SLOs*** — https://sre.google/workbook/alerting-on-slos/ | Burn rate = speed of error-budget use relative to the SLO. Page at 14.4× over 1 h confirmed by a 5 min window (2% of budget), 6× over 6 h/30 min (5%). Ticket at 1× over 3 d/6 h (10%) | multi-window, multi-burn-rate; the short window confirms the budget "is still being consumed" | synthetic traffic, **combine low-traffic services**, client retries, lower the SLO | [V] |
| **Apdex** — https://docs.newrelic.com/docs/apm/new-relic-apm/apdex/apdex-measure-user-satisfaction/ , spec https://www.apdex.org/wp-content/uploads/2020/09/Apdex_Technical_Specification.pdf | satisfied ≤ T, tolerating ≤ 4T, frustrated > 4T **or server error** "regardless of its return speed" | (S + Tol/2)/N | — | [V] snippet |
| **Netflix Kayenta / Spinnaker ACA judge** — https://spinnaker.io/docs/guides/user/canary/judge/ , [MannWhitneyClassifier.scala](https://github.com/spinnaker/kayenta/blob/master/kayenta-judge/src/main/scala/com/netflix/kayenta/judge/classifiers/metric/MannWhitneyClassifier.scala) | A metric is High/Low if the Mann-Whitney **98% CI lies entirely outside a tolerance band ±0.25 × Hodges-Lehmann estimate**, plus an effect-size gate (mean ratio or CLES) and a direction. Score = % metrics Pass. Tukey-fence outlier removal (factor 3.0) | MW-U, CI vs tolerance band. Classifier code default `confLevel = 0.95`; the docs say 98% | empty series → `Nodata`, excluded from the score. Canary fails if ≥ 50% of metrics are Nodata. No minimum n in the classifier | [V] |
| **Google + Waze canary best practice** — https://cloud.google.com/blog/products/devops-sre/canary-analysis-lessons-learned-and-best-practices-from-google-and-waze | Compare the canary to a **same-size, same-time baseline, not to production**. Calibrate with **A-A tests** (must pass) and a known-bad version (must fail) | Kayenta | "at least 50 pieces of time-series data per metric", so plan analyses "several hours long" | [V] |
| **Netflix sequential canary testing** (Lindon et al., KDD'22) — https://arxiv.org/abs/2205.14762 | Regression = the new version is stochastically worse at **any quantile**. Anytime-valid sequential tests of stochastic order; count data handled in companion work | sequential, always-valid | built for fast detection | [V] abstract |
| **Argo Rollouts analysis** — https://argo-rollouts.readthedocs.io/en/stable/features/analysis/ | user success/failureCondition per measurement. `failureLimit` default 0. If neither condition holds → **Inconclusive**, which pauses for a human | threshold per interval | empty result must be handled explicitly (`len(result)==0 \|\| …`, `isNaN`) | [V] |
| **Flagger** — https://github.com/fluxcd/flagger/blob/main/docs/gitbook/usage/metrics.md , https://docs.flagger.app/usage/how-it-works | built-in `request-success-rate` (non-5xx) min 99%, `request-duration` P99 max 500 ms, per 1 min interval. Roll back when the count of failed checks reaches `threshold` | fixed thresholds + failed-check counter | not specified | [V] (snippet for `threshold`) |
| **Amazon, hands-off deployments** — https://aws.amazon.com/builders-library/automating-safe-hands-off-deployments/ | Roll back if the aggregate high-severity alarm fires during bake time | alarms | bake time requires a **minimum number of data points**, e.g. "at least 100 requests to the Create API" | [V] snippet |
| **Microsoft Gandalf** (NSDI'20) — https://blog.acolyer.org/2020/02/28/microsoft-gandalf/ | Holt-Winters anomaly baseline (30 d history) → temporal voting (faults after rollout vote for it, faults before veto it) + spatial scope (clusters/nodes hit) → **Gaussian discriminant classifier** trained on team feedback | 92.4% precision / 100% recall (data plane) | — | [V] secondary |
| **Rebooting Microreboot** arXiv:2604.09963 — https://arxiv.org/html/2604.09963 | harm = "SLO regression of more than 10% for more than 30 seconds". Baseline = "mean SLO metrics over the 60 seconds before" the action. 5 s grace. SLOs P99 < 100 ms, errors < 0.1%. Fault-window errors excluded | continuous 30 s breach, no statistical test | not addressed | [V] |
| **Safe Remediation** arXiv:2607.20005 — https://arxiv.org/html/2607.20005v1 | per-service binary: "health-metric deviation (latency, error-rate, or saturation) within 60 s of action". Outcome labels resolved / partial / false-remediation | **no threshold or baseline window stated** (not reproducible) | not addressed | [V] |
| **SREGym** arXiv:2605.07161 / **AIOpsLab** arXiv:2501.06706 | "problem-specific" mitigation oracle: fault resolved + system healthy, from **client request success rate** + cluster state | no numeric thresholds published | — | [V] |
| **RCAEval** arXiv:2412.17015; Nezha (FSE'23) | label = root-cause service at injection time. RCAEval perturbs detection time by t_inject ± 40 s. No impact magnitude | — | — | [V] snippet (RCAEval); [B] Nezha |
| **Metastable failures** (Huang et al. OSDI'22 https://www.usenix.org/system/files/osdi22-huang-lexiang.pdf ; Bronson HotOS'21) | bad state that **persists after the trigger is removed**, measured by collapsed **goodput** | — | — | [V] snippet |
| **Resilience triangle** (Bruneau et al. 2003) — https://www.sciencedirect.com/science/article/pii/S0951832021004427 | loss = ∫ (100 − Q(t)) dt: depth × duration of the dip | area | — | [V] snippet |
| **OpenTelemetry HTTP semconv** — https://opentelemetry.io/docs/specs/semconv/http/http-spans/ | server span: 4xx leaves status Unset, 5xx → Error. Client span: 4xx → Error | — | — | [V] snippet |
| **Brown, Cai & DasGupta 2001** — https://projecteuclid.org/journals/statistical-science/volume-16/issue-2/Interval-Estimation-for-a-Binomial-Proportion/10.1214/ss/1009213286.full | Wald intervals behave erratically. Use **Wilson or Jeffreys for small n** | — | — | [V] snippet |
| **CausalImpact** (Brodersen et al. 2015) — https://arxiv.org/abs/1506.00356 | effect = observed − counterfactual predicted from **control series**. Generalises difference-in-differences | Bayesian structural TS | — | [V] snippet |

**What the survey says for ARC:**
1. Practice judges requests as good or bad (errors + slow). It does not compare a p95 ratio. [V]
2. Serious canary systems use a CI/test against a tolerance band, allow "no data / inconclusive" as a third outcome, and are calibrated with A-A runs. [V]
3. The two closest papers use a fixed "% for N seconds" rule (Rebooting Microreboot) or an unspecified deviation (2607.20005). Neither runs a statistical test or handles low traffic, so there is room to improve here. [V]

---

## (b) RECOMMENDED label specification v2 (`delta_slo_spec_version = 2`)

### b.0 Notation
- `s` = service, `o` = operation (span name), `k` = 5 s step.
- Windows:
  - **B0** = 120 s healthy.
  - **B1L** = *label baseline* = **last 60 s before the action**. The model input stays the 30 s B1.
  - **G** = 5 s grace.
  - **M** = 120 s after G, split into 4 non-overlapping 30 s blocks `b = 1..4`.
- Per step you already have `calls`, `errors`, and cumulative bucket counts `c_le`.

### b.1 The "bad request" (fixes fail-fast)
```
bad(request) = error  OR  latency > T[s,o]
```
- **Error.** The span status is Error (5xx or exception). A request that never reached `s` also counts: a caller's failed call to `s` (edge `failed`) with no matching server span. Use `n_s = max(server_calls_s, Σ inbound edge calls)` and `err_s = max(server_errors_s, Σ inbound edge failed)`. **[B]** Without this, a killed service drops out of its own data and shows up as "insufficient" exactly when it is worst. Check this against `is_alive=false` episodes.
- **Latency threshold T[s,o]** = the smallest histogram bucket boundary that is ≥ max(**100 ms**, q99 of the *pooled healthy* latency of (s,o)).
  - "Pooled healthy" means all B0 windows plus all no-fault no-op episodes. Freeze T in `thresholds_v2.json`.
  - T must be a bucket boundary so the slow count is **exact** (`n − c_le[T]`), with no interpolation.
  - The q99 rule means healthy traffic is ≤ ~1% "slow" by construction.
  - The 100 ms floor stops sub-100 ms jitter on fast services (10→25 ms) from counting as damage. **[B]**
  - Payment at 0.2 req/s × 120 s × ~100 episodes ≈ 2,400 pooled requests, enough for a stable q99. **[B]**
- **Per-operation is required for the gateway** and any mixed service. With one per-service T, the mix's q99 sits above the booking tail (~700 ms+), so searches slowing from 150 → 600 ms are never counted. **[B]** Needs span-name as a histogram dimension (spanmetrics `dimensions: [span.name]`). Until it lands, fall back to per-service T and flag `per_op=false`.
- Also store `slow4` = count with latency > the bucket ≥ 4·T (Apdex "frustrated" tier) for a severity sensitivity check. **[V]** for the 4T idea, **[B]** for its use here.

Bad counts per window W: `N_W = Σ n`, `X_W = Σ (err + slow − err∧slow)`. Traces put errors in buckets too, so use `slow_nonerr` if available. Otherwise `X ≈ min(N, err + slow)` and document the approximation. **[B]**

### b.2 Magnitude targets (regression), per service
Jeffreys-smoothed rate: `p̃_W = (X_W + 0.5) / (N_W + 1)`. Raw rate: `p̂_W = X_W / N_W`.

| Target | Formula | Role |
|---|---|---|
| **`y_mean`** (primary) | `p̂_M − p̂_B1L` | signed, in [−1, 1]. Least noisy. Main regression head |
| `y_peak` | `max_b (p̃_b − p̃_B1L)` | worst 30 s. Upward-biased under noise (max of 4), so a secondary target only **[B]** |
| `y_excess` (area) | `X_{G∪M} − p̂_B1L · N_{G∪M}` | extra bad requests caused, **including the grace window**. The error-budget / resilience-triangle area in request units **[B]** |
| `t_recover` | first 5 s step t in M after which every 30 s sliding window has `p̃ ≤ p_ref + δ` (p_ref = pooled healthy bad rate). **Right-censored at 120 s** | duration. Compute only if `n_s ≥ 1 req/s`; otherwise NA |
| `recovered_by_end` | last block's upper bound `< p_ref + δ` | metastability flag ("persists after trigger removed") |
| diagnostics (not targets) | `Δerr`, `Δslow`, `Δrate = N_M/120 − N_B1L/60`, `y_cles` | keep the fail-fast split visible. A traffic drop is evidence of damage upstream |

`y_cles` (optional, threshold-free robustness check): treat each request as an ordinal category (its bucket index, with errors = worst category). Then compute `P(M request worse than B1L request) − 0.5` from bucket counts, as a Mann-Whitney / CLES with ties. Kayenta supports CLES as an effect size. **[V]** for Kayenta, **[B]** for this construction. It needs no T, but it is sensitive to meaningless small shifts, so use it only as a check.

**Regression weights:** `w = 1 / (φ_s · SE²_mean)`, clipped to [0.1, 10] × the median weight. Quiet services then contribute in proportion to how much they tell you. **[B]**

### b.3 Harm verdict (binary, with a third "inconclusive" state)
For each block b:
```
Δ_b  = p̃_b − p̃_B1L
SE_b = sqrt( p̃_b(1−p̃_b)/N_b + p̃_B1L(1−p̃_B1L)/N_B1L )
LB_b = Δ_b − z* · sqrt(φ_s) · SE_b          # lower bound
UB_b = Δ_b + z* · sqrt(φ_s) · SE_b          # upper bound
harm(s)         = max_b LB_b > δ                 # some 30 s block is surely ≥ δ worse
no_harm(s)      = max_b UB_b < δ                 # every block is surely < δ worse
inconclusive(s) = otherwise
```
This is Kayenta's rule ("CI entirely outside a tolerance band") **[V]**, applied to a proportion with a Jeffreys-smoothed Wald/Wilson-type SE **[B]**. The third state matches Argo's Inconclusive / Kayenta's Nodata **[V]**. It replaces the hard `MIN_N = 5`: with little data the interval is wide, so the verdict becomes inconclusive on its own.

Parameters (defaults):

| Param | Default | Why |
|---|---|---|
| δ (minimum harm) | **0.05** (5 points of requests turned bad) | a user-relevant floor, same for every service. The noise is handled by φ and z*, not by per-service δ **[B]** |
| z* | start at 1.645 (one-sided 95%), then **calibrate**: the smallest z* giving per-service FPR ≤ 5% on *held-out* no-fault no-op episodes, with the max over 4 blocks included | A-A calibration per Google/Waze **[V]**. Accounts for the max-over-blocks look-elsewhere effect **[B]** |
| φ_s (overdispersion) | `max(1, mean over noise eps of Δ_mean² / SE²_mean)`. Pool within traffic tier (busy / medium / quiet) until ≥ 20 noise episodes per service | requests are bursty and autocorrelated (stalls, GC), so binomial SE is too small. This is the quasi-binomial fix **[B]** |
| B1L | 60 s (sensitivity: 30 s) | doubles quiet-service counts. Rebooting Microreboot uses 60 s **[V]**. Any bias is shared with the no-op arm and cancels in the causal contrast **[B]** |
| block | 30 s, 4 non-overlapping | matches the "> 30 s" duration notion **[V]**, keeps the multiplicity at 4 |
| grace | 5 s (Rebooting Microreboot **[V]**) excluded from the verdict, **included in `y_excess`** | the restart's RST errors land in the grace window **[B]** |

Illustrative power, φ = 1, δ = 0.05, z* = 1.645 **[B, own arithmetic]**:
- **Busy (6 req/s, 1% base):** block n = 180, B1L n = 360. Harm needs Δ ≳ 0.09.
- **Quiet (payment 0.2 req/s):** block n = 6, B1L n = 12. 3 of 6 bad → harm. 2 of 6 bad → inconclusive.

So the minimum detectable effect is ~9 pts on busy services and ~45 pts on payment. **Publish that table** (see c).

**Multiplicity across ~17 services:** control **per-service FPR** (it is the label-noise rate the model sees). Report the expected false harms per episode = Σ_s FPR_s (≈ 0.85 at 5%). Use Holm/BH only when making a *claim* such as "action a harmed ≥ 1 service in this episode". **[B]**

### b.4 Stalls (laptop hiccups)
- Detect from the client as now (a 15 s slice with ≥ 2 timeouts or median > 1 s).
- **Mask** stalled slices ± 5 s from B1L, G and M for both X and N before computing any of the above.
- If > 25% of M or > 50% of B1L is masked → `label_status = "stalled"`: keep the episode in the release, exclude it from training and calibration.
- **Before trusting masking, test stall incidence by action arm** (χ² over actions). If restarts/rollbacks cause stalls (a cold JVM burning laptop CPU), the stall *is* action damage in this environment. Masking would then erase it: report masked and unmasked for those arms. **[B]**

### b.5 End-to-end (client) label — catches Train Ticket business failures
For each flow f ∈ {search, order-list, book, pay} from `client.csv`:
- `bad = HTTP ≥ 500 OR timeout OR business status ≠ success OR latency > T_f`, with T_f from healthy client data (same q99-to-bucket rule; client latencies are exact, so no bucket snap).
- Same `y_mean`, `y_excess`, and harm verdict.
- Also **duplicate orders** (a 504 followed by a commit, then a retry) count as bad **[B, from the spec's own finding]**.

This is the only place the `200 {"status":0}` failures show up. Server spans leave these Unset/OK by OTel convention **[V]**. It is also the SRE-recommended place to measure: close to the user **[V: SLO doc uses load-balancer metrics]**.

### b.6 Granularity
| Level | Use | Why |
|---|---|---|
| **per service** | primary target: `y_mean`, harm verdict | node-level GNN output. Operations are merged into a service by summing their bad counts, so mix shift no longer biases latency |
| per (service, op) | threshold T only, not a separate target | too few requests per op for quiet services **[B]** |
| per edge | auxiliary target: `Δ(failed/calls)` per edge, with the same test | cheap extra supervision for message passing. Noisy **[B]** |
| per client flow | headline "user impact" and business failures | b.5 |

### b.6a Recovery and efficacy
- `fault_resolved`: the fault target's last block `UB < p_ref + δ`, i.e. judged against **B0/healthy, not B1**.
- Keep it separate from damage (hypothesis H4 in the spec).

### b.7 Using the no-op arm (the causal part)
1. **Calibration (no-fault, no-op = A-A):** freeze T[s,o], p_ref, φ_s, z*. Hold out ≥ 30% of these episodes to report the out-of-sample FPR. **[V: A-A practice; B: split]**
2. **Cell-level effect (for the paper):**
   - `τ(a, fault, s) = mean(y_mean | a, fault) − mean(y_mean | noop, fault)`, with a **bootstrap over episodes** (95% CI).
   - `attributable_harm(a, fault, s) = P(harm | a, fault) − P(harm | noop, fault)`.
   - Add B1 severity (`p̂_B1L`) and action delay as covariates (regression adjustment / ANCOVA) to cut variance. Random assignment keeps this unbiased. **[B]**
3. **Per-episode residual label (optional training target):** fit `g(x, s) ≈ E[y_mean | noop, x]` on fault+no-op episodes. The training target is `r = y_mean − ĝ(x, s)` for action episodes. This is the X-learner / CausalImpact idea: the no-op model plays the role of the control series. **[V for CausalImpact concept; B for application]**
   - Only valid out-of-fold (cross-fit g).
   - "Observed harm" is a per-episode fact. "Attributable harm" exists only in expectation. Never name a per-episode label "causal".
4. **Do not** use "services unreachable from the action target" as within-episode controls. That builds the static-reachability baseline into the label, and it is the baseline ARC must beat. **[B]**

### b.8 Output schema per service (`labels_v2.json`)
```
status: ok | stalled | no_traffic
N_B1L, X_B1L, N_b[4], X_b[4], N_G, X_G, N_M, X_M, err_*, slow_*, slow4_*
y_mean, y_peak, y_excess, t_recover(+censored), recovered_by_end, y_cles
verdict: harm | no_harm | inconclusive, max_LB, max_UB
T_used, per_op, phi_s, z_star, delta
```
Store the raw counts, not just derived values. Then any v3 re-labelling is a recompute, never a re-run. **[B]**

---

## (c) What to report in the paper, and pitfalls

**Report:**
1. The exact formulas above, with `delta_slo_spec_version`, T table, φ table, z*, δ.
2. **Held-out A-A false-harm rate:** per service and per episode (expected false harms per episode).
3. **Minimum detectable effect per service** at the 2 req/s load. This turns "quiet services only register large damage" into a table instead of a caveat.
4. Fraction `inconclusive` per service and per action. The model is scored only on decided labels; say how many were dropped.
5. **Known-bad positive controls:**
   - restart of a busy service → harm at that service and its callers;
   - pod-kill + no-op → harm/recovery curve at the killed service.
   The Google/Waze "known bad version" check **[V]**.
6. Sensitivity: T ∈ {q99, 2×q99}, B1L ∈ {30, 60 s}, peak vs mean vs area. Show that conclusions (action ranking) are stable, e.g. Kendall τ of action damage across definitions.
7. v1 vs v2 agreement on the same episodes, and the fail-fast example (seat kill) under both.
8. Causal effects from b.7 with CIs. The observed-vs-attributable harm distinction, stated once, clearly.
9. Stall rate overall and by action arm.

**Pitfalls:**
- **Fail fast looks fast.** Fixed by b.1. Mention it; it is a real finding that v1-style separate channels mislead. **[V: SRE book warns of exactly this]**
- **Ceiling at B1.** If B1L is already ~100% bad, `y_mean ≤ 0` by arithmetic. Report the B1 severity distribution and condition effects on it. Do not read "no harm" as "safe" for dead services. **[B]**
- **Invisible business failures.** Per-service errors undercount Train Ticket failures. State it; the client label (b.5) is the check. **[V: OTel semconv; spec]**
- **Dead services vanish from their own spans.** Use caller-side counts (b.1) and verify on pod-kill episodes. **[B]**
- **Traffic shielding.** When upstream fails, downstream services receive fewer requests and look *healthier*. Report `Δrate`. Goodput is the metastable-failure literature's measure **[V]**.
- **Overdispersion** (bursts, GC, stalls) makes binomial tests over-confident. φ_s and A-A calibration fix it. With only 10 noise episodes, φ and z* are rough: keep collecting no-fault no-ops. **[B]**
- **Selection on the worst block** biases `y_peak` upward and inflates FPR. z* is calibrated with the max included; `y_mean` is the primary target. **[B]**
- **In-sample thresholds** (v1 fitted and evaluated on the same 10 episodes) understate FPR. Always report held-out. **[B; the spec already notes this]**
- **Grace window hides restart RSTs.** Keep G in `y_excess`. **[B]**
- **Stalls correlated with action** (b.4). **[B]**
- **Coarse buckets** (1–2 s, 2–5 s, 5–10 s) make T jump, e.g. 1,000 → 2,000 ms. Snap T to buckets and publish them. Latency changes inside a bucket are invisible. **[B]**
- **Mix shift** without per-op thresholds biases gateway latency. Fix before collecting at scale. **[spec, B]**
- **Retries** count as separate requests at the callee. A retry storm raises N and X together, so check `Δrate` alongside `y_mean`. **[B]**
- **Never mix label versions.** Recompute all episodes when anything above changes. **[spec]**

---

## Sources
[Implementing SLOs](https://sre.google/workbook/implementing-slos/) · [Example SLO document](https://sre.google/workbook/slo-document/) · [Monitoring distributed systems](https://sre.google/sre-book/monitoring-distributed-systems/) · [Alerting on SLOs](https://sre.google/workbook/alerting-on-slos/) · [Apdex (New Relic)](https://docs.newrelic.com/docs/apm/new-relic-apm/apdex/apdex-measure-user-satisfaction/) · [Apdex spec](https://www.apdex.org/wp-content/uploads/2020/09/Apdex_Technical_Specification.pdf) · [Spinnaker canary judge](https://spinnaker.io/docs/guides/user/canary/judge/) · [Kayenta MannWhitneyClassifier](https://github.com/spinnaker/kayenta/blob/master/kayenta-judge/src/main/scala/com/netflix/kayenta/judge/classifiers/metric/MannWhitneyClassifier.scala) · [Google/Waze canary lessons](https://cloud.google.com/blog/products/devops-sre/canary-analysis-lessons-learned-and-best-practices-from-google-and-waze) · [Lindon et al. KDD'22](https://arxiv.org/abs/2205.14762) · [Argo Rollouts analysis](https://argo-rollouts.readthedocs.io/en/stable/features/analysis/) · [Flagger metrics](https://github.com/fluxcd/flagger/blob/main/docs/gitbook/usage/metrics.md) · [Flagger how it works](https://docs.flagger.app/usage/how-it-works) · [Amazon hands-off deployments](https://aws.amazon.com/builders-library/automating-safe-hands-off-deployments/) · [Gandalf (morning paper)](https://blog.acolyer.org/2020/02/28/microsoft-gandalf/) · [Rebooting Microreboot](https://arxiv.org/html/2604.09963) · [Safe Remediation 2607.20005](https://arxiv.org/html/2607.20005v1) · [SREGym](https://arxiv.org/pdf/2605.07161) · [AIOpsLab](https://arxiv.org/pdf/2501.06706) · [RCAEval](https://arxiv.org/pdf/2412.17015) · [Metastable Failures in the Wild](https://www.usenix.org/system/files/osdi22-huang-lexiang.pdf) · [Resilience curves review](https://www.sciencedirect.com/science/article/pii/S0951832021004427) · [OTel HTTP spans](https://opentelemetry.io/docs/specs/semconv/http/http-spans/) · [Brown, Cai, DasGupta 2001](https://projecteuclid.org/journals/statistical-science/volume-16/issue-2/Interval-Estimation-for-a-Binomial-Proportion/10.1214/ss/1009213286.full) · [CausalImpact](https://arxiv.org/abs/1506.00356)
