#!/usr/bin/env python3
"""How hard does each fault level hit on THIS machine at THIS load? Run it once before planning a campaign.

A fault that is too strong breaks everything before the action (the action's effect is then invisible:
18 of 46 pilot episodes); one that is too weak leaves nothing to remediate. We want levels where
roughly 5-60 % of user requests are bad. The right level depends on the machine and the load, so it
is measured, not assumed.

For each fault level: 60 s healthy baseline -> fault on for 90 s (the last 60 s are measured) -> fault
off -> 45 s to recover. "Bad" = failed, or slower than 2x that flow's healthy 95th percentile.
Needs the continuous load generator (run/start-campaign.sh starts one; or loadgen/loadgen.py --rate N &).

  dose_check.py                                   the default candidates below (~25 min)
  dose_check.py network-delay:50,100,200 cpu-squeeze:6,3,1.5
"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_episode as R
import arcenv

CANDIDATES = {"network-delay": [50, 100], "net-loss": [5, 15], "cpu-squeeze": [6, 3, 1.5]}
TARGET = {"network-delay": "ts-seat-service", "net-loss": "ts-travel-service", "cpu-squeeze": "ts-station-service"}
BASE_S, ON_S, MEASURE_S, REST_S = 60, 90, 60, 45


def requests_between(run_dir, t0, t1):
    rows = []
    with open(os.path.join(run_dir, "requests.jsonl")) as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if t0 <= r.get("t", 0) < t1 and r.get("err") != "client_saturated":
                rows.append(r)
    return rows


def p95(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(0.95 * len(xs)))] if xs else None


def main():
    cands = CANDIDATES
    if len(sys.argv) > 1:
        cands = {a.split(":")[0]: [float(x) if "." in x else int(x) for x in a.split(":")[1].split(",")] for a in sys.argv[1:]}
    st = R.loadgen_status()
    if not st:
        sys.exit("the load generator is not running. Start it first:  python3 loadgen/loadgen.py --rate 2 &   (wait 5 min)")
    run_dir = st["run_dir"]
    ok, why, _ = R.wait_healthy(120)
    if not ok:
        sys.exit(f"cluster not healthy: {why}")
    print(f"cluster {arcenv.CLUSTER}, load {st.get('rate_target')} req/s. Each level takes ~3.5 min.\n")
    print(f"  {'fault':14s} {'level':>6s} {'on':22s} {'requests':>8s} {'failed':>7s} {'slow':>6s} {'BAD':>6s}  {'median ms':>16s}  verdict")
    results = []
    for fault, levels in cands.items():
        target = TARGET.get(fault, "ts-station-service")
        for lvl in levels:
            t0 = time.time()
            time.sleep(BASE_S)
            base = requests_between(run_dir, t0, t0 + BASE_S)
            thr = {}
            for op in {r["op"] for r in base}:
                v = p95([r["ms"] for r in base if r["op"] == op and r["ok"]])
                thr[op] = 2 * v if v else 2000
            name = f"arc-dose-{fault}-{str(lvl).replace('.', '-')}"
            okf, info = R.apply_fault(fault, target, name, lvl)
            t_on = time.time()
            try:
                time.sleep(ON_S)
            finally:
                R.remove_fault(fault, name, target)
            rows = requests_between(run_dir, t_on + ON_S - MEASURE_S, t_on + ON_S)
            n = len(rows)
            failed = sum(not r["ok"] for r in rows)
            slow = sum(r["ok"] and r["ms"] > thr.get(r["op"], 2000) for r in rows)
            bad = 100 * (failed + slow) / n if n else float("nan")
            med = lambda rs: sorted(r["ms"] for r in rs)[len(rs) // 2] if rs else 0
            verdict = ("FAULT NOT APPLIED" if not okf else "too weak" if bad < 5 else "good" if bad <= 60
                       else "strong (use only as the 'hard' level)" if bad <= 80 else "TOO STRONG (saturates)")
            extra = f" limit {info.get('cpu_limit')}" if fault == "cpu-squeeze" else ""
            print(f"  {fault:14s} {str(lvl):>6s} {target[3:-8] + extra:22s} {n:8d} {100*failed/max(n,1):6.1f}% {100*slow/max(n,1):5.1f}% "
                  f"{bad:5.1f}%  {med(base):6.0f} -> {med(rows):6.0f}  {verdict}", flush=True)
            results.append({"fault": fault, "level": lvl, "target": target, "n": n, "failed_pct": 100 * failed / max(n, 1),
                            "slow_pct": 100 * slow / max(n, 1), "bad_pct": bad, "verified": okf, "info": info, "verdict": verdict})
            time.sleep(REST_S)
            R.wait_healthy(180)
    out = os.path.join(arcenv.DATA, "logs", f"dose-check-{time.strftime('%Y%m%d-%H%M')}.json")
    json.dump({"rate": st.get("rate_target"), "results": results}, open(out, "w"), indent=1)
    print(f"\nsaved {out}")
    print("Pick, per fault, one level marked 'good' near 10-25 % and one near 40-60 %, and plan with e.g.:")
    print("  python3 harness/run_campaign.py plan --episodes 700 --delay 50,100 --loss 5,15 --squeeze 3,1.5")


if __name__ == "__main__":
    for s in (R.signal.SIGTERM, R.signal.SIGHUP, R.signal.SIGINT):
        R.signal.signal(s, R._stop)
    try:
        main()
    except KeyboardInterrupt:
        print("stopped; the fault was removed")
