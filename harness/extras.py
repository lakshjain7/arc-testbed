#!/usr/bin/env python3
"""Three extra checks of ARC's damage prediction (target y_peak, latency inputs off, same split and scoring
as train_gnn.py).

  extras.py DATASET.jsonl [--test OTHER.jsonl] [--seeds 5]

1. "I'm not sure" signal. ARC is trained with several seeds. Two signals:
     disagreement  the spread (std) of the seeds' predictions, averaged over the episode's services
     novelty       how far the episode is from the nearest training episode (standardised summary of the state
                   before the action + action type + fault type)
   Is a high signal a sign of a bad prediction? Reported: correlation with the episode's error, and the error of
   the 20 % most flagged episodes against the rest.
2. T13 best-case root cause. The same model given one extra input per service: "this is the faulty service"
   (the true fault target, as a perfect root-cause tool would report it).
3. ARC + trees. Per service w * ARC + (1 - w) * B6 trees; w chosen on the validation blocks (best Spearman
   with an MAE at most 10 % worse than ARC's).
"""
import random, sys
import numpy as np
import torch

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import train_gnn as T
from baselines import load, roles, spearman

T.DROP.add("latency")
KEY = "y_peak"
FE = ["rps_ratio", "err_share", "cpu_use_frac", "throttled", "mem_ratio", "not_ready", "bad_before", "is_action_target"]


def tens(ep, oracle):
    X, Y, M, s, d = T.tensors(ep, KEY)
    if oracle:
        ft = ep["fault"]["target"]
        X = torch.cat([X, torch.tensor([[1.0 if n["service"] == ft else 0.0] for n in ep["nodes"]])], 1)
    return X, Y, M, s, d


