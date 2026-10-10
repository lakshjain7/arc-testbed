#!/usr/bin/env python3
"""Collect the dataset: plan, run and resume many episodes on one cluster, unattended.

  run_campaign.py calibrate [--episodes 20]          no-fault no-op episodes -> thresholds (calibrate_v2.py)
  run_campaign.py plan --episodes 700 [--name main]  write the plan (fixed by its seed, before anything runs)
  run_campaign.py run  [--name main]                 run or resume the plan
  run_campaign.py status [--name main]               progress, counts, speed, time left

The cluster comes from ARC_CLUSTER / ARC_INDEX. Each cluster gets its own plan (seeded differently) and
its own data folder, so several clusters on one machine simply run different episodes of the same design.

Design (randomised complete blocks, as in the pilot, with the pilot's lessons applied):
  - a block = one fault condition x 7 episodes: every action once + noop twice (noop = 2/7 = 29%)
  - fault conditions, at SEVERAL MILD levels (the pilot's 300 ms delay, 1/4-CPU squeeze and blackhole
    saturated the system and hid the action's effect):
        none | pod-kill | network-delay 25, 75 ms | net-loss 15, 30 % | cpu-squeeze 2.5x average use
    the levels are options of `plan` (--delay --loss --squeeze); measure good ones for a machine with
    harness/dose_check.py.  add --hard for: network-delay 300 ms, cpu-squeeze 0.5x, blackhole
  - fault target: a random permutation of the 6 target services (+1 random pick) per block
  - action target: the fault's target with p = 0.5, otherwise another target ("wrong diagnosis")
  - delay from fault to action: uniform 60-300 s
  - a discarded episode is re-run once at the end of its block
  - if the cluster stops passing its health gate, the runner repairs it (ops/recover-after-restart.sh
    + warm-up) and carries on; after 3 failed repairs it stops and says so
"""
import argparse, hashlib, json, os, random, signal, subprocess, sys, time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arcenv

TARGETS = arcenv.PILOT_TARGETS
ACTIONS = ["restart-pod", "rollout-restart", "scale-up", "cpu-bump", "drain", "noop", "noop"]
# Defaults, from the laptop dose check of 2026-10-07 at 2 req/s (share of user requests that went bad):
#   delay 25 ms 31 %, 50 ms 31 %, 100 ms 73 % | loss 5 % 0 %, 15 % 12 %, 30 % 59 % | squeeze 3x 0 %, 1.5x 8-20 %, 1x 70 %
# Measure them again on every new machine (harness/dose_check.py) and override:  plan --delay .. --loss .. --squeeze ..
# CPU squeeze is a cliff, not a dial (laptop, clean baselines, 2026-10-10): 3x = 0-3 % bad, 2x = 55-100 %,
# 1.5x = 75-80 %. One level near the edge is all it supports; drop it ('--squeeze none') if no level is usable.
LEVELS = {"network-delay": [25, 75], "net-loss": [15, 30], "cpu-squeeze": [2.5]}
HARD = [("network-delay", 300), ("cpu-squeeze", 0.5), ("blackhole", None)]
PLANS = os.path.join(arcenv.DATA, "plans")
os.makedirs(PLANS, exist_ok=True)


def log(msg):
    try:
        print(f"{time.strftime('%m-%d %H:%M:%S')} {msg}", flush=True)
    except OSError:
        pass


class Stop(Exception):
    pass


def _stop(signum, frame):
    raise Stop


def plan_path(name):
    return os.path.join(PLANS, f"{name}.json")


