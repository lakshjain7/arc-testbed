#!/usr/bin/env python3
"""Label-sensitivity sweep, step 1: recompute every episode's per-service damage under a range of FIXED latency bars.

  label_sweep.py DATASET.jsonl RAW_DIR --out SWEEP.jsonl [--bars 50,100,250,500,1000]

A request is bad if it failed or took longer than the bar; the same windows, blocks and smoothing as labels_v2.py
(it calls the same code with ABS_T_MS replaced). The bars must be latency-histogram bucket boundaries
(10 25 50 100 250 500 750 1000 ... ms). Nothing is written into the episodes.
One line per episode of DATASET: {episode_id, bars: {T: {service: {y_mean, y_peak, p_B1L, n_B1L, N_M}}}}.
Step 2 (label_sweep_build.py) turns this into one dataset per bar for the unchanged evaluation scripts.
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import labels_v2 as L


def main(args):
    ds, raw = args[0], args[1]
    out = args[args.index("--out") + 1]
    bars = [int(x) for x in args[args.index("--bars") + 1].split(",")] if "--bars" in args else [50, 100, 250, 500, 1000]
    L.ABS_T_MS = bars
    ids = [json.loads(l)["episode_id"] for l in open(ds)]
    n = 0
    with open(out, "w") as fo:
        for ep in ids:
            d = os.path.join(raw, ep)
            try:
                lab = L.label_episode(d, write=False)
            except Exception as e:
                print(f"  {ep}: skipped ({e})")
                continue
            rec = {"episode_id": ep, "bars": {str(T): {} for T in bars}}
            for svc, v in lab["services"].items():
                for T in bars:
                    a = (v.get("abs") or {}).get(str(T))
                    if a:
                        rec["bars"][str(T)][svc] = {"y_mean": a["y_mean"], "y_peak": a["y_peak"], "p_B1L": a["p_B1L"],
                                                    "n_B1L": v.get("N_B1L"), "N_M": v.get("N_M")}
            fo.write(json.dumps(rec) + "\n"); n += 1
            if n % 100 == 0:
                print(f"  {n}/{len(ids)}", flush=True)
    print(f"wrote {n} episodes x {len(bars)} bars to {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
