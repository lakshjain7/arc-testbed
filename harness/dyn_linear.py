#!/usr/bin/env python3
"""ARC dynamic model, linear version: how each service's badness moves step by step after an action.

  dyn_linear.py TRAJ.jsonl [--test OTHER_TRAJ.jsonl] [--min-n 10]

State: d_i(k) = bad_i(k) - bad_i(normal), the deviation of service i's bad-request share from its own
healthy level (B0), on 15 s steps. The model, fitted by weighted least squares:

  d_i(k+1) = a * d_i(k)                                own memory (does trouble persist?)
           + w_down * mean_{j called by i} d_j(k)      trouble arriving from the services i calls
           + w_up   * mean_{j calling i}   d_j(k)      trouble arriving from the services that call i
           + g * d_i(k_action)                         the trouble present at the action keeps pushing (the fault
                                                       is still there unless the action removes it)
           + u[action, role_i, k - k_action]           the action's own push on i, per step after it
  role_i = the service's position relative to the action target: target / caller 1 hop / caller 2+ hops /
           callee / other. u is the action's "impulse response": learned per action type and role.
Steps with no requests (for example a drained service) are skipped in the fit and treated as unknown
(0) when they appear as a neighbour. Each transition is weighted by sqrt(requests), since quiet
services are noisy.

Evaluated by ROLLING OUT from the action (only the state at the action is given; every later step is
predicted from the model's own previous prediction), against:
  persistence  d stays at its value at the action
  recovery     d returns to 0 at once
Scores on steps with >= --min-n requests: mean absolute error of the predicted bad share (points), and
the peak rise per service over the 3 minutes (same definition on predicted and actual curves).
Prediction cost: one rollout is a few hundred multiply-adds; it is printed at the end.
"""
import json, sys, time
import numpy as np

ROLES = ["target", "up1", "up2+", "down", "other", "no-target"]
ACTIONS = ["noop", "restart-pod", "rollout-restart", "scale-up", "cpu-bump", "drain"]
H = 12                     # action effect learned for 12 steps = 3 min


def load(p):
    return [json.loads(l) for l in open(p)]


def graph(ep):
    S = ep["services"]; idx = {s: i for i, s in enumerate(S)}
    callees = [[] for _ in S]; callers = [[] for _ in S]
    for a, b in ep["edges"]:
        if a in idx and b in idx and a != b:
            callees[idx[a]].append(idx[b]); callers[idx[b]].append(idx[a])
    tgt = ep["action"]["target"]
    role = []
    if tgt not in idx:
        role = ["no-target"] * len(S)
    else:
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
        up = dist(idx[tgt], callers); dn = dist(idx[tgt], callees)
        for i in range(len(S)):
            role.append("target" if i == idx[tgt] else ("up1" if up.get(i) == 1 else "up2+") if i in up
                        else "down" if i in dn else "other")
    return S, callees, callers, role


def deviations(ep):
    S = ep["services"]; K = ep["K"]; kb = ep["k_fault"]
    D = np.full((len(S), K), np.nan); W = np.zeros((len(S), K))
    for i, s in enumerate(S):
        b = ep["bad"][s]; n = ep["n"][s]
        base = [b[k] for k in range(min(kb, K)) if b[k] is not None and n[k] > 0]
        base = float(np.mean(base)) if base else 0.0
        for k in range(K):
            if b[k] is not None and n[k] > 0:
                D[i, k] = b[k] - base; W[i, k] = n[k]
    return D, W


def design(ep):
    """Rows of the regression: one per (service, step) transition at or after the fault."""
    S, callees, callers, role = graph(ep)
    D, W = deviations(ep)
    Z = np.nan_to_num(D)
    a_idx = ACTIONS.index(ep["action"]["type"]) if ep["action"]["type"] in ACTIONS else 0
    rows, ys, ws = [], [], []
    for k in range(ep["k_fault"], ep["K"] - 1):
        lag = k + 1 - ep["k_action"]
        for i in range(len(S)):
            if np.isnan(D[i, k + 1]):
                continue
            x = np.zeros(4 + len(ACTIONS) * len(ROLES) * (H + 1))
            x[0] = Z[i, k]
            x[1] = Z[callees[i], k].mean() if callees[i] else 0.0
            x[2] = Z[callers[i], k].mean() if callers[i] else 0.0
            x[3] = Z[i, ep["k_action"]] if k >= ep["k_action"] else 0.0   # the trouble present at the action (the fault keeps pushing)
            if 0 <= lag <= H:
                x[4 + (a_idx * len(ROLES) + ROLES.index(role[i])) * (H + 1) + lag] = 1.0
            rows.append(x); ys.append(D[i, k + 1]); ws.append(np.sqrt(W[i, k + 1]))
    return rows, ys, ws