def make_plan(name, n_episodes, seed, hard, delay_max, levels=LEVELS):
    rng = random.Random(seed)
    conds = [("none", None), ("pod-kill", None)] + [(f, l) for f in ("network-delay", "net-loss", "cpu-squeeze")
                                                    for l in levels[f]] + (HARD if hard else [])
    eps, block = [], 0
    while len(eps) < n_episodes:
        order = conds[:]
        rng.shuffle(order)
        for fault, level in order:
            if len(eps) >= n_episodes:
                break
            block += 1
            acts = ACTIONS[:]
            rng.shuffle(acts)
            ftargets = rng.sample(TARGETS, len(TARGETS)) + [rng.choice(TARGETS)]
            for i, (act, ft) in enumerate(zip(acts, ftargets), 1):
                if fault == "none":
                    at = rng.choice(TARGETS)
                elif rng.random() < 0.5:
                    at = ft
                else:
                    at = rng.choice([t for t in TARGETS if t != ft])
                eps.append({"id": f"ep_{name}_{arcenv.CLUSTER}_b{block:03d}_{i}", "block": block, "fault": fault,
                            "level": level, "fault_target": ft if fault != "none" else None, "action": act,
                            "action_target": at, "delay": round(rng.uniform(60, delay_max)),
                            "seed": rng.randrange(1 << 30)})
    return {"name": name, "cluster": arcenv.CLUSTER, "seed": seed, "created": time.time(), "hard": hard,
            "conditions": conds, "episodes": eps}


def status_of(ep_id):
    try:
        return json.load(open(os.path.join(arcenv.RAW, ep_id, "meta.json"))).get("status")
    except (OSError, ValueError):
        return None


def run_one(e, suffix=""):
    """Returns the recorded status ('ok' / 'discarded'), or None if the episode never recorded."""
    ep_id = e["id"] + suffix
    cmd = [sys.executable, arcenv.script("harness", "run_episode.py"), "--id", ep_id, "--fault", e["fault"],
           "--action", e["action"], "--target", e["action_target"], "--delay", str(e["delay"]), "--seed", str(e["seed"])]
    if e.get("fault_target"):
        cmd += ["--fault-target", e["fault_target"]]
    if e.get("level") is not None:
        cmd += ["--fault-param", str(e["level"])]
    log(f">>> {ep_id}: fault={e['fault']}({e.get('level')})@{(e.get('fault_target') or '-')[3:-8] or '-'} "
        f"action={e['action']}@{e['action_target'][3:-8]} delay={e['delay']}s")
    child = subprocess.Popen(cmd, start_new_session=True)     # own session: signals reach it only through us
    try:
        rc = child.wait()
    except (Stop, KeyboardInterrupt):
        for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(s, signal.SIG_IGN)
        log(f"stop requested: {ep_id} is removing its fault and undoing its action (up to ~2 min)")
        child.send_signal(signal.SIGINT)
        try:
            child.wait(timeout=300)
        except subprocess.TimeoutExpired:
            child.kill()
            log("the episode did not finish its cleanup in 5 min; run ops/cleanup.sh")
        log("STOPPED by request. The same command resumes from this episode.")
        sys.exit(130)
    st = status_of(ep_id)
    log(f"<<< {ep_id}: {st if st else f'NOT RECORDED (exit {rc})'}")
    return st


def repair():
    log("the cluster keeps failing its gates; repairing (ops/recover-after-restart.sh + warm-up)")
    subprocess.run(["bash", arcenv.script("loadgen", "stop-loadgen.sh")])
    subprocess.run(["bash", arcenv.script("ops", "recover-after-restart.sh")])
    subprocess.run(["bash", arcenv.script("loadgen", "warmup.sh")])
    ensure_load()


def ensure_load(rate=None):
    """Make sure this cluster's continuous load generator is running."""
    st_path = os.path.join(arcenv.LOADGEN_DIR, "status.json")
    try:
        st = json.load(open(st_path))
        if st.get("state") == "running" and time.time() - st.get("updated", 0) < 10:
            return st.get("rate_target")
    except (OSError, ValueError):
        pass
    rate = rate or float(os.environ.get("ARC_RATE", "2"))
    log(f"starting the continuous load generator at {rate} req/s and letting it settle for 5 min")
    subprocess.Popen([sys.executable, arcenv.script("loadgen", "loadgen.py"), "--rate", str(rate), "--print-every", "900"],
                     stdout=open(os.path.join(arcenv.LOGS, "loadgen-continuous.log"), "a"), stderr=subprocess.STDOUT,
                     start_new_session=True)
    time.sleep(300)
    return rate


