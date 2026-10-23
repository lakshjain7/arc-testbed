#!/usr/bin/env python3
"""ARC as one tool an agent calls before acting.

  arc_tool.py train DATASET.jsonl MODEL_DIR [--seeds 5]       train and save everything ARC needs
  arc_tool.py check MODEL_DIR EPISODES.jsonl [--n 3]          demo: run check() on the first n episodes

check(state, action) -> {
  "decision": "block" | "ask" | "allow",       block if the predicted net harm >= BLOCK_PTS, ask a human if the
                                               seeds disagree (spread >= the saved threshold), else allow
  "net_harm_pts", "spread_pts",                predicted net effect of this action (harm positive) and disagreement
  "services": [{service, role, damage_pts}],   predicted damage per service (y_peak), worst first;
                                               0.9 x graph model + 0.1 x trees (decision log 10f)
  "chain": ["target -> caller -> ..."],        how the worst-hit services are reached from the action target
  "safest_action", "candidates": {action: net_harm_pts},   all six action types scored on the same state
  "ms": time taken }
state = one episode record as built by build_dataset.py (nodes with "x", edges, action); "y" is not used.
"""
import json, os, pickle, random, sys, time
from collections import deque
import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import train_gnn as T
import action_rank as A
from baselines import load, roles

BLOCK_PTS = 20.0
W_TREE = 0.1
FE = ["rps_ratio", "err_share", "cpu_use_frac", "throttled", "mem_ratio", "not_ready", "bad_before", "is_action_target"]
RO = ["target", "up1", "up2+", "down", "other", "no-target"]


def tree_feats(ep):
    r = roles(ep)
    return [[n["x"].get(k) if n["x"].get(k) is not None else (1.0 if k.endswith("ratio") else 0.0) for k in FE]
            + [1.0 if r[n["service"]] == x else 0.0 for x in RO] + [1.0 if ep["action"]["type"] == x else 0.0 for x in T.ACTIONS]
            for n in ep["nodes"]]


