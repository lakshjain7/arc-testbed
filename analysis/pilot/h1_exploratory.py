#!/usr/bin/env python3
"""EXPLORATORY (not pre-registered): is the action's damage visible in MAGNITUDES, even where the
binary per-service verdict is 'inconclusive'?
  A) collateral magnitude = sum over services other than the action/fault targets of max(0, y_peak)
     (worst 30 s rise in bad-request ratio, percentage points)
  B) user-facing damage   = rise of the bad-request ratio per client flow (search, book, orders, pay),
     M vs B1L, summed over flows
Both compared action vs noop with the same within-block permutation test as the primary analysis.
Split by fault severity: blocks whose B1 users were already >= 80% bad (saturated) vs the rest."""
import json, os, random, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import h1_analysis as H

RAW = H.RAW
rows = []
for name in sorted(os.listdir(RAW)):
    if not name.startswith("ep_pilot_b"):
        continue
    try:
        m = json.load(open(f"{RAW}/{name}/meta.json")); lab = json.load(open(f"{RAW}/{name}/labels_v2.json"))
    except (OSError, ValueError):
        continue
    if m.get("status") != "ok" or lab.get("stalled"):
        continue
    excl = {m.get("action_target"), m.get("fault_target")}
    coll = sum(max(0.0, v.get("y_peak") or 0.0) for s, v in lab["services"].items()
               if s not in excl and v["verdict"] != "no_data") * 100
    flows = lab["client_flows"]
    user = sum(max(0.0, f["y_mean"]) for f in flows.values() if f.get("y_mean") is not None) * 100
    b1 = [f["p_B1L"] for f in flows.values() if f.get("p_B1L") is not None]
    saturated = bool(b1) and max(b1) >= 0.8
    rows.append({"id": name, "block": int(name.split("_b")[1].split("_")[0]), "action": m["action_type"],
                 "fault": m["fault_type"], "C": coll, "U": user, "sat": saturated})


def compare(rows, key, label):
    rng = random.Random(3)
    print(f"\n{label}")
    by = defaultdict(list)
    for r in rows:
        by[r["action"]].append(r[key])
    for a in ["noop", "cpu-bump", "restart-pod", "rollout-restart", "scale-up", "drain"]:
        xs = by.get(a, [])
        print(f"  {a:16s} n={len(xs):2d}  mean {H.mean(xs):7.1f}  median {sorted(xs)[len(xs)//2] if xs else float('nan'):7.1f}")
    for grp, name in ((H.DISRUPTIVE, "disruptive"), (["drain"], "drain"), (["restart-pod"], "restart-pod"),
                      (["rollout-restart"], "rollout-restart"), (["scale-up"], "scale-up")):
        eps = [{"block": r["block"], "action": r["action"], "C": r[key]} for r in rows]
        d, p, na, nb = H.perm_test(eps, grp, ["noop"], rng)
        print(f"  {name:16s} vs noop: {d:+7.1f}  p = {p:.3f}")


print(f"usable episodes: {len(rows)}  (saturated by the fault before the action: {sum(r['sat'] for r in rows)})")
compare(rows, "C", "A) collateral magnitude (sum of worst-30s rises, pts), ALL episodes")
compare([r for r in rows if not r["sat"]], "C", "A') same, only episodes NOT saturated by the fault")
compare(rows, "U", "B) user-facing damage (sum over flows of rise in bad %, pts), ALL episodes")
compare([r for r in rows if not r["sat"]], "U", "B') same, only episodes NOT saturated by the fault")
