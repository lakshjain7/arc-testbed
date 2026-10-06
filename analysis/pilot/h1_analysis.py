#!/usr/bin/env python3
"""H1 analysis for the pilot, fixed BEFORE the pilot ran (pre-registered, research/06 §4.1).

H1: remediation actions cause measurable collateral damage on services OTHER than the one they target.

Per episode (status ok, not stalled, label v2):
  C = number of services with verdict "harm", excluding the action target and the fault target.
      ("inconclusive" and "no_data" services count as not harmed; their numbers are reported.)
Primary test: within-block permutation test of mean C,
      disruptive actions {restart-pod, rollout-restart, scale-up, drain}  vs  noop.
Secondary: each action vs noop.  Negative control: cpu-bump vs noop should be ~0.
H1 holds if: pooled difference >= 1.5 services/episode, p < 0.05, AND at least 2 single actions have
      mean C >= 2x the noop mean.
Where the harm lands, for every harmed service: (a) upstream caller of the action target,
      (b) downstream callee, (c) neither (same machine / infrastructure). A non-zero (c) is evidence
      that graph reachability alone cannot predict collateral damage.

  ARC_PILOT_RAW=~/arc/data/raw python3 analysis/pilot/h1_analysis.py [--perm 10000]
"""
import csv, gzip, json, os, random, sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "harness"))
import arcenv
RAW = os.path.expanduser(os.environ.get("ARC_PILOT_RAW", arcenv.RAW))      # folder holding ep_pilot_b* episodes
DISRUPTIVE = ["restart-pod", "rollout-restart", "scale-up", "drain"]
N_PERM = int(sys.argv[sys.argv.index("--perm") + 1]) if "--perm" in sys.argv else 10000


def graph(d):
    """Caller->callee edges seen in B0 (healthy), from edges.csv.gz."""
    out = defaultdict(set)
    for r in csv.DictReader(gzip.open(os.path.join(d, "edges.csv.gz"), "rt")):
        if r["window"] == "B0" and r["rps"] not in ("", "0", "0.0") and r["client"] and r["server"]:
            out[r["client"]].add(r["server"])
    return out


def reach(g, start):
    seen, todo = set(), [start]
    while todo:
        x = todo.pop()
        for y in g.get(x, ()):
            if y not in seen:
                seen.add(y)
                todo.append(y)
    return seen


def load():
    eps = []
    for name in sorted(os.listdir(RAW)):
        if not name.startswith("ep_pilot_b"):
            continue
        d = os.path.join(RAW, name)
        try:
            meta = json.load(open(os.path.join(d, "meta.json")))
            lab = json.load(open(os.path.join(d, "labels_v2.json")))
        except (OSError, ValueError):
            continue
        if meta.get("status") != "ok" or lab.get("stalled"):
            continue
        block = int(name.split("_b")[1].split("_")[0])
        excl = {meta.get("action_target"), meta.get("fault_target")}
        g = graph(d)
        rev = defaultdict(set)
        for a, bs in g.items():
            for b in bs:
                rev[b].add(a)
        at = meta.get("action_target")
        down, up = (reach(g, at), reach(rev, at)) if at else (set(), set())
        harmed = [s for s, v in lab["services"].items() if v["verdict"] == "harm" and s not in excl]
        where = {"upstream": sum(s in up for s in harmed), "downstream": sum(s in down and s not in up for s in harmed),
                 "neither": sum(s not in up and s not in down for s in harmed)}
        verdicts = [v["verdict"] for s, v in lab["services"].items() if s not in excl]
        eps.append({"id": name, "block": block, "action": meta["action_type"], "fault": meta["fault_type"],
                    "C": len(harmed), "harmed": harmed, "where": where,
                    "inconclusive": verdicts.count("inconclusive"), "no_data": verdicts.count("no_data"),
                    "fault_on_new_pod": meta.get("fault_on_new_pod")})
    return eps


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def perm_test(eps, group_a, group_b, rng):
    """Difference of means (A - B) and a within-block permutation p-value (one-sided, A > B)."""
    sel = [e for e in eps if e["action"] in group_a or e["action"] in group_b]
    lab = [e["action"] in group_a for e in sel]
    obs = mean([e["C"] for e, a in zip(sel, lab) if a]) - mean([e["C"] for e, a in zip(sel, lab) if not a])
    blocks = defaultdict(list)
    for i, e in enumerate(sel):
        blocks[e["block"]].append(i)
    hits = 0
    for _ in range(N_PERM):
        perm = lab[:]
        for idx in blocks.values():
            vals = [lab[i] for i in idx]
            rng.shuffle(vals)
            for i, v in zip(idx, vals):
                perm[i] = v
        d = mean([e["C"] for e, a in zip(sel, perm) if a]) - mean([e["C"] for e, a in zip(sel, perm) if not a])
        hits += d >= obs - 1e-12
    return obs, (hits + 1) / (N_PERM + 1), sum(lab), len(lab) - sum(lab)


