#!/usr/bin/env python3
"""Does ARC choose the right action? Net-effect prediction and action ranking.

  action_rank.py DATASET.jsonl [--test OTHER.jsonl] [--seeds 3]

Net effect of an episode = the sum over services (with >= 30 requests before and after) of y_mean, the
SIGNED change of the bad-request share over the 3 minutes after the action: harm counts positive,
improvement negative. Lower is better.

The model is the action-conditioned GNN (train_gnn.py, latency inputs off) trained on y_mean (signed).
Ranking test (the counterfactual problem: each episode shows only ONE action's outcome): take pairs of
test episodes with the SAME fault type and the SAME fault target but DIFFERENT actions, i.e. the same kind
of incident handled two ways. A predictor is right on a pair if it orders the two net effects as observed
(ties in the observed net effect, |difference| < 2 points, are skipped).
  B1 action mean   the training mean net effect of each action type (knows nothing about the incident)
  ARC              the GNN, given the state before the action and the action
Also: for every test episode, ARC scores all six action types on that episode's own state (same action
target) and the time this takes is reported, i.e. what an agent would wait for.
"""
import json, random, sys, time
from collections import defaultdict
import torch

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import train_gnn as T
from baselines import load, MIN_N

T.DROP.add("latency")


def scored_idx(ep):
    return [i for i, n in enumerate(ep["nodes"])
            if n["y"].get("y_mean") is not None and (n["y"].get("n_before") or 0) >= MIN_N and (n["y"].get("n_after") or 0) >= MIN_N]


def net_actual(ep):
    return sum(ep["nodes"][i]["y"]["y_mean"] for i in scored_idx(ep))


