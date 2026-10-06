#!/usr/bin/env python3
"""KEPT FOR THE RECORD ONLY: this is the script that ran the 50-episode laptop pilot (docs/research/07).
It uses the laptop paths (~/arc). For new data use harness/run_campaign.py.

The H1 pilot: 50 episodes in a randomised complete-block design (research/06 §4.1), run in order,
resumable. Needs the continuous load generator running.

  7 blocks x 7 episodes + 1 spare no-fault noop = 50
  block faults, in order: none, pod-kill, network-delay, cpu-squeeze, net-loss, blackhole, none
      (none first and last: measures overnight drift)
  in each block: all 6 actions once + noop a second time, random order (noop = 14/50 = 28%)
  fault target: random permutation of the 6 pilot targets, plus 1 random pick
  action target: the fault's target with p = 0.5, otherwise one of the other 5 (a "wrong diagnosis");
      with no fault, uniform over all 6
  delay: uniform 60-300 s
  a discarded episode is re-run once, at the end of its block, with the same assignment

The plan is fixed by the seed and written to data/pilot_plan.json BEFORE anything runs, so the
assignment can't be influenced by results.

  run_pilot.py plan [--seed 2026]     write the plan and print it
  run_pilot.py run                    run (or resume) the plan
"""
import json, os, random, subprocess, sys, time

ARC = os.path.expanduser("~/arc")
PLAN = os.path.join(ARC, "data", "pilot_plan.json")
TARGETS = ["ts-seat-service", "ts-order-service", "ts-travel-service", "ts-basic-service",
           "ts-preserve-service", "ts-station-service"]
BLOCK_FAULTS = ["none", "pod-kill", "network-delay", "cpu-squeeze", "net-loss", "blackhole", "none"]
ACTIONS = ["restart-pod", "rollout-restart", "scale-up", "cpu-bump", "drain", "noop", "noop"]


def make_plan(seed):
    rng = random.Random(seed)
    eps = []
    for b, fault in enumerate(BLOCK_FAULTS, 1):
        acts = ACTIONS[:]
        rng.shuffle(acts)
        ftargets = rng.sample(TARGETS, 6) + [rng.choice(TARGETS)]
        for i, (act, ft) in enumerate(zip(acts, ftargets), 1):
            if fault == "none":
                at = rng.choice(TARGETS)
            elif rng.random() < 0.5:
                at = ft
            else:
                at = rng.choice([t for t in TARGETS if t != ft])
            eps.append({"id": f"ep_pilot_b{b}_{i}", "block": b, "fault": fault,
                        "fault_target": ft if fault != "none" else None, "action": act,
                        "action_target": at, "delay": round(rng.uniform(60, 300)), "seed": rng.randrange(1 << 30)})
    eps.append({"id": "ep_pilot_b8_1", "block": 8, "fault": "none", "fault_target": None, "action": "noop",
                "action_target": rng.choice(TARGETS), "delay": round(rng.uniform(60, 300)), "seed": rng.randrange(1 << 30)})
    return {"seed": seed, "created": time.time(), "episodes": eps}


def status(ep_id):
    try:
        return json.load(open(os.path.join(ARC, "data", "raw", ep_id, "meta.json"))).get("status")
    except (OSError, ValueError):
        return None


def run_one(e, suffix=""):
    ep_id = e["id"] + suffix
    cmd = [sys.executable, os.path.join(ARC, "harness", "run_episode.py"), "--id", ep_id,
           "--fault", e["fault"], "--action", e["action"], "--target", e["action_target"],
           "--delay", str(e["delay"]), "--seed", str(e["seed"])]
    if e["fault_target"]:
        cmd += ["--fault-target", e["fault_target"]]
    print(f"\n{time.strftime('%H:%M:%S')} >>> {ep_id}: block {e['block']} fault={e['fault']}@{e['fault_target']} "
          f"action={e['action']}@{e['action_target']} delay={e['delay']}s", flush=True)
    r = subprocess.run(cmd)
    st = status(ep_id)
    if r.returncode not in (0,) and st is None:
        # aborted before recording (unhealthy start or never steady): give the system time, then retry once
        print(f"{time.strftime('%H:%M:%S')}     {ep_id} did not record (exit {r.returncode}); waiting 5 min", flush=True)
        time.sleep(300)
        return None
    print(f"{time.strftime('%H:%M:%S')} <<< {ep_id}: {st}", flush=True)
    return st


def run():
    plan = json.load(open(PLAN))
    by_block = {}
    for e in plan["episodes"]:
        by_block.setdefault(e["block"], []).append(e)
    for b in sorted(by_block):
        redo = []
        for e in by_block[b]:
            if status(e["id"]) in ("ok", "discarded"):
                print(f"skip {e['id']} (already {status(e['id'])})")
                if status(e["id"]) == "discarded" and status(e["id"] + "_r") is None:
                    redo.append(e)
                continue
            st = run_one(e)
            if st is None:
                st = run_one(e)          # one retry for "never started"
            if st == "discarded":
                redo.append(e)
        for e in redo:                   # a discarded episode is re-run once, at the end of its block
            if status(e["id"] + "_r") is None:
                run_one(e, suffix="_r")
    print("PILOT DONE", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("plan", "run"):
        sys.exit(__doc__)
    if sys.argv[1] == "plan":
        seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 2026
        if os.path.exists(PLAN) and "--force" not in sys.argv:
            sys.exit(f"{PLAN} already exists (use --force to replace it before any episode has run)")
        p = make_plan(seed)
        json.dump(p, open(PLAN, "w"), indent=1)
        for e in p["episodes"]:
            same = "same" if e["action_target"] == e["fault_target"] else "other"
            print(f"  {e['id']:16s} {e['fault']:14s} {str(e['fault_target'])[3:-8]:9s} {e['action']:16s} "
                  f"{e['action_target'][3:-8]:9s} ({same:5s}) delay {e['delay']:3d}s")
        from collections import Counter
        print("actions:", dict(Counter(e["action"] for e in p["episodes"])))
        print(f"wrote {PLAN}")
    else:
        run()
