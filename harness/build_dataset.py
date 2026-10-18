#!/usr/bin/env python3
"""Turn recorded episodes into model input: one graph per episode, as the system looked BEFORE the action.

  build_dataset.py RAW_DIR [RAW_DIR ...] --out DATASET.jsonl [--plans main,main2]

One JSON object per line (= per usable episode):
  episode_id, plan, block, split ("train" / "test"), action {type, target}, fault {type, target, level}
    (fault is for analysis only and is NEVER a model input), saturated_before_action
  nodes: list of services, each with
    x: input features, all relative to the service's own healthy baseline B0 or bounded, so they mean the
       same on every machine:
         rps_ratio       request rate before the action / B0
         err_share       errors / requests before the action
         p50_ratio, p95_ratio, p99_ratio   latency before the action / B0
         cpu_use_frac    CPU cores used / CPU limit (2 cores unless a squeeze or cpu-bump changed it)
         throttled       share of CPU periods throttled before the action
         mem_ratio       memory before the action / B0
         not_ready       1 if the pod was not ready at any point before the action
         bad_before      share of the service's requests that were bad (label definition) in the 60 s
                         before the action (from labels_v2.json, N_B1L / X_B1L: measured, not a future value)
         is_action_target  1 for the service the action hits
    y: targets (what happened after the action), machine-relative and fixed-threshold:
         y_mean, y_peak, t_recover_s, y_mean_abs1000, y_peak_abs1000, verdict
  edges: caller -> callee seen before the action, with rps and failed share.
"Before the action" = the 60 s ending at the action (the labels' B1L window).
Split: by block, so the episodes of one block (same fault, randomised actions) never sit on both sides.
Every 5th block of each plan (block % 5 == 0) is test.
"""
import csv, gzip, json, math, os, sys
from collections import defaultdict

PRE_S = 60
ACTIONS = ["noop", "restart-pod", "rollout-restart", "scale-up", "cpu-bump", "drain"]


def f(v):
    try:
        x = float(v)
        return None if math.isnan(x) else x
    except (TypeError, ValueError):
        return None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def ratio(a, b, cap=50.0):
    if a is None or b is None:
        return None
    if b <= 1e-9:
        return 1.0 if a <= 1e-9 else cap
    return min(a / b, cap)


def cpu_limit(meta, svc):
    lim = 2.0
    fi, ai = meta.get("fault_info") or {}, meta.get("action_info") or {}
    if meta.get("fault_type") == "cpu-squeeze" and meta.get("fault_target") == svc and fi.get("cpu_limit"):
        v = str(fi["cpu_limit"]); lim = float(v[:-1]) / 1000 if v.endswith("m") else float(v)
    return lim


def episode(d):
    meta = json.load(open(os.path.join(d, "meta.json")))
    lab = json.load(open(os.path.join(d, "labels_v2.json")))
    w = meta["windows"]
    t_act = w["B1"][1]
    b0 = w["B0"]
    rows = list(csv.DictReader(gzip.open(os.path.join(d, "services.csv.gz"), "rt")))
    pre = lambda t: t_act - PRE_S < t <= t_act
    base = lambda t: b0[0] <= t <= b0[1]
    by = defaultdict(lambda: {"pre": [], "base": []})
    for r in rows:
        t = float(r["t"])
        if pre(t):
            by[r["service"]]["pre"].append(r)
        elif base(t):
            by[r["service"]]["base"].append(r)
    nodes = []
    for svc in sorted(set(by) | set(lab["services"])):
        P, B = by[svc]["pre"], by[svc]["base"]
        g = lambda rs, k: mean([f(r[k]) for r in rs])
        rps_p, rps_b = g(P, "rps"), g(B, "rps")
        err_p = g(P, "err_rps")
        L = lab["services"].get(svc, {})
        nb, xb = L.get("N_B1L") or 0, L.get("X_B1L") or 0
        x = {
            "rps_ratio": ratio(rps_p, rps_b),
            "err_share": (err_p / rps_p) if (err_p is not None and rps_p) else 0.0,
            "p50_ratio": ratio(g(P, "p50_ms"), g(B, "p50_ms")),
            "p95_ratio": ratio(g(P, "p95_ms"), g(B, "p95_ms")),
            "p99_ratio": ratio(g(P, "p99_ms"), g(B, "p99_ms")),
            "cpu_use_frac": (g(P, "cpu_cores") or 0.0) / cpu_limit(meta, svc),
            "throttled": g(P, "throttled") or 0.0,
            "mem_ratio": ratio(g(P, "mem_mb"), g(B, "mem_mb")),
            "not_ready": 1.0 if any(f(r["ready"]) == 0 for r in P) else 0.0,
            "bad_before": (xb + 0.5) / (nb + 1),
            "is_action_target": 1.0 if svc == meta.get("action_target") else 0.0,
        }
        a = L.get("abs", {}).get("1000") or {}
        y = {"y_mean": L.get("y_mean"), "y_peak": L.get("y_peak"), "t_recover_s": L.get("t_recover_s"),
             "y_mean_abs1000": a.get("y_mean"), "y_peak_abs1000": a.get("y_peak"), "verdict": L.get("verdict"),
             "n_before": nb, "n_after": L.get("N_M")}
        nodes.append({"service": svc, "x": x, "y": y})
    edges = defaultdict(lambda: [0.0, 0.0, 0])
    for r in csv.DictReader(gzip.open(os.path.join(d, "edges.csv.gz"), "rt")):
        if pre(float(r["t"])) and r["client"] and r["server"]:
            e = edges[(r["client"], r["server"])]
            e[0] += f(r["rps"]) or 0.0; e[1] += f(r["failed_rps"]) or 0.0; e[2] += 1
    E = [{"src": a, "dst": b, "rps": v[0] / v[2], "failed_share": (v[1] / v[0]) if v[0] else 0.0}
         for (a, b), v in edges.items() if v[0] > 0]
    return meta, lab, nodes, E


def main(args):
    out = args[args.index("--out") + 1] if "--out" in args else "dataset.jsonl"
    plans = set(args[args.index("--plans") + 1].split(",")) if "--plans" in args else None
    roots = [a for a in args if os.path.isdir(a)]
    n = skipped = 0
    with open(out, "w") as fo:
        for root in roots:
            for name in sorted(os.listdir(root)):
                d = os.path.join(root, name)
                parts = name.split("_")
                plan = parts[1] if len(parts) > 2 else ""
                if plans and plan not in plans:
                    continue
                try:
                    meta, lab, nodes, E = episode(d)
                except Exception as e:      # missing files or labels: not usable
                    skipped += 1
                    continue
                if meta.get("status") != "ok" or lab.get("stalled"):
                    skipped += 1
                    continue
                blk = next((int(p[1:]) for p in parts if p.startswith("b") and p[1:].isdigit()), 0)
                rec = {"episode_id": name, "plan": plan, "block": blk,
                       "split": "test" if blk and blk % 5 == 0 else "train",
                       "action": {"type": meta.get("action_type"), "target": meta.get("action_target")},
                       "fault": {"type": meta.get("fault_type"), "target": meta.get("fault_target"),
                                 "level": meta.get("fault_param")},
                       "saturated_before_action": bool(lab.get("saturated_before_action")),
                       "user_damage": (lab.get("summary") or {}).get("user_damage"),
                       "user_damage_abs1000": (lab.get("summary") or {}).get("user_damage_abs1000"),
                       "nodes": nodes, "edges": E}
                fo.write(json.dumps(rec) + "\n")
                n += 1
    print(f"wrote {n} episodes to {out} ({skipped} skipped)")


if __name__ == "__main__":
    main(sys.argv[1:])
