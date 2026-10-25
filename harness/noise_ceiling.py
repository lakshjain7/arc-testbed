#!/usr/bin/env python3
"""How well could ANY predictor do when the same incident, repeated, gives different numbers each time?

  noise_ceiling.py REPTEST_DATASET.jsonl

The repeatability test runs each recipe (same fault, same target and level, same action, same target) five times.
For each recipe and each service scored in a replicate (>= 30 requests before and after), the best a predictor
can do is to know the recipe's expected outcome. We estimate that by leave-one-out: predict replicate j by the
mean of the other replicates and take the mean absolute error. This is the noise ceiling: ARC's MAE cannot
honestly go below it on incidents like these (it may look lower on a small test set by luck).
Also reported: the spread of the episode's net effect (sum of y_mean over scored services) per recipe.
Recipe = (episode id without its last _k).
"""
import json, sys
from collections import defaultdict
import numpy as np

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from baselines import load, MIN_N


def main(path):
    eps = load(path); rec = defaultdict(list)
    for e in eps:
        rec[e["episode_id"].rsplit("_", 1)[0]].append(e)
    print(f"{len(eps)} episodes, {len(rec)} recipes")
    allerr = {"y_peak": [], "y_mean": []}
    for r, es in sorted(rec.items()):
        a = es[0]
        print(f"\n{r}: {len(es)} replicates; fault {a['fault']['type']}@{a['fault']['target']}, action {a['action']['type']}@{a['action']['target']}")
        per = {"y_peak": defaultdict(dict), "y_mean": defaultdict(dict)}
        net = []
        for j, e in enumerate(es):
            s = 0.0
            for n in e["nodes"]:
                y = n["y"]
                if (y.get("n_before") or 0) >= MIN_N and (y.get("n_after") or 0) >= MIN_N and y.get("y_peak") is not None:
                    per["y_peak"][n["service"]][j] = y["y_peak"]; per["y_mean"][n["service"]][j] = y["y_mean"]; s += y["y_mean"]
            net.append(100 * s)
        print(f"  net effect per replicate (points): {[round(x, 1) for x in net]}  mean {np.mean(net):.1f}, sd {np.std(net, ddof=1):.1f}"
              + (f", CV {100 * np.std(net, ddof=1) / abs(np.mean(net)):.0f} %" if abs(np.mean(net)) > 0.5 else ""))
        for key in ("y_peak", "y_mean"):
            errs, spread = [], []
            for svc, d in per[key].items():
                if len(d) < 4:
                    continue
                v = np.array(list(d.values()))
                loo = [abs(v[i] - np.delete(v, i).mean()) for i in range(len(v))]
                errs += loo; spread.append((svc, float(v.std(ddof=1)), float(v.mean())))
            if errs:
                allerr[key] += errs
                top = sorted(spread, key=lambda x: -x[1])[:3]
                print(f"  {key}: noise-ceiling MAE {100 * np.mean(errs):.2f} points over {len(spread)} services; "
                      f"noisiest: " + ", ".join(f"{s[3:-8] if s.startswith('ts-') else s} sd {100 * sd:.1f} (mean {100 * m:.1f})" for s, sd, m in top))
    print()
    for key, v in allerr.items():
        print(f"ALL recipes, {key}: noise-ceiling MAE {100 * np.mean(v):.2f} points ({len(v)} service-replicates)")


if __name__ == "__main__":
    main(sys.argv[1])