def run_list(todo_blocks):
    fails, repairs, done = 0, 0, 0
    for blk in todo_blocks:
        redo = []
        for e in blk:
            st0 = status_of(e["id"])
            if st0 in ("ok", "discarded"):
                if st0 == "discarded" and status_of(e["id"] + "_r") is None:
                    redo.append(e)
                continue
            st = run_one(e)
            if st is None:                      # never started (health / steady gate) or export failed
                fails += 1
                if fails >= 2:
                    if repairs >= 3:
                        log("STOPPING: 3 repairs did not fix the cluster. See docs/RUNBOOK.md and ops/health.sh.")
                        return False
                    repair(); repairs += 1; fails = 0
                else:
                    time.sleep(300)
                st = run_one(e)
            if st is not None:
                fails = 0; done += 1
            if st == "discarded":
                redo.append(e)
            if done and done % 25 == 0 and os.environ.get("ARC_SYNC") == "1":
                subprocess.run(["bash", arcenv.script("run", "sync-data.sh")])
        for e in redo:
            if status_of(e["id"] + "_r") is None:
                run_one(e, suffix="_r")
    return True


def cmd_run(a):
    plan = json.load(open(plan_path(a.name)))
    ensure_load()
    blocks = {}
    for e in plan["episodes"]:
        blocks.setdefault(e["block"], []).append(e)
    ok = run_list([blocks[b] for b in sorted(blocks)])
    if os.environ.get("ARC_SYNC") == "1":
        subprocess.run(["bash", arcenv.script("run", "sync-data.sh")])
    log("CAMPAIGN DONE" if ok else "CAMPAIGN STOPPED")


def cmd_calibrate(a):
    ensure_load()
    have = [n for n in os.listdir(arcenv.RAW) if n.startswith(f"ep_cal_{arcenv.CLUSTER}_")]
    start = len(have) + 1
    eps = [{"id": f"ep_cal_{arcenv.CLUSTER}_{i:03d}", "block": 0, "fault": "none", "level": None, "fault_target": None,
            "action": "noop", "action_target": TARGETS[i % len(TARGETS)], "delay": 60, "seed": 9000 + i}
           for i in range(start, start + a.episodes)]
    run_list([eps])
    log("calibration episodes done; fitting thresholds on every no-fault no-op episode of this machine")
    r = subprocess.run([sys.executable, arcenv.script("harness", "calibrate_v2.py")])
    if r.returncode == 0:
        log("CALIBRATION DONE (re-label old episodes with: python3 harness/relabel.py)")
    else:
        log("CALIBRATION EPISODES DONE, BUT THE FIT FAILED (see the lines above; it needs about 8+ usable "
            "episodes). Run more: run/start-campaign.sh calibrate 10")


