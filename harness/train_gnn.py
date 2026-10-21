#!/usr/bin/env python3
"""First action-conditioned graph model for ARC: predict each service's damage from the system state
before the action and the action itself. Plain PyTorch (no graph library needed).

  train_gnn.py DATASET.jsonl [--target y_peak] [--seeds 3] [--epochs 300]

Model: each service starts from its own features (build_dataset.py "x"), its role relative to the
action target (target / caller 1 hop / caller 2+ hops / callee / unrelated), and the action type.
Three rounds of message passing along the call graph, with separate weights for "from my callers" and
"from my callees" (damage can travel both ways), then a small head predicts the damage per service.
Trained on the train split with L1 loss on services with >= 30 requests; the last 15 % of training
blocks is held out for early stopping. Scored exactly like baselines.py on the test split.
"""
import json, random, sys
import torch, torch.nn as nn

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from baselines import roles, scored, spearman, MIN_N, load, fit

FEATS = ["rps_ratio", "err_share", "p50_ratio", "p95_ratio", "p99_ratio", "cpu_use_frac", "throttled",
         "mem_ratio", "not_ready", "bad_before", "is_action_target"]
RATIO = {"rps_ratio", "p50_ratio", "p95_ratio", "p99_ratio", "mem_ratio"}
ROLES = ["target", "up1", "up2+", "down", "other", "no-target"]
ACTIONS = ["noop", "restart-pod", "rollout-restart", "scale-up", "cpu-bump", "drain"]


DROP = set()          # feature groups switched off for the ablation (--drop)
GROUPS = {"state": set(FEATS) - {"is_action_target"}, "bad_before": {"bad_before"}, "latency": {"p50_ratio", "p95_ratio", "p99_ratio"},
          "role": set(), "action": set(), "graph": set()}


def tensors(ep, key):
    r = roles(ep)
    names = [n["service"] for n in ep["nodes"]]
    idx = {s: i for i, s in enumerate(names)}
    a = [1.0 if ep["action"]["type"] == x else 0.0 for x in ACTIONS]
    X, Y, M = [], [], []
    for n in ep["nodes"]:
        v = []
        for k in FEATS:
            x = n["x"].get(k)
            if x is None:
                x = 1.0 if k in RATIO else 0.0
            if k in RATIO:
                x = torch.log(torch.tensor(max(x, 1e-3))).item()   # ratios on a log scale: 2x and 0.5x symmetric
            v.append(0.0 if any(k in GROUPS[g] for g in DROP) else x)
        v += [0.0 if "role" in DROP else (1.0 if r[n["service"]] == x else 0.0) for x in ROLES]
        v += [0.0] * len(a) if "action" in DROP else a
        X.append(v)
        y = n["y"].get(key)
        ok = y is not None and (n["y"].get("n_before") or 0) >= MIN_N and (n["y"].get("n_after") or 0) >= MIN_N
        Y.append(y if ok else 0.0); M.append(1.0 if ok else 0.0)
    if "graph" in DROP:
        ep = dict(ep, edges=[])
    src = [idx[e["src"]] for e in ep["edges"] if e["src"] in idx and e["dst"] in idx]
    dst = [idx[e["dst"]] for e in ep["edges"] if e["src"] in idx and e["dst"] in idx]
    return (torch.tensor(X), torch.tensor(Y), torch.tensor(M),
            torch.tensor(src, dtype=torch.long), torch.tensor(dst, dtype=torch.long))


class GNN(nn.Module):
    def __init__(self, d_in, h=64, layers=3):
        super().__init__()
        self.inp = nn.Sequential(nn.Linear(d_in, h), nn.ReLU())
        self.self_ = nn.ModuleList(nn.Linear(h, h) for _ in range(layers))
        self.from_callers = nn.ModuleList(nn.Linear(h, h) for _ in range(layers))
        self.from_callees = nn.ModuleList(nn.Linear(h, h) for _ in range(layers))
        self.head = nn.Sequential(nn.Linear(h, h), nn.ReLU(), nn.Linear(h, 1))

    def forward(self, X, src, dst):
        h = self.inp(X)
        n = h.shape[0]
        for s, fc, fe in zip(self.self_, self.from_callers, self.from_callees):
            def agg(frm, to):       # mean of neighbours' states
                out = torch.zeros_like(h).index_add_(0, to, h[frm])
                cnt = torch.zeros(n).index_add_(0, to, torch.ones(len(to))).clamp(min=1).unsqueeze(1)
                return out / cnt
            h = torch.relu(s(h) + fc(agg(src, dst)) + fe(agg(dst, src))) + h
        return self.head(h).squeeze(1)


