#!/usr/bin/env python3
"""Explainable blast radius of each episode: WHICH services the action hit, HOW (damage profile), WHEN
(onset after the action) and ALONG WHICH CALLS the damage travelled.

  blast_radius.py TRAJ.jsonl [--show EPISODE_ID] [--out BLAST.jsonl]

Per service, comparing the 3 minutes after the action (M) with the 60 s before it (B1L), 15 s steps:
  d_bad     change in bad-request share (the ARC damage score, points)
  d_err     change in error share (availability)
  p95x      p95 latency after / before (speed)
  rpsx      request rate after / before (traffic; a drained or dead service loses its traffic)
  thr       change in CPU-throttled share (saturation)
  onset_s   first step after the action where the bad share is >= 5 points above its pre-action level for
            two steps in a row (seconds after the action); None = never hit
  recover_s first later step from which it stays within 5 points of the pre-action level
  hops      call-graph distance from the action target, and the direction (up = callers, down = callees)
  via       the neighbour that was hit EARLIER and is connected by a call (the likely path); None for the
            target or when no earlier-hit neighbour exists
Episode summary: number of services hit, total damage, deepest hop reached, hits upstream vs downstream,
and the share of non-target hits that have an earlier-hit neighbour on the call graph ("the chain follows
the calls"). Run without --show for the dataset-wide statistics used in the paper.
"""
import json, sys
from collections import Counter, defaultdict

THR, STEP_MIN_N = 0.05, 5


def load(p):
    return [json.loads(l) for l in open(p)]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def analyse(ep):
    S = ep["services"]; ka = ep["k_action"]; K = ep["K"]; step = ep["step_s"]
    pre = range(max(0, ka - 4), ka)            # 60 s before the action
    post = range(ka + 1, K)
    out_, in_ = defaultdict(set), defaultdict(set)
    for a, b in ep["edges"]:
        out_[a].add(b); in_[b].add(a)
    tgt = ep["action"]["target"]

    def dist(start, nbr):
        d = {start: 0}; fr = [start]
        while fr:
            nx = []
            for u in fr:
                for v in nbr[u]:
                    if v not in d:
                        d[v] = d[u] + 1; nx.append(v)
            fr = nx
        return d
    up = dist(tgt, in_) if tgt else {}; dn = dist(tgt, out_) if tgt else {}
    svc = {}
    for s in S:
        b, n = ep["bad"][s], ep["n"][s]
        ok = lambda k: b[k] is not None and n[k] >= STEP_MIN_N
        base = mean([b[k] for k in pre if ok(k)])
        if base is None:
            continue
        dev = {k: b[k] - base for k in post if ok(k)}
        onset = next((k for k in post if dev.get(k, 0) >= THR and dev.get(k + 1, 0) >= THR), None)
        rec = None
        if onset is not None:
            rec = next((k for k in range(onset + 1, K) if all(dev.get(j, 0) < THR for j in range(k, K))), None)
        rat = lambda name, ks: mean([ep[name][s][k] for k in ks])
        p95b, p95a, rb, ra = rat("p95r", pre), rat("p95r", post), rat("rpsr", pre), rat("rpsr", post)
        svc[s] = {"d_bad": mean(list(dev.values())), "d_err": (mean([ep["err"][s][k] for k in post]) or 0) - (mean([ep["err"][s][k] for k in pre]) or 0),
                  "p95x": (p95a / p95b) if (p95a and p95b) else None, "rpsx": (ra / rb) if (ra is not None and rb) else None,
                  "thr": (mean([ep["thr"][s][k] for k in post]) or 0) - (mean([ep["thr"][s][k] for k in pre]) or 0),
                  "onset_s": None if onset is None else (onset - ka) * step,
                  "recover_s": None if onset is None else (None if rec is None else (rec - ka) * step),
                  "hops": 0 if s == tgt else up.get(s) if s in up else dn.get(s),
                  "dir": "target" if s == tgt else "up" if s in up else "down" if s in dn else "none"}
    hit = {s: v for s, v in svc.items() if v["onset_s"] is not None}
    # The action happens AT the target at t = 0, whether or not the target itself shows a measurable rise
    # (a drained or restarting target often has no traffic to measure), so it is always a possible source.
    t_on = lambda x: 0 if x == tgt else hit[x]["onset_s"]
    for s, v in hit.items():
        nb = (out_[s] | in_[s]) & (set(hit) | ({tgt} if tgt else set()))
        earlier = [x for x in nb if x != s and t_on(x) <= v["onset_s"]]
        v["via"] = None if s == tgt else (min(earlier, key=t_on) if earlier else None)
    non_t = [s for s in hit if s != tgt]
    summ = {"hit": len(hit), "hit_up": sum(hit[s]["dir"] == "up" for s in hit), "hit_down": sum(hit[s]["dir"] == "down" for s in hit),
            "hit_none": sum(hit[s]["dir"] == "none" for s in hit), "target_hit": tgt in hit,
            "total_damage": sum(max(0.0, v["d_bad"] or 0) for v in svc.values()),
            "max_hops": max([hit[s]["hops"] or 0 for s in hit] or [0]),
            "chain_follows_calls": (sum(hit[s]["via"] is not None for s in non_t) / len(non_t)) if non_t else None}
    return svc, summ


