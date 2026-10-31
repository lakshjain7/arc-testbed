import json
import numpy as np
import pandas as pd
from collections import defaultdict, deque
from scipy import stats

T = "C:/Users/Laksh/Documents/arc-boutique/tables/"
RAW = "C:/Users/Laksh/Documents/arc-boutique/data/boutique/raw/"
ep = pd.read_csv(T + "episodes.csv.gz")
sl = pd.read_csv(T + "service_labels.csv.gz")
cf = pd.read_csv(T + "client_flows.csv.gz")
for c in ("y_mean", "y_peak", "y_mean_1000"):
    sl[c] *= 100
for c in ("y_mean", "y_mean_1000"):
    cf[c] *= 100
camp = ep[(ep.kind == "campaign") & (ep.usable == 1) & (ep.stalled == 0)]
scored = sl[(sl.n_before >= 30) & (sl.n_after >= 30)]
m = scored.merge(ep[["episode_id", "kind", "plan", "block", "fault", "fault_level", "action", "action_target", "saturated_before_action", "stalled", "usable"]], on="episode_id")
print("clean campaign episodes (not stalled):", len(camp), "| scored service rows (campaign, clean):",
      len(m[(m.kind == "campaign") & (m.usable == 1)]))

print("\n=== TEST 1: negative control ===")
for name, d in (("no fault + no-op (campaign, not saturated)", m[(m.kind == "campaign") & (m.usable == 1) & (m.fault == "none") & (m.action == "noop") & (m.saturated_before_action == 0) & (m.stalled == 0)]),
                ("healthy calibration episodes", m[m.kind == "calibration"]),
                ("no fault + drain (contrast)", m[(m.kind == "campaign") & (m.usable == 1) & (m.fault == "none") & (m.action == "drain") & (m.saturated_before_action == 0) & (m.stalled == 0)])):
    print("%-45s episodes %3d rows %4d harm %.4f mean %.3f pp  p95|y| %.2f  rows>5pp %.4f" % (
        name, d.episode_id.nunique(), len(d), (d.verdict == "harm").mean(), d.y_mean.mean(), d.y_mean.abs().quantile(0.95), (d.y_mean.abs() > 5).mean()))
nc = m[(m.kind == "campaign") & (m.usable == 1) & (m.fault == "none") & (m.action == "noop") & (m.saturated_before_action == 0)]
em = nc.groupby("episode_id").y_mean.mean()
print("episode means of the no-fault no-op: mean %.3f, n=%d, t-test p=%.3f" % (em.mean(), len(em), stats.ttest_1samp(em, 0).pvalue))

print("\n=== TEST 2: dose-response (user bad share before the action) ===")
pre = cf.groupby("episode_id").apply(lambda d: pd.Series(dict(up=100 * (d.p_before * d.n_before).sum() / max(d.n_before.sum(), 1))))
pe = camp.merge(pre, left_on="episode_id", right_index=True)
for f in ["network-delay", "net-loss", "cpu-squeeze", "pod-hang", "pod-kill", "none"]:
    d = pe[pe.fault == f]
    g = d.groupby("fault_level", dropna=False).agg(n=("up", "size"), user_bad_before=("up", "mean"), saturated=("saturated_before_action", "mean")).round(3)
    extra = ""
    lv = d.fault_level.dropna().unique()
    if len(lv) == 2:
        a = d[d.fault_level == min(lv)].up
        b = d[d.fault_level == max(lv)].up
        extra = "  Mann-Whitney p=%.2g (higher level larger: %s)" % (stats.mannwhitneyu(a, b, alternative="less").pvalue, b.mean() > a.mean())
    print("\n", f, extra); print(g)

print("\n=== TEST 3: frontend counters vs the load generator's log ===")
g = sl[(sl.service == "frontend") & (sl.n_before >= 30) & (sl.n_after >= 30)].merge(camp[["episode_id", "action", "saturated_before_action"]], on="episode_id")
agg = cf.groupby("episode_id").apply(lambda d: pd.Series(dict(client=np.average(d.y_mean_1000, weights=d.n_after) if d.n_after.sum() > 0 else np.nan)))
j = g.merge(agg, left_on="episode_id", right_index=True).dropna(subset=["y_mean_1000", "client"])
j["diff"] = j.y_mean_1000 - j.client
print("episodes %d  Pearson %.3f  Spearman %.3f  mean diff %.2f pp  within 5: %.3f  within 10: %.3f" % (
    len(j), stats.pearsonr(j.y_mean_1000, j.client)[0], stats.spearmanr(j.y_mean_1000, j.client)[0], j["diff"].mean(), (j["diff"].abs() <= 5).mean(), (j["diff"].abs() <= 10).mean()))
big = j[(j.y_mean_1000.abs() > 5) | (j.client.abs() > 5)]
print("real-effect episodes %d  Pearson %.3f  Spearman %.3f  mean diff %.2f  within 10: %.3f  sign agree %.3f" % (
    len(big), stats.pearsonr(big.y_mean_1000, big.client)[0], stats.spearmanr(big.y_mean_1000, big.client)[0], big["diff"].mean(),
    (big["diff"].abs() <= 10).mean(), (np.sign(big.y_mean_1000) == np.sign(big.client)).mean()))
print(j[j.saturated_before_action == 0].groupby("action")[["y_mean_1000", "client"]].mean().round(2))

print("\n=== TEST 4: mechanism (excess over the same block's no-op) ===")
services = set(sl.service.unique())
want = set(camp[camp.action.isin(["drain", "restart-pod", "rollout-restart", "scale-up", "cpu-bump"])].episode_id)
graphs = {}
for eid in want:
    df = pd.read_csv(RAW + eid + "/edges.csv.gz")
    df = df[df.window.isin(["B0", "B1"]) & df.client.isin(services) & df.server.isin(services)]
    gg = df.groupby(["client", "server"]).rps.mean()
    graphs[eid] = [(c, s) for (c, s), v in gg.items() if v > 0.05]
print("graphs", len(graphs), "avg edges", np.mean([len(v) for v in graphs.values()]).round(1))


def roles(edges, target):
    callers, callees = defaultdict(set), defaultdict(set)
    for c, s in edges:
        callers[s].add(c)
        callees[c].add(s)

    def reach(rel):
        seen, q = {target}, deque([target])
        while q:
            x = q.popleft()
            for y in rel[x]:
                if y not in seen:
                    seen.add(y)
                    q.append(y)
        return seen - {target}
    up_all, down_all = reach(callers), reach(callees)
    r = {}
    for s in services:
        r[s] = "target" if s == target else "caller (direct)" if s in callers[target] else "caller (2+ hops)" if s in up_all else "callee" if s in down_all else "unrelated"
    return r


mm = m[(m.kind == "campaign") & (m.usable == 1)]
noop = mm[mm.action == "noop"].groupby(["plan", "block", "service"]).y_mean.mean().rename("noop_y")
for action in ["drain", "restart-pod", "rollout-restart", "scale-up", "cpu-bump"]:
    a = mm[(mm.action == action) & (mm.saturated_before_action == 0) & (mm.stalled == 0) & mm.episode_id.isin(graphs.keys())].copy()
    a = a.merge(noop.reset_index(), on=["plan", "block", "service"], how="inner")
    a["excess"] = a.y_mean - a.noop_y
    a["role"] = [roles(graphs[r.episode_id], r.action_target)[r.service] for _, r in a.iterrows()]
    t = a.groupby("role").agg(rows=("excess", "size"), mean_excess_pp=("excess", "mean"), harm_rate=("verdict", lambda v: (v == "harm").mean())).round(3)
    print("\n", action); print(t)