def fit(eps):
    X, Y, Wt = [], [], []
    for ep in eps:
        r, y, w = design(ep); X += r; Y += y; Wt += w
    X, Y, Wt = np.array(X), np.array(Y), np.array(Wt)
    lam = 1e-2 * np.eye(X.shape[1]); lam[:4, :4] = 0          # small ridge on the action terms only
    A = (X * Wt[:, None] ** 2).T @ X + lam * (Wt ** 2).mean()
    return np.linalg.solve(A, (X * Wt[:, None] ** 2).T @ Y), len(Y)


def rollout(theta, ep, D0):
    """Predict d for every step after the action from the state at the action only."""
    S, callees, callers, role = graph(ep)
    a_idx = ACTIONS.index(ep["action"]["type"]) if ep["action"]["type"] in ACTIONS else 0
    K, ka = ep["K"], ep["k_action"]
    P = np.zeros((len(S), K)); P[:, ka] = D0
    for k in range(ka, K - 1):
        lag = k + 1 - ka
        for i in range(len(S)):
            v = theta[0] * P[i, k]
            v += theta[1] * (P[callees[i], k].mean() if callees[i] else 0.0)
            v += theta[2] * (P[callers[i], k].mean() if callers[i] else 0.0)
            v += theta[3] * D0[i]
            if lag <= H:
                v += theta[4 + (a_idx * len(ROLES) + ROLES.index(role[i])) * (H + 1) + lag]
            P[i, k + 1] = v
    return P


def score(theta, eps, min_n):
    out = {"model": [0.0, 0, 0.0, 0], "persistence": [0.0, 0, 0.0, 0], "recovery": [0.0, 0, 0.0, 0]}
    t_cost = 0.0
    for ep in eps:
        D, W = deviations(ep); ka = ep["k_action"]
        D0 = np.nan_to_num(D[:, ka])
        t = time.perf_counter(); P = rollout(theta, ep, D0); t_cost += time.perf_counter() - t
        preds = {"model": P, "persistence": np.repeat(D0[:, None], ep["K"], 1), "recovery": np.zeros_like(P)}
        for i in range(len(ep["services"])):
            ks = [k for k in range(ka + 1, ep["K"]) if W[i, k] >= min_n and not np.isnan(D[i, k])]
            if len(ks) < 3:
                continue
            for name, Pm in preds.items():
                o = out[name]
                o[0] += sum(abs(Pm[i, k] - D[i, k]) for k in ks); o[1] += len(ks)
                # peak rise over the window: max of 2-step (30 s) means, predicted vs actual
                blk = lambda arr: max(np.mean(arr[j:j + 2]) for j in range(0, len(arr) - 1, 2)) if len(arr) >= 2 else arr[0]
                o[2] += abs(blk([Pm[i, k] for k in ks]) - blk([D[i, k] for k in ks])); o[3] += 1
    return {k: (100 * v[0] / max(v[1], 1), 100 * v[2] / max(v[3], 1)) for k, v in out.items()}, t_cost / max(len(eps), 1)


def main(args):
    eps = load(args[0]); min_n = int(args[args.index("--min-n") + 1]) if "--min-n" in args else 10
    train = [e for e in eps if e["split"] == "train"]
    test = load(args[args.index("--test") + 1]) if "--test" in args else [e for e in eps if e["split"] == "test"]
    theta, n = fit(train)
    print(f"fitted on {len(train)} episodes ({n} transitions); tested on {len(test)} episodes")
    print(f"  own memory a = {theta[0]:.3f} | from callees w_down = {theta[1]:.3f} | from callers w_up = {theta[2]:.3f} | ongoing fault g = {theta[3]:.3f}")
    print("  action push on the TARGET in the first 4 steps after the action (points of bad share):")
    for a_i, a in enumerate(ACTIONS):
        base = 4 + (a_i * len(ROLES) + ROLES.index("target")) * (H + 1)
        print(f"    {a:16s} " + "  ".join(f"{100 * theta[base + l]:+6.1f}" for l in range(1, 5)))
    res, cost = score(theta, test, min_n)
    print(f"  rollout from the action, steps with >= {min_n} requests:")
    print(f"    {'predictor':12s} {'step MAE':>9s} {'peak error':>11s}   (points)")
    for k, (m, p) in res.items():
        print(f"    {k:12s} {m:9.2f} {p:11.2f}")
    print(f"  prediction cost: {1000 * cost:.2f} ms per episode (one action, 3 min ahead, plain Python)")


if __name__ == "__main__":
    main(sys.argv[1:])
