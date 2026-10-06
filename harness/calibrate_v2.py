#!/usr/bin/env python3
"""Fit the two things label v2 needs, from no-fault no-op episodes, and measure false harm honestly.

1. slo_thresholds.json: per (service, operation) latency threshold T = smallest histogram bucket
   boundary >= max(100 ms, q99 of healthy successful requests), pooled over all healthy windows of the
   TRAINING episodes. Also a per-flow threshold for what users saw (client side). Frozen afterwards:
   the definition of "too slow" must not change from episode to episode.
2. calibration_v2.json: per-service variance inflation phi (how much more the bad-ratio wobbles than
   pure binomial chance would) and one z, chosen as the smallest z for which every service's false-harm
   rate on the TRAINING episodes is <= 5%.
Then the false-harm rate is measured on HELD-OUT episodes (never on the ones used for fitting).

  calibrate_v2.py                              every no-fault no-op episode of every cluster on this machine
  calibrate_v2.py ~/arc-data/arc/raw/ep_cal_*  [--holdout 0.3]
Results go to <ARC_DATA_ROOT>/calibration/ and are shared by all clusters on the machine.
"""
import csv, gzip, hashlib, json, math, os, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import labels_v2 as L

BUCKETS = [10, 25, 50, 100, 250, 500, 750, 1000, 2000, 5000, 10000, 15000, 30000]
Z_GRID = [x / 10 for x in range(16, 61)]
TARGET_FP = 0.05


def holdout_of(ep, frac):
    return int(hashlib.md5(ep.encode()).hexdigest(), 16) % 100 < frac * 100


def usable(d):
    meta = json.load(open(os.path.join(d, "meta.json")))
    return (meta.get("fault_type") == "none" and meta.get("action_type") == "noop" and meta.get("status") == "ok"
            and os.path.exists(os.path.join(d, "op_counters.csv.gz")))


def quantile_from_buckets(counts, q):
    total = sum(counts.values())
    if total <= 0:
        return None
    run, prev = 0.0, 0.0
    for le in BUCKETS + [float("inf")]:
        c = counts.get(le, 0.0)
        if run + c >= q * total:
            return le if not math.isinf(le) else BUCKETS[-1]
        run += c
        prev = le
    return prev


def build_slo(train):
    """Pool healthy successful requests per (service, op) into non-cumulative bucket counts."""
    per = defaultdict(lambda: defaultdict(float))
    client = defaultdict(list)
    for d in train:
        incs = L.step_increments(d)
        stalls = L.stall_ranges(L.client_rows(d))
        for svc, rows in incs.items():
            cum = defaultdict(lambda: defaultdict(float))     # (t, op) -> le -> cumulative inc
            for t, op, st, le, x in rows:
                if st != "ok" or any(a <= t <= b for a, b in stalls):
                    continue
                cum[(t, op)][le] += x
            for (t, op), les in cum.items():
                prev = 0.0
                for b in BUCKETS:
                    c = les.get(str(float(b)), les.get(str(b), None))
                    if c is None:
                        continue
                    per[(svc, op)][b] += max(c - prev, 0)
                    prev = c
                inf = les.get("+Inf", prev)
                per[(svc, op)][float("inf")] += max(inf - prev, 0)
        for r in L.client_rows(d):
            if r["ok"] == "1" and not any(a <= float(r["t"]) <= b for a, b in stalls):
                client[r["op"]].append(float(r["ms"]))
    slo = defaultdict(dict)
    for (svc, op), counts in per.items():
        q99 = quantile_from_buckets(counts, 0.99)
        need = max(L.LAT_FLOOR_MS, q99 or 0)
        T = next((b for b in BUCKETS if b >= need), BUCKETS[-1])
        slo[svc][op] = {"T_ms": T, "q99_ms": q99, "n": round(sum(counts.values()))}
    slo["_client"] = {}
    for op, ms in client.items():
        ms.sort()
        q99 = ms[min(len(ms) - 1, int(0.99 * len(ms)))]
        slo["_client"][op] = {"T_ms": max(L.LAT_FLOOR_MS, round(q99)), "n": len(ms)}
    return dict(slo)