def train_model(train, seed):
    torch.manual_seed(seed); random.seed(seed)
    blocks = sorted({(e["plan"], e["block"]) for e in train}); vb = set(blocks[int(0.85 * len(blocks)):])
    tr = [e for e in train if (e["plan"], e["block"]) not in vb]; va = [e for e in train if (e["plan"], e["block"]) in vb]
    D = {id(e): T.tensors(e, "y_mean") for e in train}
    model = T.GNN(len(T.FEATS) + len(T.ROLES) + len(T.ACTIONS))
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    best, state, bad = 1e9, None, 0
    for _ in range(300):
        model.train(); random.shuffle(tr)
        for e in tr:
            X, Y, M, s, d = D[id(e)]
            if M.sum() == 0:
                continue
            loss = ((model(X, s, d) - Y).abs() * M).sum() / M.sum()
            opt.zero_grad(); loss.backward(); opt.step()
        v = T.evaluate(model, va, [D[id(e)] for e in va], "y_mean")[0]
        if v < best - 1e-4:
            best, state, bad = v, {k: t.clone() for k, t in model.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= 25:
                break
    model.load_state_dict(state); model.eval()
    return model


def net_pred(model, ep, action=None):
    e = ep if action is None else dict(ep, action=dict(ep["action"], type=action))
    X, Y, M, s, d = T.tensors(e, "y_mean")
    with torch.no_grad():
        p = model(X, s, d)
    return float(sum(p[i] for i in scored_idx(ep)))


def main(args):
    eps = load(args[0]); seeds = int(args[args.index("--seeds") + 1]) if "--seeds" in args else 3
    if "--fold" in args:        # 5-fold cross-validation by block
        k = int(args[args.index("--fold") + 1])
        for e in eps:
            e["split"] = "test" if e["block"] % 5 == k else "train"
    if "--train-plans" in args:
        keep = set(args[args.index("--train-plans") + 1].split(","))
        eps = [e for e in eps if e["split"] == "test" or e["plan"] in keep]
    train = [e for e in eps if e["split"] == "train"]
    test = load(args[args.index("--test") + 1]) if "--test" in args else [e for e in eps if e["split"] == "test"]
    act_mean = defaultdict(list)
    for e in train:
        act_mean[e["action"]["type"]].append(net_actual(e))
    act_mean = {a: sum(v) / len(v) for a, v in act_mean.items()}
    groups = defaultdict(list)
    for e in test:
        if scored_idx(e):
            groups[(e["fault"]["type"], e["fault"]["target"])].append(e)
    pairs = [(a, b) for g in groups.values() for i, a in enumerate(g) for b in g[i + 1:]
             if a["action"]["type"] != b["action"]["type"] and abs(net_actual(a) - net_actual(b)) >= 0.02]
    print(f"{len(test)} test episodes, {len(groups)} incident kinds (fault type x fault target), {len(pairs)} pairs with different actions")
    base_right = sum((act_mean.get(a["action"]["type"], 0) < act_mean.get(b["action"]["type"], 0)) == (net_actual(a) < net_actual(b)) for a, b in pairs)
    print(f"  B1 action mean (ignores the incident): {100 * base_right / max(len(pairs), 1):.1f} % of pairs ordered right")
    accs = []
    for seed in range(seeds):
        model = train_model(train, seed)
        cache = {id(e): net_pred(model, e) for e in test}
        right = sum((cache[id(a)] < cache[id(b)]) == (net_actual(a) < net_actual(b)) for a, b in pairs)
        accs.append(right / max(len(pairs), 1))
        t = time.perf_counter(); n = 0
        for e in test[:100]:
            for a in T.ACTIONS:
                net_pred(model, e, a); n += 1
        per = (time.perf_counter() - t) / max(n, 1)
        mae = sum(abs(cache[id(e)] - net_actual(e)) for e in test) / len(test)
        print(f"  ARC seed {seed}: {100 * accs[-1]:.1f} % of pairs ordered right; net-effect MAE {100 * mae:.1f} points; "
              f"scoring one candidate action {1000 * per:.2f} ms, all six {6000 * per:.1f} ms", flush=True)
        # T9 hard pairs: the two action types have similar average effects (training means within 5
        # points), so knowing the action type alone is close to a coin flip
        hard = [(a, b) for a, b in pairs if abs(act_mean.get(a["action"]["type"], 0) - act_mean.get(b["action"]["type"], 0)) < 0.05]
        hb = sum((act_mean.get(a["action"]["type"], 0) < act_mean.get(b["action"]["type"], 0)) == (net_actual(a) < net_actual(b)) for a, b in hard)
        ha = sum((cache[id(a)] < cache[id(b)]) == (net_actual(a) < net_actual(b)) for a, b in hard)
        print(f"    hard pairs ({len(hard)}): action-mean {100 * hb / max(len(hard), 1):.1f} %, ARC {100 * ha / max(len(hard), 1):.1f} %")
        # bootstrap 95 % interval of ARC's pair accuracy and of its lead over the action-mean baseline,
        # resampling incident kinds (pairs within a kind are not independent)
        rng = random.Random(seed); kinds = list(groups)
        kind_of = lambda e: (e["fault"]["type"], e["fault"]["target"])
        byk = defaultdict(list)
        for a, b in pairs:
            byk[kind_of(a)].append(((cache[id(a)] < cache[id(b)]) == (net_actual(a) < net_actual(b)),
                                    (act_mean.get(a["action"]["type"], 0) < act_mean.get(b["action"]["type"], 0)) == (net_actual(a) < net_actual(b))))
        accb, leadb = [], []
        for _ in range(1000):
            smp = [x for k in (rng.choice(kinds) for _ in kinds) for x in byk.get(k, [])]
            if smp:
                accb.append(sum(x for x, _ in smp) / len(smp)); leadb.append((sum(x for x, _ in smp) - sum(y for _, y in smp)) / len(smp))
        accb.sort(); leadb.sort()
        print(f"    95 % interval: ARC accuracy {100 * accb[25]:.1f}-{100 * accb[974]:.1f} %; lead over action-mean "
              f"{100 * leadb[25]:+.1f} to {100 * leadb[974]:+.1f} points ({100 * sum(l <= 0 for l in leadb) / len(leadb):.1f} % of resamples <= 0)")
        # T11 damage-control gate: an action is HARMFUL if its observed net effect is >= 20 points; ARC blocks
        # it if its predicted net effect is >= a threshold. Compared with blocking by action type.
        harmful = [net_actual(e) >= 0.20 for e in test if scored_idx(e)]
        evs = [e for e in test if scored_idx(e)]
        print(f"    gate: {sum(harmful)} harmful of {len(harmful)} actions (net effect >= 20 points)")
        for thr in (0.05, 0.10, 0.20, 0.40):
            for name, f in (("ARC", lambda e: cache[id(e)]), ("action-mean", lambda e: act_mean.get(e["action"]["type"], 0))):
                block = [f(e) >= thr for e in evs]
                caught = sum(b and h for b, h in zip(block, harmful)) / max(sum(harmful), 1)
                wrong = sum(b and not h for b, h in zip(block, harmful)) / max(len(harmful) - sum(harmful), 1)
                print(f"      block if predicted >= {int(100 * thr):2d} pts  {name:12s} catches {100 * caught:5.1f} % of harmful, "
                      f"wrongly blocks {100 * wrong:5.1f} % of safe")
    m = sum(accs) / len(accs); sd = (sum((a - m) ** 2 for a in accs) / max(len(accs) - 1, 1)) ** 0.5
    print(f"ARC over {seeds} seeds: {100 * m:.1f} ± {100 * sd:.1f} % of pairs ordered right (action-mean baseline "
          f"{100 * base_right / max(len(pairs), 1):.1f} %, coin flip 50 %)")


if __name__ == "__main__":
    main(sys.argv[1:])
