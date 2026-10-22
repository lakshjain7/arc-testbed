#!/usr/bin/env python3
"""Per-service time series of each episode, for the dynamic (time-step) model of ARC.

  trajectories.py RAW_DIR [RAW_DIR ...] --out TRAJ.jsonl [--plans main,main2] [--step 15]

For every usable episode, on a grid of STEP-second steps from the start of B0 to the end of M:
  bad[i][k]     share of service i's requests that were bad in step k (label definition: failed or slower
                than the calibrated per-operation threshold; same counts as labels_v2.py)
  n[i][k]       number of requests of service i in step k (weight: quiet services are noisy)
  err[i][k]     error share in step k (services.csv.gz)
  p95r[i][k]    p95 latency in step k / the service's median p95 in B0 (1.0 = normal)
  rpsr[i][k]    request rate in step k / its B0 mean (traffic)
  thr[i][k]     share of CPU periods throttled
  ready[i][k]   1 if the pod was ready during the whole step
plus k_fault (step the fault started), k_action (step of the action), the action and its target,
the fault (analysis only, never a model input), the call graph (edges seen before the action),
and the split by block as in build_dataset.py.
The thresholds come from $ARC_CALIB (the calibration that labelled these episodes).
"""
import csv, gzip, json, math, os, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import labels_v2 as L


def f(v):
    try:
        x = float(v)
        return None if math.isnan(x) else x
    except (TypeError, ValueError):
        return None


def episode(d, step):
    meta = json.load(open(os.path.join(d, "meta.json")))
    lab = json.load(open(os.path.join(d, "labels_v2.json")))
    slo = L.load_json(L.SLO_FILE, {})
    w = meta["windows"]
    t0, t_end, t_act = w["B0"][0], w["M"][1], w["B1"][1]
    K = int((t_end - t0) // step)
    k_of = lambda t: int((t - t0) // step)
    incs = L.step_increments(d)
    services = sorted(set(incs) | set(lab["services"]))
    bad = {s: [0.0] * K for s in services}; n = {s: [0.0] * K for s in services}
    for s in services:
        for t, (N, X) in L.per_step_counts(incs.get(s, []), s, slo).items():
            k = k_of(t)
            if 0 <= k < K:
                n[s][k] += N; bad[s][k] += X
    for s in services:
        bad[s] = [round(bad[s][k] / n[s][k], 4) if n[s][k] > 0 else None for k in range(K)]
    acc = defaultdict(lambda: defaultdict(list))
    for r in csv.DictReader(gzip.open(os.path.join(d, "services.csv.gz"), "rt")):
        k = k_of(float(r["t"]))
        if 0 <= k < K:
            acc[r["service"]][k].append(r)
    b0 = lambda k: (k + 1) * step <= w["B0"][1] - t0
    out = {}
    for name, fn in (("err", lambda rs: (sum(f(x["err_rps"]) or 0 for x in rs) / max(sum(f(x["rps"]) or 0 for x in rs), 1e-9))
                                   if sum(f(x["rps"]) or 0 for x in rs) > 0 else 0.0),
                     ("p95", lambda rs: _mean([f(x["p95_ms"]) for x in rs])),
                     ("rps", lambda rs: _mean([f(x["rps"]) for x in rs])),
                     ("thr", lambda rs: _mean([f(x["throttled"]) for x in rs]) or 0.0),
                     ("ready", lambda rs: 1.0 if all(f(x["ready"]) != 0 for x in rs) else 0.0)):
        out[name] = {s: [fn(acc[s][k]) if acc[s][k] else None for k in range(K)] for s in services}
    for name in ("p95", "rps"):          # relative to the service's own healthy B0 level
        for s in services:
            base = _median([v for k, v in enumerate(out[name][s]) if b0(k) and v])
            out[name + "r"] = out.get(name + "r", {})
            out[name + "r"][s] = [round(v / base, 3) if (v is not None and base) else None for v in out[name][s]]
    edges = set()
    for r in csv.DictReader(gzip.open(os.path.join(d, "edges.csv.gz"), "rt")):
        if float(r["t"]) <= t_act and r["client"] and r["server"] and (f(r["rps"]) or 0) > 0:
            edges.add((r["client"], r["server"]))
    return meta, lab, {"services": services, "step_s": step, "K": K,
                       "k_fault": k_of(meta.get("fault_applied_at") or t_act), "k_action": k_of(t_act),
                       "bad": bad, "n": n, "err": out["err"], "p95r": out["p95r"], "rpsr": out["rpsr"],
                       "thr": out["thr"], "ready": out["ready"], "edges": sorted(edges)}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def main(args):
    out = args[args.index("--out") + 1] if "--out" in args else "trajectories.jsonl"
    plans = set(args[args.index("--plans") + 1].split(",")) if "--plans" in args else None
    step = int(args[args.index("--step") + 1]) if "--step" in args else 15
    roots = [a for a in args if os.path.isdir(a)]
    n_ok = skipped = 0
    with open(out, "w") as fo:
        for root in roots:
            for name in sorted(os.listdir(root)):
                parts = name.split("_")
                plan = parts[1] if len(parts) > 2 else ""
                if plans and plan not in plans:
                    continue
                d = os.path.join(root, name)
                try:
                    meta, lab, tr = episode(d, step)
                except Exception:
                    skipped += 1; continue
                if meta.get("status") != "ok" or lab.get("stalled"):
                    skipped += 1; continue
                blk = next((int(p[1:]) for p in parts if p.startswith("b") and p[1:].isdigit()), 0)
                tr.update(episode_id=name, plan=plan, block=blk, split="test" if blk and blk % 5 == 0 else "train",
                          action={"type": meta.get("action_type"), "target": meta.get("action_target")},
                          fault={"type": meta.get("fault_type"), "target": meta.get("fault_target")})
                fo.write(json.dumps(tr) + "\n"); n_ok += 1
    print(f"wrote {n_ok} episode trajectories to {out} ({skipped} skipped), {step} s steps")


if __name__ == "__main__":
    main(sys.argv[1:])
