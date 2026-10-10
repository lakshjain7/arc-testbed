# Batch 2: the wider system

Batch 1 is 20 services, 4 user flows, 5 fault types, 6 actions. Batch 2 widens all three, and is the
"system the model has not seen" for the transfer test (train on batch 1, test on batch 2).

It is built on the laptop one piece at a time (the laptop cannot hold 30 services at once) and run on
the lab machine after batch 1. Nothing here changes batch 1: the default load mix (`core`) and the
default plan are untouched.

**Rule for every piece:** it goes into a plan only after it has been proven on a live cluster. A user
flow must run under load with ~0 failures and show up in the service graph. A fault or action must
pass a smoke test that shows it does what it claims and can be undone.

## User flows (each brings more services into play)

| # | Flow (load-generator ops) | Extra services | Status |
|---|---|---|---|
| 1 | Other train types: `search2`, `book2`, `orders2` (K / Z / T trains) | ts-travel2-service, ts-preserve-other-service | **Done, 2026-10-11.** 7 min at 2 req/s with a database reset in the middle: 869 requests, 0 failed; 13 new graph edges (55 in total) |
| 2 | Insurance: book with `assurance=1` | ts-assurance-service | to do |
| 3 | Food: list food for a trip, book with food | ts-food-service, ts-train-food-service, ts-station-food-service | to do |
| 4 | Consign luggage with a booking | ts-consign-service, ts-consign-price-service | to do |
| 5 | Cancel an order (refund) | ts-cancel-service | to do |
| 6 | Collect ticket / enter station (paid orders) | ts-execute-service | to do |
| 7 | Travel plan search (cheapest / quickest) | ts-travel-plan-service, ts-route-plan-service | to do; heavy fan-out, decide after measuring |

All seven would give 32 services (about +5.5 GB on top of the 20-service cluster).

How to switch a flow on (cluster already up):

```bash
bash ops/add-services.sh flow1          # loads images, adds telemetry + CPU limit, starts them one by one
bash loadgen/warmup.sh
ARC_MIX=wide bash run/start-campaign.sh calibrate     # new mix => new calibration
```

`ops/reset-data.sh` already cleans the second order table (`orders_other`) that flow 1 fills.

## Faults (to do; on/off and proportional ones first, since they do not depend on machine speed)

| Fault | Idea | Smoke test must show |
|---|---|---|
| hung pod | process alive, answers nothing (Chaos Mesh pod-failure, pause image) | callers time out; pod not restarted by itself; clean recovery on removal |
| database partition | cut one service off from MySQL only | that service's DB calls fail, others fine; heals on removal |
| HTTP abort | a share of requests to one service is dropped | only if it really fires with our keep-alive connections (it did not for NetworkPolicy) |
| CPU throttle by target | lower the limit until a target share of periods is throttled, instead of a multiple of use | throttled share lands near the target on a busy and a quiet service |
| delay as a multiple | delay = k x the target's healthy latency | recorded ms, similar "bad" share on laptop and lab |

## Actions (to do)

| Action | Idea | Smoke test must show |
|---|---|---|
| rollback | `rollout undo` to a seeded previous revision (a harmless one and a harmful one) | the pod template really changed; reset returns to the current revision |
| scale down | 2 copies -> 1 (needs services that normally run 2) | callers forget the removed copy; no stuck requests |
| restart caller | restart an upstream caller of the faulty service instead of the service | recorded which caller; same checks as restart-pod |

## Targets

Batch 1 uses 6 target services. Batch 2 adds the new services of each finished flow as fault and
action targets (travel2 and preserve-other first).

## Open design points

- Load: find the lab machine's real ceiling (`step-test.sh "6 8 12 16"`), run at two thirds, recalibrate.
- CPU limits: 2 cores per service leaves them using under 1 % on the lab machine. Right-sizing needs
  its own test first (500m made JVM start-up slow and broke restart actions on the laptop).
