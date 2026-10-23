#!/usr/bin/env python3
"""Simple predictors of per-service damage that any learned model must beat.

  baselines.py DATASET.jsonl [--target y_peak|y_mean|y_peak_abs1000|y_mean_abs1000]

Task: given the system before the action and the action, predict each service's damage (default y_peak,
the worst 30 s rise of its bad-request share after the action). Services with too few requests
(n_before or n_after < 30) are left out of scoring: their labels are mostly noise.
Fitted on the train split, scored on the test split (split by block, see build_dataset.py).

  B0 zero           predict no damage anywhere
  B1 action mean    the average damage of this action type (train), same for every service
  B2 role           average by (action type, role of the service relative to the action target):
                    target / upstream caller (1 hop, 2+ hops) / downstream callee / unrelated, with roles
                    from the call graph seen before the action
  B3 role + state   B2 plus the service's own badness before the action (does a hurt service get hurt more?):
                    per-(action, role) least-squares line on bad_before

Scores: MAE (points), Spearman rank correlation within each episode (does it rank the services
right?), and top-1 hit (is the most-damaged service the one predicted most damaged?).
"""
import json, sys
from collections import defaultdict

MIN_N = 30


def load(path):
    return [json.loads(l) for l in open(path)]


def roles(ep):
    tgt = ep["action"]["target"]
    out_, in_ = defaultdict(set), defaultdict(set)
    for e in ep["edges"]:
        out_[e["src"]].add(e["dst"]); in_[e["dst"]].add(e["src"])
    def dist(start, nbr):
        d, frontier = {start: 0}, [start]
        while frontier:
            nxt = []
            for u in frontier:
                for v in nbr[u]:
                    if v not in d:
                        d[v] = d[u] + 1; nxt.append(v)
            frontier = nxt
        return d
    up, down = dist(tgt, in_) if tgt else {}, dist(tgt, out_) if tgt else {}
    r = {}
    for n in ep["nodes"]:
        s = n["service"]
        if not tgt:
            r[s] = "no-target"
        elif s == tgt:
            r[s] = "target"
        elif s in up:
            r[s] = "up1" if up[s] == 1 else "up2+"
        elif s in down:
            r[s] = "down"
        else:
            r[s] = "other"
    return r


def scored(ep, key):
    for n in ep["nodes"]:
        y = n["y"].get(key)
        if y is None or (n["y"].get("n_before") or 0) < MIN_N or (n["y"].get("n_after") or 0) < MIN_N:
            continue
        yield n, y


def spearman(a, b):
    if len(a) < 3:
        return None
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2
            i = j + 1
        return r
    ra, rb = rank(a), rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else None


def fit(train, key):
    act, role = defaultdict(list), defaultdict(list)
    for ep in train:
        r = roles(ep)
        for n, y in scored(ep, key):
            a = ep["action"]["type"]
            act[a].append(y); role[(a, r[n["service"]])].append((n["x"]["bad_before"], y))
    m_act = {k: sum(v) / len(v) for k, v in act.items()}
    m_role = {k: sum(y for _, y in v) / len(v) for k, v in role.items()}
    line = {}
    for k, v in role.items():
        if len(v) >= 10:
            mx = sum(x for x, _ in v) / len(v); my = sum(y for _, y in v) / len(v)
            sxx = sum((x - mx) ** 2 for x, _ in v)
            b = sum((x - mx) * (y - my) for x, y in v) / sxx if sxx > 1e-12 else 0.0
            line[k] = (my - b * mx, b)
    return m_act, m_role, line


