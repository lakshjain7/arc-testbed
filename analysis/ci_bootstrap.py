#!/usr/bin/env python3
"""Block-bootstrap confidence intervals for the 5-fold results (decision log 10e).

  ci_bootstrap.py DIR [--n 10000]

DIR holds arc_f{0..4}.jsonl (train_gnn.py --dump, one row per seed and test episode) and base_f{0..4}.jsonl
(baselines.py --dump, one row per baseline and test episode). Services inside one episode, and episodes inside one
block, are not independent, so the resampling unit is the block (plan, block): draw blocks with replacement, pool
the episodes of the drawn blocks, recompute the error. Paired differences use the same draw for both models.
The ARC error of an episode is the mean over its seeds. Errors are in points (fractions x 100).
"""
import glob, json, os, random, sys
from collections import defaultdict


def main(d, n_boot=10000):
    arc = defaultdict(list)           # episode_id -> [(err, n), ...] over seeds
    meta = {}
    for f in sorted(glob.glob(os.path.join(d, "arc_f*.jsonl"))):
        for l in open(f):
            r = json.loads(l); arc[r["episode_id"]].append((r["err"], r["n"])); meta[r["episode_id"]] = (r["plan"], r["block"])
    models = {"ARC": {e: (sum(x[0] for x in v) / len(v), v[0][1]) for e, v in arc.items()}}
    for f in sorted(glob.glob(os.path.join(d, "base_f*.jsonl"))):
        for l in open(f):
            r = json.loads(l)
            models.setdefault(r["model"], {})[r["episode_id"]] = (r["err"], r["n"])
    ids = sorted(arc)
    blocks = defaultdict(list)
    for e in ids:
        blocks[meta[e]].append(e)
    keys = sorted(blocks)
    print(f"{len(ids)} episodes in {len(keys)} blocks; {n_boot} resamples of blocks")
    use = ["ARC", "B6 trees, no graph", "B3 role + state", "B1 action mean", "B5 dependency map", "B0 zero"]
    use = [m for m in use if m in models]

    def pooled(model, draw):
        s = c = 0.0
        for k in draw:
            for e in blocks[k]:
                a, n = models[model][e]; s += a; c += n
        return 100 * s / max(c, 1)

    random.seed(0)
    draws = [[random.choice(keys) for _ in keys] for _ in range(n_boot)]

    def ci(v):
        v = sorted(v); return v[int(0.025 * len(v))], v[int(0.975 * len(v)) - 1]

    print(f"\n{'model':22s} {'MAE':>6s}   95% CI")
    for m in use:
        pt = pooled(m, keys); lo, hi = ci([pooled(m, dr) for dr in draws])
        print(f"{m:22s} {pt:6.2f}   [{lo:.2f}, {hi:.2f}]")
    print("\npaired difference in MAE (model - ARC; positive = ARC better)")
    for m in use:
        if m == "ARC":
            continue
        pt = pooled(m, keys) - pooled("ARC", keys)
        lo, hi = ci([pooled(m, dr) - pooled("ARC", dr) for dr in draws])
        print(f"{m:22s} {pt:6.2f}   [{lo:.2f}, {hi:.2f}]")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], int(a[a.index("--n") + 1]) if "--n" in a else 10000)