def show(ep, svc, summ):
    a = ep["action"]; tgt = a["target"]
    print(f"{ep['episode_id']}: {a['type']} on {tgt}   (fault: {ep['fault']['type']} on {ep['fault']['target']})")
    hit = {s: v for s, v in svc.items() if v["onset_s"] is not None}
    children = defaultdict(list)
    roots = []
    for s, v in sorted(hit.items(), key=lambda x: x[1]["onset_s"]):
        (children[v["via"]].append(s) if v.get("via") and v["via"] in hit else
         children["__action__"].append(s) if v.get("via") == tgt else roots.append(s))
    def line(s, depth):
        v = hit[s]
        bits = [f"bad {100 * v['d_bad']:+.0f} pts"]
        if v["d_err"] and abs(v["d_err"]) >= 0.02:
            bits.append(f"errors {100 * v['d_err']:+.0f} pts")
        if v["p95x"] and (v["p95x"] >= 1.3 or v["p95x"] <= 0.77):
            bits.append(f"p95 x{v['p95x']:.1f}")
        if v["rpsx"] is not None and v["rpsx"] <= 0.7:
            bits.append(f"traffic {100 * (v['rpsx'] - 1):+.0f} %")
        rel = "" if v["dir"] == "target" else f" ({v['dir']} {v['hops']} hop{'s' if (v['hops'] or 0) > 1 else ''})" if v["hops"] else " (not connected)"
        rec = f", recovered +{v['recover_s']} s" if v["recover_s"] is not None else ", not recovered in 3 min"
        print(f"   {'   ' * depth}+{v['onset_s']:>3} s  {s[3:-8]}{rel}: {', '.join(bits)}{rec}")
        for c in children[s]:
            line(c, depth + 1)
    if children["__action__"]:
        print(f"     0 s  {a['type']} on {tgt[3:-8]}")
        for c in children["__action__"]:
            line(c, 1)
    for r in roots:
        line(r, 0)
    if not hit:
        print("   no service hit (no rise of 5 points or more)")
    print(f"   summary: {summ['hit']} services hit ({summ['hit_up']} callers, {summ['hit_down']} callees, {summ['hit_none']} unconnected), "
          f"total damage {100 * summ['total_damage']:.0f} pts, deepest {summ['max_hops']} hops")


def main(args):
    eps = load(args[0])
    if "--show" in args:
        want = args[args.index("--show") + 1]
        for ep in eps:
            if ep["episode_id"] == want:
                svc, summ = analyse(ep); show(ep, svc, summ)
        return
    rows = []
    fo = open(args[args.index("--out") + 1], "w") if "--out" in args else None
    for ep in eps:
        svc, summ = analyse(ep)
        rows.append((ep, svc, summ))
        if fo:
            fo.write(json.dumps({"episode_id": ep["episode_id"], "action": ep["action"], "summary": summ, "services": svc}) + "\n")
    print(f"{len(rows)} episodes")
    by = defaultdict(list)
    for ep, svc, summ in rows:
        by[ep["action"]["type"]].append(summ)
    print(f"  {'action':16s} {'episodes':>8s} {'hit/ep':>7s} {'callers':>8s} {'callees':>8s} {'unconn.':>8s} {'target hit':>11s} {'depth':>6s} {'damage':>7s} {'chain follows calls':>20s}")
    for a, ss in sorted(by.items()):
        cf = [s["chain_follows_calls"] for s in ss if s["chain_follows_calls"] is not None]
        print(f"  {a:16s} {len(ss):8d} {mean([s['hit'] for s in ss]):7.2f} {mean([s['hit_up'] for s in ss]):8.2f} {mean([s['hit_down'] for s in ss]):8.2f} "
              f"{mean([s['hit_none'] for s in ss]):8.2f} {100 * mean([s['target_hit'] for s in ss]):10.0f}% {mean([s['max_hops'] for s in ss]):6.2f} "
              f"{100 * mean([s['total_damage'] for s in ss]):7.1f} {(100 * mean(cf)) if cf else float('nan'):19.0f}%")
    onset = defaultdict(list)
    for ep, svc, summ in rows:
        for s, v in svc.items():
            if v["onset_s"] is not None and ep["action"]["type"] != "noop":
                onset[v["dir"] if v["dir"] != "up" else f"up{min(v['hops'] or 0, 3)}"].append(v["onset_s"])
    print("  median onset after the action (s), real actions only: " +
          ", ".join(f"{k} {sorted(v)[len(v) // 2]} (n={len(v)})" for k, v in sorted(onset.items())))


if __name__ == "__main__":
    main(sys.argv[1:])