def train_damage(train, seed):
    torch.manual_seed(seed); random.seed(seed)
    blocks = sorted({(e["plan"], e["block"]) for e in train}); vb = set(blocks[int(0.85 * len(blocks)):])
    tr = [T.tensors(e, "y_peak") for e in train if (e["plan"], e["block"]) not in vb]
    va_e = [e for e in train if (e["plan"], e["block"]) in vb]; va = [T.tensors(e, "y_peak") for e in va_e]
    m = T.GNN(len(T.FEATS) + len(T.ROLES) + len(T.ACTIONS)); opt = torch.optim.Adam(m.parameters(), lr=1e-3, weight_decay=1e-4)
    best, state, bad = 1e9, None, 0
    for _ in range(300):
        m.train(); random.shuffle(tr)
        for X, Y, M, s, d in tr:
            if M.sum() == 0:
                continue
            loss = ((m(X, s, d) - Y).abs() * M).sum() / M.sum(); opt.zero_grad(); loss.backward(); opt.step()
        v = T.evaluate(m, va_e, va, "y_peak")[0]
        if v < best - 1e-4:
            best, state, bad = v, {k: t.clone() for k, t in m.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= 25:
                break
    m.load_state_dict(state); m.eval()
    return m


def train(path, out, seeds):
    from sklearn.ensemble import GradientBoostingRegressor
    eps = load(path); train = [e for e in eps if e["split"] == "train"]
    os.makedirs(out, exist_ok=True)
    for s in range(seeds):
        torch.save(train_damage(train, s).state_dict(), os.path.join(out, f"damage_{s}.pt"))
        torch.save(A.train_model(train, s).state_dict(), os.path.join(out, f"net_{s}.pt"))
        print(f"  seed {s} saved", flush=True)
    X, Y = [], []
    for e in train:
        for f, n in zip(tree_feats(e), e["nodes"]):
            y = n["y"].get("y_peak")
            if y is not None and (n["y"].get("n_before") or 0) >= A.MIN_N and (n["y"].get("n_after") or 0) >= A.MIN_N:
                X.append(f); Y.append(y)
    gbr = GradientBoostingRegressor(loss="absolute_error", n_estimators=300, max_depth=3, learning_rate=0.05, random_state=0).fit(X, Y)
    pickle.dump(gbr, open(os.path.join(out, "trees.pkl"), "wb"))
    # ask threshold: 90th percentile of the seeds' spread on the training actions that would not be blocked
    arc = ARC(out)
    sp = [arc._net(e)[1] for e in train if A.scored_idx(e)]
    json.dump({"seeds": seeds, "ask_spread_pts": float(np.quantile(sp, 0.9)), "trained_on": os.path.basename(path)},
              open(os.path.join(out, "config.json"), "w"))
    print(f"saved to {out}")


class ARC:
    def __init__(self, d):
        self.d = d; cfg = os.path.join(d, "config.json")
        self.cfg = json.load(open(cfg)) if os.path.exists(cfg) else {"ask_spread_pts": float("inf")}
        k = len([f for f in os.listdir(d) if f.startswith("damage_")])
        mk = lambda f: (lambda m: (m.load_state_dict(torch.load(os.path.join(d, f))), m.eval(), m)[2])(
            T.GNN(len(T.FEATS) + len(T.ROLES) + len(T.ACTIONS)))
        self.dmg = [mk(f"damage_{s}.pt") for s in range(k)]; self.net = [mk(f"net_{s}.pt") for s in range(k)]
        self.trees = pickle.load(open(os.path.join(d, "trees.pkl"), "rb")) if os.path.exists(os.path.join(d, "trees.pkl")) else None

    def _net(self, ep):
        v = [A.net_pred(m, ep) * 100 for m in self.net]
        return float(np.mean(v)), float(np.std(v))

    def check(self, ep):
        t0 = time.perf_counter()
        X, _, _, s, d = T.tensors(ep, "y_peak")
        with torch.no_grad():
            g = torch.stack([m(X, s, d) for m in self.dmg]).mean(0).numpy()
        dmg = (1 - W_TREE) * g + W_TREE * self.trees.predict(tree_feats(ep)) if self.trees is not None else g
        net, spread = self._net(ep)
        cands = {a: self._net(dict(ep, action=dict(ep["action"], type=a)))[0] for a in T.ACTIONS}
        decision = "block" if net >= BLOCK_PTS else ("ask" if spread >= self.cfg["ask_spread_pts"] else "allow")
        r = roles(ep)
        svc = sorted(({"service": n["service"], "role": r[n["service"]], "damage_pts": round(100 * float(v), 1)}
                      for n, v in zip(ep["nodes"], dmg)), key=lambda x: -x["damage_pts"])
        return {"decision": decision, "net_harm_pts": round(net, 1), "spread_pts": round(spread, 1),
                "services": svc, "chain": self._chain(ep, [x["service"] for x in svc if x["damage_pts"] >= 5][:4]),
                "safest_action": min(cands, key=cands.get), "candidates": {a: round(v, 1) for a, v in cands.items()},
                "ms": round(1000 * (time.perf_counter() - t0), 1)}

    @staticmethod
    def _chain(ep, hit):
        """Shortest call path (either direction) from the action target to each hit service."""
        tgt = ep["action"]["target"]
        if not tgt:
            return []
        nb = {}
        for e in ep["edges"]:
            nb.setdefault(e["src"], []).append((e["dst"], "calls")); nb.setdefault(e["dst"], []).append((e["src"], "is called by"))
        prev = {tgt: None}; q = deque([tgt])
        while q:
            u = q.popleft()
            for v, how in nb.get(u, []):
                if v not in prev:
                    prev[v] = (u, how); q.append(v)
        out = []
        for h in hit:
            if h == tgt:
                out.append(f"{h} (the action target)"); continue
            if h not in prev:
                out.append(f"{h} (not connected to the target by calls seen before the action)"); continue
            path, v = [], h
            while prev[v]:
                u, how = prev[v]; path.append(f"{u} {how} {v}"); v = u
            out.append("; ".join(reversed(path)))
        return out


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "train":
        train(a[1], a[2], int(a[a.index("--seeds") + 1]) if "--seeds" in a else 5)
    else:
        arc = ARC(a[1]); n = int(a[a.index("--n") + 1]) if "--n" in a else 3
        for ep in load(a[2])[:n]:
            r = arc.check(ep)
            print(f"\n{ep['episode_id']}: {ep['action']['type']} on {ep['action']['target']} (fault {ep['fault']['type']} on {ep['fault']['target']})")
            print(json.dumps({k: (v[:5] if k == "services" else v) for k, v in r.items()}, indent=1))
