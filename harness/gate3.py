#!/usr/bin/env python3
"""Three-way damage-control gate: BLOCK / ASK A HUMAN / ALLOW.

  gate3.py DATASET.jsonl [--test OTHER.jsonl] [--seeds 5]

ARC (action_rank.py's net-effect model) is trained with several seeds. For each test action:
  mean  = the seeds' average predicted net effect (points; harm positive)
  sd    = their spread (disagreement)
  BLOCK if mean >= T;  else ASK if sd >= S;  else ALLOW
An action is HARMFUL if its observed net effect is >= 20 points (as in action_rank.py).
Reported for several T and S: harmful caught (blocked or asked), harmful let through, safe actions wrongly
blocked, and how often a human is asked. S = inf is the two-way gate of action_rank.py.
S is also chosen on the validation blocks (the smallest that asks about at most 10 % of actions).
"""
import random, sys
import numpy as np

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import action_rank as A
from baselines import load


def main(args):
    eps = load(args[0]); seeds = int(args[args.index("--seeds") + 1]) if "--seeds" in args else 5
    train = [e for e in eps if e["split"] == "train"]
    test = load(args[args.index("--test") + 1]) if "--test" in args else [e for e in eps if e["split"] == "test"]
    test = [e for e in test if A.scored_idx(e)]
    blocks = sorted({(e["plan"], e["block"]) for e in train}); vb = set(blocks[int(0.85 * len(blocks)):])
    val = [e for e in train if (e["plan"], e["block"]) in vb and A.scored_idx(e)]
    models = [A.train_model(train, s) for s in range(seeds)]
    pred = lambda es: np.array([[A.net_pred(m, e) for m in models] for e in es])
    P, V = pred(test), pred(val)
    harm = np.array([A.net_actual(e) >= 0.20 for e in test])
    mu, sd = P.mean(1), P.std(1)
    print(f"{len(test)} test actions, {harm.sum()} harmful (net effect >= 20 points); {seeds} seeds")
    for T in (0.10, 0.20, 0.40):
        # S chosen on validation: the smallest spread threshold that sends at most 10 % of non-blocked actions to a human
        vmu, vsd = V.mean(1), V.std(1)
        cand = sorted(vsd[vmu < T]); S_val = cand[int(0.9 * len(cand))] if cand else np.inf
        for S, name in ((np.inf, "never ask"), (S_val, "S from validation"), (np.quantile(sd, 0.8), "ask top 20 % spread")):
            block = mu >= T; ask = (~block) & (sd >= S); allow = ~block & ~ask
            print(f"  block >= {int(100 * T):2d} pts, {name:20s} (S={100 * S:5.1f}): harmful caught {100 * (harm & ~allow).sum() / max(harm.sum(), 1):5.1f} % "
                  f"(blocked {100 * (harm & block).sum() / max(harm.sum(), 1):5.1f}, asked {100 * (harm & ask).sum() / max(harm.sum(), 1):5.1f}); "
                  f"safe wrongly blocked {100 * (~harm & block).sum() / max((~harm).sum(), 1):4.1f} %; human asked on {100 * ask.mean():4.1f} % of actions",
                  flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