def train(tr, va, seed, oracle):
    torch.manual_seed(seed); random.seed(seed)
    Dtr = [tens(e, oracle) for e in tr]; Dva = [tens(e, oracle) for e in va]
    model = T.GNN(Dtr[0][0].shape[1]); opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    best, state, bad = 1e9, None, 0
    order = list(range(len(Dtr)))
    for _ in range(300):
        model.train(); random.shuffle(order)
        for i in order:
            X, Y, M, s, d = Dtr[i]
            if M.sum() == 0:
                continue
            loss = ((model(X, s, d) - Y).abs() * M).sum() / M.sum()
            opt.zero_grad(); loss.backward(); opt.step()
        v = T.evaluate(model, va, Dva, KEY)[0]
        if v < best - 1e-4:
            best, state, bad = v, {k: t.clone() for k, t in model.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= 25:
                break
    model.load_state_dict(state); model.eval()
    return model


def predict(model, ep, oracle):
    X, Y, M, s, d = tens(ep, oracle)
    with torch.no_grad():
        return model(X, s, d).numpy(), Y.numpy(), M.numpy() > 0


def score(eps, P):
    """P[i] = per-node predictions for eps[i]; returns MAE (points), Spearman, top-1 like train_gnn.evaluate."""
    err, cnt, rhos, hits, n = 0.0, 0, [], 0, 0
    for ep, p in zip(eps, P):
        _, Y, M = predict_cache[id(ep)]
        ys = list(Y[M]); ps = list(p[M])
        err += sum(abs(a - b) for a, b in zip(ys, ps)); cnt += len(ys)
        if len(ys) >= 3:
            r = spearman(ps, ys)
            if r is not None:
                rhos.append(r)
            if max(ys) > 0.05:
                n += 1; hits += ys.index(max(ys)) == ps.index(max(ps))
    return 100 * err / max(cnt, 1), float(np.mean(rhos)), hits / max(n, 1)


predict_cache = {}


def main(args):
    eps = load(args[0]); seeds = int(args[args.index("--seeds") + 1]) if "--seeds" in args else 5
    train_eps = [e for e in eps if e["split"] == "train"]
    test = load(args[args.index("--test") + 1]) if "--test" in args else [e for e in eps if e["split"] == "test"]
    blocks = sorted({(e["plan"], e["block"]) for e in train_eps}); vb = set(blocks[int(0.85 * len(blocks)):])
    tr = [e for e in train_eps if (e["plan"], e["block"]) not in vb]; va = [e for e in train_eps if (e["plan"], e["block"]) in vb]
    print(f"{len(tr)} train, {len(va)} validation, {len(test)} test episodes; {seeds} seeds", flush=True)

    # --- ARC ensemble
    models = [train(tr, va, s, False) for s in range(seeds)]
    for e in va + test:
        p, Y, M = predict(models[0], e, False); predict_cache[id(e)] = (p, Y, M)
    ens = {id(e): np.stack([predict(m, e, False)[0] for m in models]) for e in va + test}
    mean = lambda e: ens[id(e)].mean(0)
    for i in range(seeds):
        print(f"  seed {i}: MAE {score(test, [ens[id(e)][i] for e in test])[0]:.2f}")
    r = score(test, [mean(e) for e in test])
    print(f"ARC ensemble of {seeds}: MAE {r[0]:.2f}, Spearman {r[1]:.3f}, top-1 {r[2]:.2f}", flush=True)

    # --- 1. "I'm not sure"
    def summary(ep):
        X = np.array([[n["x"].get(k) or 0.0 for k in FE] for n in ep["nodes"]])
        a = [1.0 if ep["action"]["type"] == x else 0.0 for x in T.ACTIONS]
        f = [1.0 if ep["fault"]["type"] == x else 0.0 for x in ("none", "network-delay", "net-loss", "pod-kill", "pod-hang", "db-delay", "cpu-squeeze")]
        return np.concatenate([X.mean(0), X.max(0), a, f])
    S = np.array([summary(e) for e in train_eps]); mu, sd = S.mean(0), S.std(0) + 1e-6; Sz = (S - mu) / sd
    nov = lambda e: float(np.sort(np.linalg.norm(Sz - np.clip((summary(e) - mu) / sd, -5, 5), axis=1))[:3].mean())   # z clipped: a never-seen fault type counts as far, not infinitely far
    rows = []
    for e in test:
        _, Y, M = predict_cache[id(e)]
        if M.sum() == 0:
            continue
        E = ens[id(e)]
        rows.append((100 * np.abs(E.mean(0)[M] - Y[M]).mean(), 100 * E.std(0)[M].mean(), nov(e)))
    err = np.array([r[0] for r in rows])
    for j, name in ((1, "disagreement"), (2, "novelty")):
        sig = np.array([r[j] for r in rows]); top = sig >= np.quantile(sig, 0.8)
        print(f"  not-sure signal {name:12s}: Spearman with episode error {spearman(list(sig), list(err)):.2f}; "
              f"error of the 20 % most flagged {err[top].mean():.2f} vs rest {err[~top].mean():.2f} points "
              f"(signal mean {sig.mean():.2f})")
    vnov = np.array([nov(e) for e in va])
    print(f"  novelty above the 95th percentile of the validation episodes: {100 * np.mean([r[2] > np.quantile(vnov, 0.95) for r in rows]):.0f} % of test episodes", flush=True)

    # --- 3. ARC + trees
    from sklearn.ensemble import GradientBoostingRegressor
    RO = ["target", "up1", "up2+", "down", "other", "no-target"]
    def feats(ep):
        r = roles(ep)
        return np.array([[n["x"].get(k) if n["x"].get(k) is not None else (1.0 if k.endswith("ratio") else 0.0) for k in FE]
                         + [1.0 if r[n["service"]] == x else 0.0 for x in RO] + [1.0 if ep["action"]["type"] == x else 0.0 for x in T.ACTIONS]
                         for n in ep["nodes"]])
    Xtr, Ytr = [], []
    for e in tr:
        _, Y, M = predict(models[0], e, False); F = feats(e)
        Xtr += list(F[M]); Ytr += list(Y[M])
    gbr = GradientBoostingRegressor(loss="absolute_error", n_estimators=300, max_depth=3, learning_rate=0.05, random_state=0).fit(Xtr, Ytr)
    tree = {id(e): gbr.predict(feats(e)) for e in va + test}
    blend = lambda es, w: [w * mean(e) + (1 - w) * tree[id(e)] for e in es]
    ws = [0.0, 0.25, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    vres = {w: score(va, blend(va, w)) for w in ws}
    ok = [w for w in ws if vres[w][0] <= 1.1 * vres[1.0][0]]; wbest = max(ok, key=lambda w: vres[w][1])
    for w in ws:
        r = score(test, blend(test, w))
        print(f"  blend w={w:.2f} (1 = ARC only, 0 = trees only): test MAE {r[0]:.2f}, Spearman {r[1]:.3f}, top-1 {r[2]:.2f}"
              + ("   <- chosen on validation" if w == wbest else ""), flush=True)

    # --- 2. T13 best-case root cause
    om = [train(tr, va, s, True) for s in range(min(seeds, 3))]
    po = [np.mean([predict(m, e, True)[0] for m in om], 0) for e in test]
    r = score(test, po)
    print(f"T13 ARC given the true faulty service ({len(om)} seeds): MAE {r[0]:.2f}, Spearman {r[1]:.3f}, top-1 {r[2]:.2f}")
    for f in sorted({e["fault"]["type"] for e in test}):
        idx = [i for i, e in enumerate(test) if e["fault"]["type"] == f]
        a = score([test[i] for i in idx], [mean(test[i]) for i in idx]); b = score([test[i] for i in idx], [po[i] for i in idx])
        print(f"    fault {f:10s} {len(idx):4d} episodes: MAE {a[0]:.2f} -> {b[0]:.2f}, top-1 {a[2]:.2f} -> {b[2]:.2f}")


if __name__ == "__main__":
    main(sys.argv[1:])