def main(args):
    frac = 0.3
    if "--holdout" in args:
        frac = float(args[args.index("--holdout") + 1])
        args = [a for a in args if a not in ("--holdout", str(frac))]
    eps = [os.path.expanduser(a) for a in args if os.path.isdir(os.path.expanduser(a))]
    if not eps:      # default: all clusters' episodes on this machine
        import glob
        eps = sorted(glob.glob(os.path.join(L.arcenv.DATA_ROOT, "*", "raw", "*")))
    eps = [d for d in eps if os.path.exists(os.path.join(d, "meta.json")) and usable(d)]
    train = [d for d in eps if not holdout_of(os.path.basename(d), frac)]
    hold = [d for d in eps if holdout_of(os.path.basename(d), frac)]
    print(f"no-fault no-op episodes: {len(eps)} usable  -> train {len(train)}, held out {len(hold)}")
    if len(train) < 5:
        sys.exit("need at least 5 training episodes")

    slo = build_slo(train)
    json.dump(slo, open(L.SLO_FILE, "w"), indent=1)
    print(f"wrote {L.SLO_FILE}: {sum(len(v) for k, v in slo.items() if k != '_client')} operations")

    # phi: mean squared z-score of block deltas under pure noise (>= 1), per service
    unit = {"z": 1.0, "phi": {}}
    zsq = defaultdict(list)
    labs = []
    for d in train:
        lab = L.label_episode(d, slo=slo, cal=unit)
        if lab["stalled"]:
            continue
        labs.append(lab)
        for svc, v in lab["services"].items():
            if v["verdict"] == "no_data":
                continue
            nB = v["N_B1L"]
            tB = L.smooth(v["X_B1L"], nB)
            for dl in v["block_deltas"]:
                if dl is None:
                    continue
                zsq[svc].append(dl)
    # recompute phi properly: E[(delta/SE)^2] needs SE per block; approximate with pooled block N
    phi = {}
    for svc in zsq:
        ratios = []
        for lab in labs:
            v = lab["services"].get(svc)
            if not v or v["verdict"] == "no_data":
                continue
            tB = L.smooth(v["X_B1L"], v["N_B1L"])
            nb = max(v["N_M"] / max(len(v["block_deltas"]), 1), 1)
            s = L.se(tB, nb, tB, v["N_B1L"])
            ratios += [(dl / s) ** 2 for dl in v["block_deltas"] if dl is not None and s > 0]
        phi[svc] = max(1.0, sum(ratios) / len(ratios)) if ratios else 1.0

    def fp_rate(dirs, z):
        per = defaultdict(lambda: [0, 0])
        for d in dirs:
            lab = L.label_episode(d, slo=slo, cal={"z": z, "phi": phi})
            if lab["stalled"]:
                continue
            for svc, v in lab["services"].items():
                if v["verdict"] == "no_data":
                    continue
                per[svc][0] += 1
                per[svc][1] += v["verdict"] == "harm"
        return per

    chosen = Z_GRID[-1]
    for z in Z_GRID:
        per = fp_rate(train, z)
        if all(h / n <= TARGET_FP for n, h in per.values() if n):
            chosen = z
            break
    cal = {"z": chosen, "phi": {k: round(v, 3) for k, v in phi.items()},
           "train": [os.path.basename(d) for d in train], "holdout": [os.path.basename(d) for d in hold],
           "delta": L.DELTA, "target_fp": TARGET_FP}
    json.dump(cal, open(L.CAL_FILE, "w"), indent=1)
    print(f"wrote {L.CAL_FILE}: z = {chosen}")

    print(f"\n  {'service':26s} {'phi':>5s} {'T (ms) per operation':40s}  {'train FP':>9s} {'HOLDOUT FP':>10s}  {'min detectable Δ':>16s}")
    tr, ho = fp_rate(train, chosen), fp_rate(hold, chosen)
    for svc in sorted(phi):
        ops = slo.get(svc, {})
        ts = ", ".join(f"{o.split('/')[-1][:14]}={v['T_ms']}" for o, v in sorted(ops.items()))[:40]
        n_t, h_t = tr.get(svc, [0, 0]); n_h, h_h = ho.get(svc, [0, 0])
        # minimum detectable effect for a typical 30 s block at this service's traffic
        typ = [l["services"][svc] for l in labs if svc in l["services"] and l["services"][svc]["verdict"] != "no_data"]
        if typ:
            nb = sum(v["N_M"] for v in typ) / len(typ) / 6
            nB = sum(v["N_B1L"] for v in typ) / len(typ)
            p0 = sum(L.smooth(v["X_B1L"], v["N_B1L"]) for v in typ) / len(typ)
            mde = L.DELTA + chosen * math.sqrt(phi[svc]) * L.se(p0, max(nb, 1), p0, max(nB, 1))
        else:
            mde = None
        print(f"  {svc:26s} {phi[svc]:5.2f} {ts:40s}  {h_t:3d}/{n_t:<4d} {h_h:4d}/{n_h:<4d}     "
              f"{'-' if mde is None else f'{100*mde:5.1f} pts'}")
    th = sum(h for n, h in ho.values()); tn = sum(n for n, h in ho.values())
    print(f"\nheld-out false harm: {th}/{tn} service-verdicts"
          + (f" = {100*th/tn:.1f}%  (~{th/max(len(hold),1):.2f} per episode)" if tn else " (no held-out episodes yet)"))


if __name__ == "__main__":
    main(sys.argv[1:])
