import gzip
import io
import json
import tarfile
import os
from collections import defaultdict, deque
import numpy as np
import pandas as pd

D = "C:/Users/Laksh/Documents/arc-release/"
ep = pd.read_csv(D + "hf/episodes.csv.gz")
sl = pd.read_csv(D + "hf/service_labels.csv.gz")
camp = ep[(ep.kind == "campaign") & (ep.usable == 1) & (ep.stalled == 0)]
acts = camp[camp.action.isin(["drain", "restart-pod", "rollout-restart", "scale-up", "cpu-bump"])]
want = set(acts.episode_id)
services = set(sl.service.unique())

# call graph per episode from edges.csv.gz (edges with traffic before the action)
graphs = {}
for fn in sorted(os.listdir(D + "zenodo")):
    if not fn.startswith("arc-raw-"):
        continue
    with tarfile.open(D + "zenodo/" + fn) as tf:
        for m in tf:
            if not m.isfile() or not m.name.endswith("/edges.csv.gz"):
                continue
            eid = m.name.split("/")[-2]
            if eid not in want:
                continue
            df = pd.read_csv(io.BytesIO(gzip.decompress(tf.extractfile(m).read())))
            df = df[df.window.isin(["B0", "B1"])]
            df = df[df.client.isin(services) & df.server.isin(services)]
            g = df.groupby(["client", "server"]).rps.mean()
            graphs[eid] = [(c, s) for (c, s), v in g.items() if v > 0.05]
    print(fn, "graphs so far", len(graphs), flush=True)


def roles(edges, target):
    callers, callees = defaultdict(set), defaultdict(set)
    for c, s in edges:
        callers[s].add(c)
        callees[c].add(s)
    up1 = callers[target]
    seen, q = {target}, deque([target])
    while q:
        x = q.popleft()
        for c in callers[x]:
            if c not in seen:
                seen.add(c)
                q.append(c)
    up_all = seen - {target}
    seen2, q = {target}, deque([target])
    while q:
        x = q.popleft()
        for c in callees[x]:
            if c not in seen2:
                seen2.add(c)
                q.append(c)
    down_all = seen2 - {target}
    r = {}
    for s in services:
        if s == target:
            r[s] = "target"
        elif s in up1:
            r[s] = "caller (direct)"
        elif s in up_all:
            r[s] = "caller (2+ hops)"
        elif s in down_all:
            r[s] = "callee"
        else:
            r[s] = "unrelated"
    return r


scored = sl[(sl.kind == "campaign") & (sl.n_before >= 30) & (sl.n_after >= 30)]
m = scored.merge(camp[["episode_id", "plan", "block", "fault", "fault_level", "action", "action_target", "saturated_before_action"]], on="episode_id")
noop = m[m.action == "noop"].groupby(["plan", "block", "service"]).y_mean.mean().rename("noop_y")
res = []
for action in ["drain", "restart-pod", "rollout-restart", "scale-up", "cpu-bump"]:
    a = m[(m.action == action) & (m.saturated_before_action == 0) & m.episode_id.isin(graphs.keys())].copy()
    a = a.merge(noop.reset_index(), on=["plan", "block", "service"], how="inner")
    a["excess"] = 100 * (a.y_mean - a.noop_y)       # points
    rl = []
    for _, r in a.iterrows():
        rl.append(roles(graphs[r.episode_id], r.action_target)[r.service])
    a["role"] = rl
    t = a.groupby("role").agg(rows=("excess", "size"), mean_excess=("excess", "mean"), harm_rate=("verdict", lambda v: (v == "harm").mean()),
                              share_gt5=("excess", lambda v: (v > 5).mean())).round(3)
    print("\n", action, "(non-saturated; excess = y_mean minus the no-op of the same block)")
    print(t)
    res.append(dict(action=action, table=t.reset_index().to_dict("records")))
json.dump(res, open("t4.json", "w"), indent=1)
