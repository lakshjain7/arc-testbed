#!/usr/bin/env python3
"""How hard does each fault level hit on THIS machine at THIS load? Run it once before planning a campaign.

A fault that is too strong breaks everything before the action (the action's effect is then invisible:
18 of 46 pilot episodes); one that is too weak leaves nothing to remediate. We want levels where
roughly 10-60 % of user requests are bad. The right level depends on the machine and the load, so it
is measured, not assumed.

For each fault level: 60 s healthy baseline -> fault on for 90 s (the last 60 s are measured) -> fault
off -> rest. Two definitions of a "bad" request are reported:
  LABEL   failed, or slower than the calibrated threshold of that user flow (the definition the labels
          use: max(100 ms, healthy q99), from calibration/slo_thresholds.json). Decide with this one.
          Shown as "-" before calibration has run.
  2xP95   failed, or slower than twice that flow's 95th percentile in the 60 s just before. A rough
          stand-in for use before calibration exists.
Both bars follow the machine's own healthy speed, so on a fast machine (35 ms requests) a 150 ms answer
already counts as bad although no user would notice. That is intended for the labels (damage relative
to normal), but keep it in mind when reading the percentages.
Needs the continuous load generator (python3 loadgen/loadgen.py --rate N &, wait 5 min).

  dose_check.py                                             the default candidates below (~35 min)
  dose_check.py network-delay:2,5,10 net-loss:8,15          chosen levels, default targets
  dose_check.py cpu-squeeze@ts-order-service:2,1.5,1        a chosen target (fault@service:levels)
"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_episode as R
import labels_v2 as L
import arcenv

TARGET = {"network-delay": "ts-seat-service", "net-loss": "ts-travel-service", "cpu-squeeze": "ts-station-service"}
# the squeeze is sized from each service's own CPU use, so test a quiet and a busy target
CANDIDATES = [("network-delay", TARGET["network-delay"], [25, 75]), ("net-loss", TARGET["net-loss"], [15, 30]),
              ("cpu-squeeze", "ts-station-service", [1.5, 1]), ("cpu-squeeze", "ts-order-service", [1.5, 1])]
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


def restarts(target):
    p = R.pod_of(target)
    cs = ((p or {}).get("status", {}).get("containerStatuses") or [{}])[0]
    return (p or {}).get("metadata", {}).get("uid"), cs.get("restartCount", 0)


def parse(args):
    out = []
    for a in args:
        head, levels = a.split(":")
        fault, _, target = head.partition("@")
        out.append((fault, target or TARGET.get(fault, "ts-station-service"),
                    [float(x) if "." in x else int(x) for x in levels.split(",")]))
    return out


def main():
    cands = parse(sys.argv[1:]) if len(sys.argv) > 1 else CANDIDATES
    st = R.loadgen_status()
    if not st:
        sys.exit("the load generator is not running. Start it first:  python3 loadgen/loadgen.py --rate 2 &   (wait 5 min)")
    run_dir = st["run_dir"]
    ok, why, _ = R.wait_healthy(120)
    if not ok:
        sys.exit(f"cluster not healthy: {why}")
    label_T = {op: v["T_ms"] for op, v in L.load_json(L.SLO_FILE, {}).get("_client", {}).items()}
    print(f"cluster {arcenv.CLUSTER}, load {st.get('rate_target')} req/s. Each level takes 3.5-5 min.")
    print("label thresholds per flow (ms): " + (", ".join(f"{k} {v}" for k, v in sorted(label_T.items())) or
                                                "none yet (calibrate first); deciding with 2xP95") + "\n", flush=True)
    print(f"  {'fault':14s} {'level':>6s} {'on':24s} {'requests':>8s} {'failed':>7s} {'LABEL bad':>10s} {'2xP95 bad':>10s}  "
          f"{'median ms':>16s}  verdict", flush=True)
    results = []
    for fault, target, levels in cands:
        for lvl in levels:
            t0 = time.time()
            time.sleep(BASE_S)
            base = requests_between(run_dir, t0, t0 + BASE_S)
            thr = {}
            for op in {r["op"] for r in base}:
                v = p95([r["ms"] for r in base if r["op"] == op and r["ok"]])
                thr[op] = 2 * v if v else 2000
            uid0, rc0 = restarts(target)
            name = f"arc-dose-{fault}-{str(lvl).replace('.', '-')}"
            okf, info = R.apply_fault(fault, target, name, lvl)
            t_on = time.time()
            try:
                time.sleep(ON_S)
            finally:
                uid1, rc1 = restarts(target)
                R.remove_fault(fault, name, target)
            rows = requests_between(run_dir, t_on + ON_S - MEASURE_S, t_on + ON_S)
            n = len(rows)
            pct = lambda k: 100 * k / n if n else float("nan")
            failed = sum(not r["ok"] for r in rows)
            rel = pct(failed + sum(r["ok"] and r["ms"] > thr.get(r["op"], 2000) for r in rows))
            lab = pct(failed + sum(r["ok"] and r["ms"] > label_T.get(r["op"], L.FALLBACK_T_MS) for r in rows)) if label_T else None
            bad = lab if lab is not None else rel
            med = lambda rs: sorted(r["ms"] for r in rs)[len(rs) // 2] if rs else 0
            crashed = uid1 != uid0 or rc1 != rc0
            verdict = ("FAULT NOT APPLIED" if not okf else
                       "CONTAINER RESTARTED (the fault became a crash; too strong)" if crashed and fault != "pod-kill" else
                       "too weak" if bad < 5 else "good" if bad <= 60 else
                       "strong (use only as the 'hard' level)" if bad <= 80 else "TOO STRONG (saturates)")
            extra = f" limit {info.get('cpu_limit')}" if fault == "cpu-squeeze" else ""
            print(f"  {fault:14s} {str(lvl):>6s} {target[3:-8] + extra:24s} {n:8d} {pct(failed):6.1f}% "
                  f"{'-' if lab is None else f'{lab:.1f}%':>10s} {rel:9.1f}%  {med(base):6.0f} -> {med(rows):6.0f}  {verdict}", flush=True)
            results.append({"fault": fault, "level": lvl, "target": target, "n": n, "failed_pct": pct(failed),
                            "bad_label_pct": lab, "bad_2xp95_pct": rel, "verified": okf, "info": info,
                            "container_restarted": crashed, "verdict": verdict})
            # the squeeze is sized from the CPU used in the last 2 min: let a previous squeeze leave that window
            time.sleep(130 if fault == "cpu-squeeze" else REST_S)
            R.wait_healthy(180)
    out = os.path.join(arcenv.DATA, "logs", f"dose-check-{time.strftime('%Y%m%d-%H%M')}.json")
    json.dump({"rate": st.get("rate_target"), "label_thresholds_ms": label_T, "results": results}, open(out, "w"), indent=1)
    print(f"\nsaved {out}")
    print("Pick, per fault, one level near 10-25 % bad and one near 40-60 %, and give them to the plan:")
    print("  python3 harness/run_campaign.py plan --episodes 700 --delay A,B --loss C,D --squeeze E,F")


if __name__ == "__main__":
    for s in (R.signal.SIGTERM, R.signal.SIGHUP, R.signal.SIGINT):
        R.signal.signal(s, R._stop)
    try:
        main()
    except KeyboardInterrupt:
        print("stopped; the fault was removed")