def main(args):
    path = args[0]
    key = args[args.index("--target") + 1] if "--target" in args else "y_peak"
    eps = load(path)
    if "--fold" in args:        # 5-fold cross-validation by block: fold k tests the blocks with block % 5 == k
        k = int(args[args.index("--fold") + 1])
        for e in eps:
            e["split"] = "test" if e["block"] % 5 == k else "train"
    if "--train-plans" in args:  # sensitivity: train only on some plans (e.g. main2), test split unchanged
        keep = set(args[args.index("--train-plans") + 1].split(","))
        eps = [e for e in eps if e["split"] == "test" or e["plan"] in keep]
    train = [e for e in eps if e["split"] == "train"]; test = [e for e in eps if e["split"] == "test"]
    if "--test" in args:        # unseen-system test: train on this file's train split, test on ALL of another
        test = load(args[args.index("--test") + 1])
    m_act, m_role, line = fit(train, key)
    # B4 diffusion (what the closest prior work uses): damage spreads from the action target along the call
    # graph, weakening by a factor per hop in either direction; one scale per action type fitted on train
    def spread(ep, decay=0.5):
        out_, in_ = defaultdict(set), defaultdict(set)
        for e in ep["edges"]:
            out_[e["src"]].add(e["dst"]); in_[e["dst"]].add(e["src"])
        tgt = ep["action"]["target"]; score = defaultdict(float)
        if not tgt:
            return score
        score[tgt] = 1.0; frontier = {tgt}; seen = {tgt}; w = 1.0
        while frontier:
            w *= decay; nxt = set()
            for u in frontier:
                for v in out_[u] | in_[u]:
                    if v not in seen:
                        seen.add(v); nxt.add(v); score[v] = w
            frontier = nxt
        return score
    num, den = defaultdict(float), defaultdict(float)
    for ep in train:
        sc = spread(ep)
        for n, y in scored(ep, key):
            x = sc.get(n["service"], 0.0); a = ep["action"]["type"]; num[a] += x * y; den[a] += x * x
    beta = {a: num[a] / den[a] if den[a] else 0.0 for a in num}
    # B5 dependency map (commercial service maps): every caller within 3 hops of the changed service is at
    # risk; the predicted damage is the training mean for that hop distance, whatever the action
    hopmean = defaultdict(list)
    for ep in train:
        r = roles(ep)
        for n, y in scored(ep, key):
            hopmean[r[n["service"]] if r[n["service"]] in ("target", "up1", "up2+") else "rest"].append(y)
    hopmean = {k: sum(v) / len(v) for k, v in hopmean.items()}
    # B6 gradient-boosted trees on each service's own features + role + action, no graph aggregation
    from sklearn.ensemble import GradientBoostingRegressor
    FE = ["rps_ratio", "err_share", "cpu_use_frac", "throttled", "mem_ratio", "not_ready", "bad_before", "is_action_target"]
    RO = ["target", "up1", "up2+", "down", "other", "no-target"]
    AC = ["noop", "restart-pod", "rollout-restart", "scale-up", "cpu-bump", "drain"]
    def feats(ep, n, r):
        return ([n["x"].get(k) if n["x"].get(k) is not None else (1.0 if k.endswith("ratio") else 0.0) for k in FE]
                + [1.0 if r[n["service"]] == x else 0.0 for x in RO] + [1.0 if ep["action"]["type"] == x else 0.0 for x in AC])
    Xtr, Ytr = [], []
    for ep in train:
        r = roles(ep)
        for n, y in scored(ep, key):
            Xtr.append(feats(ep, n, r)); Ytr.append(y)
    gbr = GradientBoostingRegressor(loss="absolute_error", n_estimators=300, max_depth=3, learning_rate=0.05, random_state=0).fit(Xtr, Ytr)
    preds = {
        "B0 zero": lambda ep, n, r: 0.0,
        "B5 dependency map": lambda ep, n, r: hopmean.get(r[n["service"]] if r[n["service"]] in ("target", "up1", "up2+") else "rest", 0.0),
        "B6 trees, no graph": lambda ep, n, r: float(gbr.predict([feats(ep, n, r)])[0]),
        "B1 action mean": lambda ep, n, r: m_act.get(ep["action"]["type"], 0.0),
        "B2 role": lambda ep, n, r: m_role.get((ep["action"]["type"], r[n["service"]]), m_act.get(ep["action"]["type"], 0.0)),
        "B4 diffusion": lambda ep, n, r: beta.get(ep["action"]["type"], 0.0) * spread(ep).get(n["service"], 0.0),
        "B3 role + state": lambda ep, n, r: (lambda k: (line[k][0] + line[k][1] * n["x"]["bad_before"]) if k in line
                                             else m_role.get(k, 0.0))((ep["action"]["type"], r[n["service"]])),
    }
    print(f"{path}: {len(train)} train / {len(test)} test episodes, target {key} (in points), services with >= {MIN_N} requests")
    print(f"  {'baseline':18s} {'MAE':>7s} {'Spearman':>9s} {'top-1 hit':>10s}   n services")
    for name, p in preds.items():
        err, rhos, hits, cnt, eps_n = 0.0, [], 0, 0, 0
        for ep in test:
            r = roles(ep)
            ys, ps = [], []
            for n, y in scored(ep, key):
                v = p(ep, n, r); err += abs(v - y); cnt += 1; ys.append(y); ps.append(v)
            if len(ys) >= 3:
                rho = spearman(ps, ys)
                if rho is not None:
                    rhos.append(rho)
                if max(ys) > 0.05:
                    eps_n += 1; hits += ys.index(max(ys)) == ps.index(max(ps))
        print(f"  {name:18s} {100 * err / max(cnt, 1):7.2f} {sum(rhos) / max(len(rhos), 1):9.3f} "
              f"{(hits / eps_n if eps_n else 0):10.2f}   {cnt}")
    print("  (top-1 hit counts episodes where some service rose by more than 5 points)")
    # Yes/no view (the closest prior work predicts harmed / not harmed per service): harmed = the service's
    # damage is at least HARM points. B7 = a classifier trained for exactly that; B5 = "every caller within
    # 2 hops is harmed"; B3 and B6 thresholded at the same level.
    from sklearn.ensemble import GradientBoostingClassifier
    HARM = 0.10
    clf = GradientBoostingClassifier(n_estimators=300, max_depth=3, learning_rate=0.05, random_state=0).fit(Xtr, [y >= HARM for y in Ytr])
    yes_no = {
        "B5 callers <= 2 hops": lambda ep, n, r: r[n["service"]] in ("up1", "up2+") and ep["action"]["type"] != "noop",
        "B3 rule >= 10 pts": lambda ep, n, r: preds["B3 role + state"](ep, n, r) >= HARM,
        "B6 trees >= 10 pts": lambda ep, n, r: preds["B6 trees, no graph"](ep, n, r) >= HARM,
        "B7 yes/no classifier": lambda ep, n, r: bool(clf.predict([feats(ep, n, r)])[0]),
    }
    print(f"  yes/no 'harmed' (damage >= {int(100 * HARM)} points): {'precision':>9s} {'recall':>7s} {'F1':>6s}")
    for name, p in yes_no.items():
        tp = fp = fn = 0
        for ep in test:
            r = roles(ep)
            for n, y in scored(ep, key):
                h, ph = y >= HARM, p(ep, n, r)
                tp += h and ph; fp += (not h) and ph; fn += h and (not ph)
        pr = tp / max(tp + fp, 1); rc = tp / max(tp + fn, 1)
        print(f"    {name:24s} {pr:9.2f} {rc:7.2f} {2 * pr * rc / max(pr + rc, 1e-9):6.2f}")


if __name__ == "__main__":
    main(sys.argv[1:])
