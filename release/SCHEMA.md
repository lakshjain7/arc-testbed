# Schema of the ARC dataset v1.0

All tables are gzip-compressed CSV with a header row. Empty cell = not applicable or not measured. "Points" = percentage points
of bad-request share (a rise from 2% to 5% is 3 points). A request is bad if it failed or was slower than a latency bar.

## episodes.csv.gz (one row per episode)

| Column | Meaning |
|---|---|
| episode_id | `ep_<plan>_<cluster>_b<block>_<position>`; a trailing `_r` is a repeat of a discarded episode |
| part | batch1, wide1, wide1db, wide2, reptest, held |
| kind | `campaign` (benchmark data), `calibration` (healthy no-op episodes for the latency bars), `other` |
| plan, block, position | the plan it belongs to; a block is 7 episodes of one fault condition (one per action, no-op twice) |
| status, discard_reason, usable | `usable` = 1 for episodes in the benchmark |
| fault, fault_level, fault_target | fault type; its level (network delay: ms, packet loss: percent, CPU squeeze: limit as multiple of recent use, load surge: multiple of the load, call-cut: callee); target service |
| action, action_target | one of noop, restart-pod, rollout-restart, scale-up, cpu-bump, drain; target service |
| action_on_fault_target | 1 if the action targets the faulty service |
| delay_s | seconds from fault to action (60 to 300) |
| load_rate_req_s, load_mix | offered load and the user-flow mix (`core` 4 flows, `wide` 9 flows) |
| recorded | when the episode was recorded (lab clock) |
| healthy_after | 1 if every service was ready again after the episode |
| saturated_before_action | 1 if users were at least 80% bad in the 60 s before the action |
| stalled | 1 if more than a quarter of the after-action window was cut out as a machine stall |
| user_damage_pts (+ _abs500, _abs1000) | rise of the bad-request share summed over the user flows, at the calibrated, 500 ms and 1 s bars |
| collateral_harmed, collateral_mean_sum_pts, collateral_peak_sum_pts | services other than the action target that were harmed; sums of their `y_mean` / `y_peak` |

## service_labels.csv.gz (one row per episode and service)

| Column | Meaning |
|---|---|
| episode_id, part, kind, service | `part` and `kind` as in `episodes.csv.gz` (benchmark rows are `kind` = campaign); service names keep Train Ticket's `ts-` prefix |
| is_action_target, is_fault_target | 1 if this service is the target |
| verdict | `harm`, `no_harm`, `inconclusive` (too few requests or a change within noise), `no_data` |
| n_before, bad_before, p_before | requests, bad requests and bad share in the 60 s before the action (B1L) |
| n_after, bad_after, p_after | the same for the 180 s after the action, starting 5 s later (M) |
| y_mean | `p_after - p_before`, in points of share (the main label) |
| y_mean_se | its standard error |
| y_peak | worst 30 s block of M minus `p_before` (smoothed: half a request added to each count) |
| y_excess | extra bad requests in M compared with the baseline share |
| t_recover_s, recovered_by_end | seconds until the share is back to its baseline; whether it recovered before M ended |
| y_mean_500, y_peak_500, y_mean_1000, y_peak_1000 | the same labels at fixed 500 ms and 1 s bars |
| block_deltas | JSON list: rise of each of the six 30 s blocks of M (null if a block had no requests) |

Rows with fewer than 30 requests before or after are not scored in the paper (`arc_data.scored`). Filter `kind == 'campaign'` first: the 28,769 scored rows are campaign rows only.

## client_flows.csv.gz (one row per episode and user flow)

flow (search, search2, orders, orders2, book, book2, pay, cancel, collect), n_before, n_after, p_before, p_after, y_mean, bar_ms (the
flow's calibrated bar), y_mean_500, y_mean_1000: what users of that flow saw.

## splits.csv.gz (campaign episodes only)

One column per protocol; the value is `train`, `test`, `repeat` or empty (not used in that protocol).

| Column | Protocol |
|---|---|
| in_system | every 5th block (`block % 5 == 0`) of each plan is test; blocks never straddle |
| unseen_system | train on batch1 (20 services), test on wide1 (25 services, 5 new) |
| unseen_fault | train on wide1, test on wide1db (database delay never seen) |
| held_out_faults | train on everything except held, test on held (call-cut and load surge never seen) |
| higher_load | train on the 4 req/s parts, test on wide2 (8 req/s) |
| noise_ceiling | reptest: the same incident repeated 5 times; use it to measure the floor on any error |
| wide2_first_half | 1 for wide2 blocks 1 to 24 (before the cancel-flow drift) |

## Raw files (inside `arc-raw-<part>-v1.0.tar.gz`, folder `<part>/raw/<episode_id>/`)

| File | Content |
|---|---|
| services.csv.gz | per 5 s and service: rps, err_rps, p50/p95/p99 ms, cpu_cores, mem_mb, throttled, restarts, ready; `window` = B0 (healthy baseline), B1 (the 30 s before the action), M |
| edges.csv.gz | per 5 s and caller to callee: rps, failed_rps |
| counters.csv.gz | exact cumulative request, error and latency-bucket counters per service |
| op_counters.csv.gz | the same per operation and status, plus callers' failed calls per edge |
| client.csv.gz | every request the load generator sent: time, flow, HTTP code, milliseconds, success, error type |
| events.json | Kubernetes events during the episode |
| labels_v2.json | all labels of the episode, with the parameters used |
| meta.json | what was injected, applied and verified; timings; health before and after |
| calibration/ | latency bars (`slo_thresholds.json`), calibration summary |
| plans/ | the pre-registered episode plan (when recorded with one) |
