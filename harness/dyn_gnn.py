#!/usr/bin/env python3
"""ARC dynamic model, graph-network version: the same step equation as dyn_linear.py, but how much each
service keeps, passes on and receives is learned per service from its state, instead of one shared number.

  dyn_gnn.py TRAJ.jsonl [--test OTHER.jsonl] [--seeds 3] [--epochs 60] [--min-n 10]

Each step k -> k+1 after the action, for every service i:
  h_i   = encoder(state of i AT THE ACTION: deviation d, error share, p95 ratio, traffic ratio, ready,
                  throttled; role relative to the action target; action type)     (computed once)
  m_dn  = mean over the services i calls of   msg_dn(h_j, d_j(k))
  m_up  = mean over the services calling i of msg_up(h_j, d_j(k))
  d_i(k+1) = d_i(k) + step(h_i, d_i(k), m_dn, m_up, d_i(at action), steps since the action)
Trained by rolling out the whole 3 minutes from the action (the model only ever sees its own earlier
predictions), weighted MAE on steps with enough requests. Scored exactly like dyn_linear.py.
"""
import json, random, sys, time
import numpy as np
import torch, torch.nn as nn

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from dyn_linear import load, graph, deviations, ROLES, ACTIONS

H = 12


def prep(ep):
    S, callees, callers, role = graph(ep)
    D, W = deviations(ep); ka = ep["k_action"]; K = ep["K"]
    def at(name, s, default, tf=lambda v: v):
        v = ep[name][s][ka] if ka < len(ep[name][s]) else None
        return tf(v) if v is not None else default
    a = [1.0 if ep["action"]["type"] == x else 0.0 for x in ACTIONS]
    X = []
    for i, s in enumerate(S):
        X.append([np.nan_to_num(D[i, ka]), at("err", s, 0.0), at("p95r", s, 0.0, lambda v: float(np.log(max(v, 1e-3)))),
                  at("rpsr", s, 0.0, lambda v: float(np.log(max(v, 1e-3)))), at("ready", s, 1.0), at("thr", s, 0.0)]
                 + [1.0 if role[i] == r else 0.0 for r in ROLES] + a)
    src = [j for i in range(len(S)) for j in callees[i]]; dst = [i for i in range(len(S)) for j in callees[i]]
    steps = list(range(ka + 1, K))
    Y = np.nan_to_num(D[:, ka + 1:]); M = (~np.isnan(D[:, ka + 1:])) & (W[:, ka + 1:] >= 1)
    Wt = np.sqrt(W[:, ka + 1:]) * M
    return (torch.tensor(X, dtype=torch.float32), torch.tensor(src, dtype=torch.long), torch.tensor(dst, dtype=torch.long),
            torch.tensor(np.nan_to_num(D[:, ka]), dtype=torch.float32), torch.tensor(Y, dtype=torch.float32),
            torch.tensor(Wt, dtype=torch.float32), len(steps), D, W)


class Dyn(nn.Module):
    def __init__(self, d_in, h=48):
        super().__init__()
        self.enc = nn.Sequential(nn.Linear(d_in, h), nn.ReLU(), nn.Linear(h, h), nn.ReLU())
        self.msg_dn = nn.Sequential(nn.Linear(h + 1, h), nn.ReLU())
        self.msg_up = nn.Sequential(nn.Linear(h + 1, h), nn.ReLU())
        self.step = nn.Sequential(nn.Linear(3 * h + 2 + H + 1, h), nn.ReLU(), nn.Linear(h, 1))

    def forward(self, X, src, dst, d0, n_steps):
        h = self.enc(X); n = h.shape[0]; d = d0.clone(); out = []
        def mean_agg(vals, frm, to):
            s = torch.zeros(n, vals.shape[1]).index_add_(0, to, vals[frm])
            c = torch.zeros(n).index_add_(0, to, torch.ones(len(to))).clamp(min=1).unsqueeze(1)
            return s / c
        for k in range(n_steps):
            z = torch.cat([h, d.unsqueeze(1)], 1)
            m_dn = mean_agg(self.msg_dn(z), dst, src)       # i (caller) hears from the services it calls
            m_up = mean_agg(self.msg_up(z), src, dst)       # i (callee) hears from its callers
            lag = torch.zeros(n, H + 1); lag[:, min(k + 1, H)] = 1
            d = d + self.step(torch.cat([h, m_dn, m_up, d.unsqueeze(1), d0.unsqueeze(1), lag], 1)).squeeze(1)
            out.append(d)
        return torch.stack(out, 1)


def evaluate(model, data, min_n):
    tot = {"model": [0.0, 0, 0.0, 0], "persistence": [0.0, 0, 0.0, 0]}; cost = 0.0
    blk = lambda arr: max(np.mean(arr[j:j + 2]) for j in range(0, len(arr) - 1, 2)) if len(arr) >= 2 else arr[0]
    model.eval()
    with torch.no_grad():
        for X, s, d_, d0, Y, Wt, T, D, W in data:
            t = time.perf_counter(); P = model(X, s, d_, d0, T).numpy(); cost += time.perf_counter() - t
            ka = D.shape[1] - T - 1
            for i in range(D.shape[0]):
                ks = [k for k in range(T) if W[i, ka + 1 + k] >= min_n and not np.isnan(D[i, ka + 1 + k])]
                if len(ks) < 3:
                    continue
                act = [D[i, ka + 1 + k] for k in ks]
                for name, pr in (("model", [P[i, k] for k in ks]), ("persistence", [float(d0[i])] * len(ks))):
                    o = tot[name]; o[0] += sum(abs(a - b) for a, b in zip(pr, act)); o[1] += len(ks)
                    o[2] += abs(blk(pr) - blk(act)); o[3] += 1
    return {k: (100 * v[0] / max(v[1], 1), 100 * v[2] / max(v[3], 1)) for k, v in tot.items()}, cost / max(len(data), 1)