def cmd_status(a):
    try:
        plan = json.load(open(plan_path(a.name)))
    except OSError:
        sys.exit(f"no plan named '{a.name}' for cluster {arcenv.CLUSTER} (looked in {PLANS})")
    rows, times = [], []
    for e in plan["episodes"]:
        d = os.path.join(arcenv.RAW, e["id"])
        try:
            m = json.load(open(os.path.join(d, "meta.json")))
        except (OSError, ValueError):
            continue
        try:
            lab = json.load(open(os.path.join(d, "labels_v2.json")))
        except (OSError, ValueError):
            lab = {}
        rows.append((e, m, lab)); times.append(m.get("exported_at", 0))
    n, total = len(rows), len(plan["episodes"])
    print(f"plan '{a.name}' on {arcenv.CLUSTER}: {n} of {total} episodes recorded ({100*n/max(total,1):.0f}%)")
    print("  status:   ", dict(Counter(m.get("status") for _, m, _ in rows)))
    print("  discards: ", dict(Counter(m.get("discard_reason") for _, m, _ in rows if m.get("status") == "discarded")))
    print("  stalled:  ", sum(1 for _, _, l in rows if l.get("stalled")),
          "| saturated before the action:", sum(1 for _, _, l in rows if l.get("saturated_before_action")))
    print("  by fault: ", dict(Counter(f"{e['fault']}{'' if e['level'] is None else ':' + str(e['level'])}" for e, _, _ in rows)))
    print("  by action:", dict(Counter(e["action"] for e, _, _ in rows)))
    if len(times) >= 2:
        span = max(times) - min(times)
        rate = (len(times) - 1) / span * 3600 if span > 0 else 0
        left = (total - n) / rate if rate else float("inf")
        print(f"  speed: {rate:.1f} episodes/hour  ->  about {left:.0f} hours left ({left/24:.1f} days)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("calibrate"); c.add_argument("--episodes", type=int, default=20)
    pl = sub.add_parser("plan")
    pl.add_argument("--episodes", type=int, required=True); pl.add_argument("--name", default="main")
    pl.add_argument("--seed", type=int); pl.add_argument("--hard", action="store_true")
    pl.add_argument("--delay-max", type=int, default=300); pl.add_argument("--force", action="store_true")
    num = lambda v: [] if v.strip().lower() in ("", "none", "off") else [float(x) if "." in x else int(x) for x in v.split(",")]
    pl.add_argument("--delay", type=num, default=LEVELS["network-delay"], help="network-delay levels in ms, e.g. 25,75")
    pl.add_argument("--loss", type=num, default=LEVELS["net-loss"], help="net-loss levels in percent, e.g. 15,30")
    pl.add_argument("--squeeze", type=num, default=LEVELS["cpu-squeeze"],
                    help="cpu-squeeze levels: CPU limit as a multiple of the service's recent average use, e.g. 2.5; "
                         "'none' leaves a fault out of the plan (works for --delay and --loss too)")
    for nm in ("run", "status"):
        s = sub.add_parser(nm); s.add_argument("--name", default="main")
    a = p.parse_args()
    if a.cmd in ("run", "calibrate"):
        for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(s, _stop)
    if a.cmd == "plan":
        if os.path.exists(plan_path(a.name)) and not a.force:
            sys.exit(f"{plan_path(a.name)} exists. Use --force only before any of its episodes has run.")
        seed = a.seed if a.seed is not None else int(hashlib.md5(f"{a.name}/{arcenv.CLUSTER}".encode()).hexdigest()[:8], 16)
        plan = make_plan(a.name, a.episodes, seed, a.hard, a.delay_max,
                         {"network-delay": a.delay, "net-loss": a.loss, "cpu-squeeze": a.squeeze})
        json.dump(plan, open(plan_path(a.name), "w"), indent=1)
        eps = plan["episodes"]
        print(f"wrote {plan_path(a.name)}: {len(eps)} episodes in {eps[-1]['block']} blocks of 7, seed {seed}"
              + (f"  (asked for {a.episodes}; rounded up so the last block is complete)" if len(eps) != a.episodes else ""))
        print("  faults: ", dict(Counter(f"{e['fault']}{'' if e['level'] is None else ':' + str(e['level'])}" for e in eps)))
        print("  actions:", dict(Counter(e["action"] for e in eps)))
        print(f"  at ~10 min per episode: about {len(eps)*10/60:.0f} hours ({len(eps)*10/60/24:.1f} days) on this cluster")
    elif a.cmd in ("run", "calibrate"):
        try:
            cmd_run(a) if a.cmd == "run" else cmd_calibrate(a)
        except (Stop, KeyboardInterrupt):        # stopped between episodes: nothing to undo
            log("STOPPED by request. The same command resumes where it left off.")
            sys.exit(130)
    else:
        cmd_status(a)


if __name__ == "__main__":
    main()