def evaluate(model, eps, data, key):
    err, cnt, rhos, hits, n_eps = 0.0, 0, [], 0, 0
    model.eval()
    with torch.no_grad():
        for ep, (X, Y, M, s, d) in zip(eps, data):
            p = model(X, s, d)
            ys = [Y[i].item() for i in range(len(Y)) if M[i] > 0]; ps = [p[i].item() for i in range(len(Y)) if M[i] > 0]
            err += sum(abs(a - b) for a, b in zip(ys, ps)); cnt += len(ys)
            if len(ys) >= 3:
                rho = spearman(ps, ys)
                if rho is not None:
                    rhos.append(rho)
                if max(ys) > 0.05:
                    n_eps += 1; hits += ys.index(max(ys)) == ps.index(max(ps))
    return 100 * err / max(cnt, 1), sum(rhos) / max(len(rhos), 1), hits / max(n_eps, 1)


def main(args):
    path = args[0]
    key = args[args.index("--target") + 1] if "--target" in args else "y_peak"
    seeds = int(args[args.index("--seeds") + 1]) if "--seeds" in args else 3
    epochs = int(args[args.index("--epochs") + 1]) if "--epochs" in args else 300
    if "--drop" in args:
        DROP.update(args[args.index("--drop") + 1].split(","))
        print("ablation: inputs switched off:", sorted(DROP))
    eps = load(path)
    train = [e for e in eps if e["split"] == "train"]; test = [e for e in eps if e["split"] == "test"]
    if "--test" in args:        # unseen-system test: train on this file's train split, test on ALL of another
        test = load(args[args.index("--test") + 1])
    blocks = sorted({(e["plan"], e["block"]) for e in train})
    val_b = set(blocks[int(0.85 * len(blocks)):])
    tr = [e for e in train if (e["plan"], e["block"]) not in val_b]; va = [e for e in train if (e["plan"], e["block"]) in val_b]
    D = {id(e): tensors(e, key) for e in eps + [t for t in test if t not in eps]}
    res = []
    for seed in range(seeds):
        torch.manual_seed(seed); random.seed(seed)
        model = GNN(len(FEATS) + len(ROLES) + len(ACTIONS))
        opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
        best, best_state, patience = 1e9, None, 0
        for ep_i in range(epochs):
            model.train(); random.shuffle(tr)
            for e in tr:
                X, Y, M, s, d = D[id(e)]
                if M.sum() == 0:
                    continue
                loss = ((model(X, s, d) - Y).abs() * M).sum() / M.sum()
                opt.zero_grad(); loss.backward(); opt.step()
            v = evaluate(model, va, [D[id(e)] for e in va], key)[0]
            if v < best - 1e-4:
                best, best_state, patience = v, {k: t.clone() for k, t in model.state_dict().items()}, 0
            else:
                patience += 1
                if patience >= 25:
                    break
        model.load_state_dict(best_state)
        r = evaluate(model, test, [D[id(e)] for e in test], key)
        res.append(r)
        print(f"  seed {seed}: stopped at epoch {ep_i + 1}, validation MAE {best:.2f} -> test MAE {r[0]:.2f}, Spearman {r[1]:.3f}, top-1 {r[2]:.2f}", flush=True)
    m = [sum(x[i] for x in res) / len(res) for i in range(3)]
    sd = [(sum((x[i] - m[i]) ** 2 for x in res) / max(len(res) - 1, 1)) ** 0.5 for i in range(3)]
    print(f"GNN over {seeds} seeds, target {key}: MAE {m[0]:.2f} ± {sd[0]:.2f}, Spearman {m[1]:.3f} ± {sd[1]:.3f}, "
          f"top-1 {m[2]:.2f} ± {sd[2]:.2f}   ({len(tr)} train, {len(va)} validation, {len(test)} test episodes)")


if __name__ == "__main__":
    main(sys.argv[1:])