def chain_eval(model, eps, data, min_n=5, thr=0.05):
    """T12: blast radius from PREDICTIONS vs the measured one. A service is hit when its bad share rises
    >= thr above its level at the action for two consecutive 15 s steps; onset = first such step.
    Compared with the dependency-map rule (every caller within 2 hops of the target is hit)."""
    from dyn_linear import graph
    tot = {"ARC": [0, 0, 0], "dependency map": [0, 0, 0]}; rhos = []
    model.eval()
    with torch.no_grad():
        for ep, (X, s, d_, d0, Y, Wt, T, D, W) in zip(eps, data):
            if ep["action"]["type"] == "noop":
                continue
            P = model(X, s, d_, d0, T).numpy(); ka = D.shape[1] - T - 1
            S, callees, callers, role = graph(ep)
            def onset(curve, base):
                for k in range(T - 1):
                    if curve[k] - base >= thr and curve[k + 1] - base >= thr:
                        return k
                return None
            act_on, pred_on = {}, {}
            for i in range(len(S)):
                ks = [k for k in range(T) if W[i, ka + 1 + k] >= min_n and not np.isnan(D[i, ka + 1 + k])]
                if len(ks) < T // 2:
                    continue                     # too little traffic to judge this service
                a = onset([np.nan_to_num(D[i, ka + 1 + k]) for k in range(T)], float(d0[i]))
                p = onset(list(P[i]), float(d0[i]))
                act_on[i], pred_on[i] = a, p
            for name, pred in (("ARC", {i: v is not None for i, v in pred_on.items()}),
                               ("dependency map", {i: role[i] in ("up1", "up2+") for i in act_on})):
                for i, a in act_on.items():
                    h, ph = a is not None, pred[i]
                    tot[name][0] += h and ph; tot[name][1] += (not h) and ph; tot[name][2] += h and (not ph)
            both = [i for i in act_on if act_on[i] is not None and pred_on[i] is not None]
            if len(both) >= 3:
                from baselines import spearman
                r = spearman([pred_on[i] for i in both], [act_on[i] for i in both])
                if r is not None:
                    rhos.append(r)
    for name, (tp, fp, fn) in tot.items():
        pr, rc = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
        print(f"    predicted chain, {name:15s}: services hit precision {pr:.2f}, recall {rc:.2f}, F1 {2 * pr * rc / max(pr + rc, 1e-9):.2f}")
    print(f"    onset ORDER, ARC vs measured: Spearman {np.mean(rhos) if rhos else float('nan'):.2f} over {len(rhos)} episodes with >= 3 services hit in both")


def main(args):
    eps = load(args[0])
    seeds = int(args[args.index("--seeds") + 1]) if "--seeds" in args else 3
    epochs = int(args[args.index("--epochs") + 1]) if "--epochs" in args else 60
    min_n = int(args[args.index("--min-n") + 1]) if "--min-n" in args else 10
    train = [e for e in eps if e["split"] == "train"]
    test = load(args[args.index("--test") + 1]) if "--test" in args else [e for e in eps if e["split"] == "test"]
    blocks = sorted({(e["plan"], e["block"]) for e in train}); vb = set(blocks[int(0.85 * len(blocks)):])
    tr = [prep(e) for e in train if (e["plan"], e["block"]) not in vb]
    va = [prep(e) for e in train if (e["plan"], e["block"]) in vb]
    te = [prep(e) for e in test]
    res = []
    for seed in range(seeds):
        torch.manual_seed(seed); random.seed(seed)
        model = Dyn(tr[0][0].shape[1]); opt = torch.optim.Adam(model.parameters(), lr=1e-3)
        best, state, bad = 1e9, None, 0
        for ep_i in range(epochs):
            model.train(); random.shuffle(tr)
            for X, s, d_, d0, Y, Wt, T, D, W in tr:
                if Wt.sum() == 0:
                    continue
                P = model(X, s, d_, d0, T)
                loss = ((P - Y).abs() * Wt).sum() / Wt.sum()
                opt.zero_grad(); loss.backward(); nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step()
            v = evaluate(model, va, min_n)[0]["model"][0]
            if v < best - 1e-3:
                best, state, bad = v, {k: t.clone() for k, t in model.state_dict().items()}, 0
            else:
                bad += 1
                if bad >= 8:
                    break
        model.load_state_dict(state)
        r, cost = evaluate(model, te, min_n); res.append(r)
        if "--chain" in args and seed == seeds - 1:
            chain_eval(model, test, te)
        print(f"  seed {seed}: epoch {ep_i + 1}, validation step MAE {best:.2f} -> test step MAE {r['model'][0]:.2f}, "
              f"peak error {r['model'][1]:.2f} (persistence {r['persistence'][0]:.2f} / {r['persistence'][1]:.2f}); "
              f"{1000 * cost:.1f} ms per rollout", flush=True)
    m = np.mean([[r["model"][0], r["model"][1]] for r in res], 0); sd = np.std([[r["model"][0], r["model"][1]] for r in res], 0)
    print(f"dynamic GNN over {seeds} seeds: step MAE {m[0]:.2f} ± {sd[0]:.2f}, peak error {m[1]:.2f} ± {sd[1]:.2f}  "
          f"(persistence {res[0]['persistence'][0]:.2f} / {res[0]['persistence'][1]:.2f}; {len(tr)} train, {len(te)} test)")


if __name__ == "__main__":
    main(sys.argv[1:])