def main():
    rng = random.Random(7)
    eps = load()
    print(f"usable pilot episodes: {len(eps)} (ok, not stalled, labelled v2)\n")
    by = defaultdict(list)
    for e in eps:
        by[e["action"]].append(e)
    noop_mean = mean([e["C"] for e in by["noop"]])
    print(f"  {'action':16s} {'n':>3s} {'mean C':>7s}  {'where: up/down/neither':>24s}  {'inconcl/ep':>10s}")
    for a in ["noop", "cpu-bump"] + DISRUPTIVE:
        es = by.get(a, [])
        w = [sum(e["where"][k] for e in es) for k in ("upstream", "downstream", "neither")]
        print(f"  {a:16s} {len(es):3d} {mean([e['C'] for e in es]):7.2f}  {w[0]:8d}/{w[1]:4d}/{w[2]:<8d}  "
              f"{mean([e['inconclusive'] for e in es]):10.1f}")
    print()
    d, p, na, nb = perm_test(eps, DISRUPTIVE, ["noop"], rng)
    print(f"PRIMARY  disruptive vs noop: difference {d:+.2f} services/episode, p = {p:.4f}  (n = {na} vs {nb})")
    singles = []
    for a in DISRUPTIVE + ["cpu-bump"]:
        da, pa, n1, n2 = perm_test(eps, [a], ["noop"], rng)
        ratio = mean([e["C"] for e in by.get(a, [])]) / noop_mean if noop_mean else float("inf")
        tag = "  (negative control: should be ~0)" if a == "cpu-bump" else ""
        print(f"  {a:16s} vs noop: {da:+.2f}, p = {pa:.4f}, {ratio:.1f}x noop{tag}")
        # with a noop mean of 0 the "2x noop" ratio is meaningless (0 x 2 = 0); require a positive
        # mean C as well, so actions that harmed nothing can't pass (pre-registration flaw, fixed openly)
        if a in DISRUPTIVE and ratio >= 2 and mean([e["C"] for e in by.get(a, [])]) > 0:
            singles.append(a)
    holds = d >= 1.5 and p < 0.05 and len(singles) >= 2
    print(f"\nH1 {'HOLDS' if holds else 'NOT SUPPORTED'}: difference {d:+.2f} (need >= 1.5), p = {p:.4f} (need < 0.05), "
          f"single actions >= 2x noop: {singles or 'none'} (need >= 2)")
    tot = defaultdict(int)
    for e in eps:
        for k, v in e["where"].items():
            tot[k] += v
    print(f"where collateral harm landed (all episodes): upstream {tot['upstream']}, downstream {tot['downstream']}, "
          f"neither {tot['neither']}  <- 'neither' = not explained by the call graph")
    json.dump({"episodes": eps, "primary": {"diff": d, "p": p}, "h1_holds": holds},
              open(os.path.join(os.path.dirname(RAW), "h1_result.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
