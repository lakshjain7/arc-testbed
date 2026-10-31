import numpy as np
import pandas as pd
from scipy import stats

D = "C:/Users/Laksh/Documents/arc-release/hf/"
ep = pd.read_csv(D + "episodes.csv.gz")
sl = pd.read_csv(D + "service_labels.csv.gz")
cf = pd.read_csv(D + "client_flows.csv.gz")
for c in ("y_mean", "y_mean_1000"):
    sl[c] *= 100
    cf[c] *= 100
camp = ep[(ep.kind == "campaign") & (ep.usable == 1) & (ep.stalled == 0)]
g = sl[(sl.service == "ts-gateway-service") & (sl.kind == "campaign") & (sl.n_before >= 30) & (sl.n_after >= 30)]
agg = cf.groupby("episode_id").apply(lambda d: pd.Series(dict(client=np.average(d.y_mean_1000, weights=d.n_after) if d.n_after.sum() > 0 else np.nan)))
j = g.merge(agg, left_on="episode_id", right_index=True).merge(camp[["episode_id", "fault", "action", "saturated_before_action", "part"]], on="episode_id")
j["diff"] = j.y_mean_1000 - j.client
print("n", len(j), "| |diff|>10:", round((j["diff"].abs() > 10).mean(), 3))
print(j.groupby("saturated_before_action")["diff"].agg(["count", "mean", lambda v: (v.abs() > 10).mean()]).round(3))
print(j.groupby("fault")["diff"].agg(["count", "mean", lambda v: (v.abs() > 10).mean()]).round(3))
big = j[(j.y_mean_1000.abs() > 5) | (j.client.abs() > 5)]
print("episodes with a real effect (either > 5 pp):", len(big), "Pearson %.3f Spearman %.3f mean diff %.2f" % (
    stats.pearsonr(big.y_mean_1000, big.client)[0], stats.spearmanr(big.y_mean_1000, big.client)[0], big["diff"].mean()))
ns = j[j.saturated_before_action == 0]
bigns = ns[(ns.y_mean_1000.abs() > 5) | (ns.client.abs() > 5)]
print("non-saturated, real effect:", len(bigns), "Pearson %.3f within 10 pp %.3f" % (stats.pearsonr(bigns.y_mean_1000, bigns.client)[0], (bigns["diff"].abs() <= 10).mean()))
print("non-saturated all: within 5 pp %.3f within 10 pp %.3f" % ((ns["diff"].abs() <= 5).mean(), (ns["diff"].abs() <= 10).mean()))

# test 2 within the same fault target (levels were dosed per service)
pre = cf.groupby("episode_id").apply(lambda d: pd.Series(dict(up=100 * (d.p_before * d.n_before).sum() / d.n_before.sum())))
pe = camp.merge(pre, left_on="episode_id", right_index=True)
rows = []
for f in ["network-delay", "net-loss", "cpu-squeeze", "db-delay"]:
    d = pe[pe.fault == f].copy()
    d["lvl"] = pd.to_numeric(d.fault_level, errors="coerce")
    sign = 1 if f != "cpu-squeeze" else -1          # a lower multiple of use is a harder squeeze
    for tgt, h in d.groupby("fault_target"):
        if h.lvl.nunique() >= 3 and len(h) >= 12:
            r, p = stats.spearmanr(sign * h.lvl, h.up)
            rows.append((f, tgt, len(h), round(r, 2), round(p, 4)))
t = pd.DataFrame(rows, columns=["fault", "target", "n", "rho", "p"])
print(t.groupby("fault").agg(targets=("rho", "size"), positive=("rho", lambda v: (v > 0).sum()), median_rho=("rho", "median")))
print(t.sort_values("fault").to_string(index=False))
