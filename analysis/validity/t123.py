import json
import numpy as np
import pandas as pd
from scipy import stats

D = "C:/Users/Laksh/Documents/arc-release/hf/"
ep = pd.read_csv(D + "episodes.csv.gz")
sl = pd.read_csv(D + "service_labels.csv.gz")
cf = pd.read_csv(D + "client_flows.csv.gz")
out = {}
for _c in ("y_mean", "y_peak", "y_mean_500", "y_mean_1000", "y_peak_500", "y_peak_1000", "y_mean_se"):
    sl[_c] = sl[_c] * 100          # tables hold fractions; the paper reports points
for _c in ("y_mean", "y_mean_500", "y_mean_1000"):
    cf[_c] = cf[_c] * 100

camp = ep[(ep.kind == "campaign") & (ep.usable == 1)]
print("campaign usable episodes", len(camp))
scored = sl[(sl.kind == "campaign") & (sl.n_before >= 30) & (sl.n_after >= 30)]
scored = scored[scored.episode_id.isin(camp.episode_id)]
print("scored service rows", len(scored))
m = scored.merge(camp[["episode_id", "fault", "fault_level", "action", "saturated_before_action", "block", "plan", "part", "stalled"]],
                 on="episode_id", suffixes=("", "_e"))

# ------------------------------------------------------------------ test 1: negative control
print("\n=== TEST 1: negative control (no fault + no-op) ===")
nc = m[(m.fault == "none") & (m.action == "noop") & (m.saturated_before_action == 0) & (m.stalled == 0)]
real = m[(m.fault == "none") & (m.action == "drain") & (m.saturated_before_action == 0) & (m.stalled == 0)]
cal = sl[(sl.kind == "calibration") & (sl.n_before >= 30) & (sl.n_after >= 30)]
def summ(d, name):
    h = (d.verdict == "harm").mean()
    r = dict(name=name, episodes=int(d.episode_id.nunique()), rows=int(len(d)), harm_rate=round(float(h), 4),
             mean_y=round(float(d.y_mean.mean()), 3), median_y=round(float(d.y_mean.median()), 3),
             p95_abs=round(float(d.y_mean.abs().quantile(0.95)), 2), p99_abs=round(float(d.y_mean.abs().quantile(0.99)), 2),
             share_abs_gt5=round(float((d.y_mean.abs() > 5).mean()), 4))
    print(r)
    return r
out["t1"] = [summ(nc, "no fault + no-op (campaign)"), summ(cal, "healthy calibration episodes"), summ(real, "no fault + drain (contrast)")]
by_part = nc.groupby("part").apply(lambda d: pd.Series(dict(rows=len(d), harm=round((d.verdict == "harm").mean(), 4), mean_y=round(d.y_mean.mean(), 3))))
print(by_part)
# is y_mean of a no-op distinguishable from zero? rows are clustered by episode: use episode means
epmean = nc.groupby("episode_id").y_mean.mean()
t = stats.ttest_1samp(epmean, 0)
print("episode-mean y of no-fault no-op: mean %.3f, n=%d, t-test p=%.3f" % (epmean.mean(), len(epmean), t.pvalue))
out["t1_ttest"] = dict(mean=float(epmean.mean()), n=int(len(epmean)), p=float(t.pvalue))

# ------------------------------------------------------------------ test 2: dose-response
print("\n=== TEST 2: dose-response (fault level vs what users see BEFORE the action) ===")
pre = cf.groupby("episode_id").apply(lambda d: pd.Series(dict(n=d.n_before.sum(), bad=(d.p_before * d.n_before).sum())))
pre["user_p_before"] = 100 * pre.bad / pre.n
pe = camp.merge(pre[["user_p_before"]], left_on="episode_id", right_index=True, how="left")
pe = pe[(pe.stalled == 0)]
res2 = []
for f in ["network-delay", "net-loss", "cpu-squeeze", "load-surge", "pod-kill", "db-delay", "call-cut"]:
    d = pe[pe.fault == f].copy()
    d["lvl"] = pd.to_numeric(d.fault_level, errors="coerce")
    if d.lvl.nunique() < 2:
        print(f, "levels:", d.fault_level.unique()[:5], "n=", len(d)); continue
    g = d.groupby("lvl").agg(n=("episode_id", "count"), user_bad_before=("user_p_before", "mean"),
                              saturated=("saturated_before_action", "mean")).round(3)
    rho, p = stats.spearmanr(d.lvl, d.user_p_before, nan_policy="omit")
    print("\n", f, "  Spearman(level, user bad share before action) = %.2f (p=%.2g)" % (rho, p)); print(g)
    res2.append(dict(fault=f, rho=round(float(rho), 3), p=float(p), table=g.reset_index().to_dict("records")))
none = pe[pe.fault == "none"]
print("\nno fault: user bad share before action: mean %.2f, n=%d" % (none.user_p_before.mean(), len(none)))
out["t2"] = res2
out["t2_none_user_p_before"] = float(none.user_p_before.mean())

# ------------------------------------------------------------------ test 3: two instruments
print("\n=== TEST 3: service-side counters vs the load generator's own request log ===")
print("services:", sorted(sl.service.unique())[:30])
gw = [s for s in sl.service.unique() if "gateway" in s]
print("gateway-like:", gw)
if gw:
    g = sl[(sl.service == gw[0]) & (sl.kind == "campaign")].merge(camp[["episode_id", "saturated_before_action", "stalled"]], on="episode_id")
    cl = cf.copy()
    cl["w"] = cl.n_after
    agg = cl.groupby("episode_id").apply(lambda d: pd.Series(dict(
        client_mean=np.average(d.y_mean, weights=d.n_after) if d.n_after.sum() > 0 else np.nan,
        client_1000=np.average(d.y_mean_1000, weights=d.n_after) if d.n_after.sum() > 0 else np.nan,
        n_client=d.n_after.sum())))
    j = g.merge(agg, left_on="episode_id", right_index=True)
    j = j[(j.n_before >= 30) & (j.n_after >= 30) & (j.stalled == 0)]
    for lab, a, b in (("calibrated bar", "y_mean", "client_mean"), ("1 s bar", "y_mean_1000", "client_1000")):
        d = j.dropna(subset=[a, b])
        r, _ = stats.pearsonr(d[a], d[b]); rho, _ = stats.spearmanr(d[a], d[b])
        diff = d[a] - d[b]
        print("%s: n=%d  Pearson %.3f  Spearman %.3f  mean diff %.2f pp  within 5 pp: %.1f%%  within 10 pp: %.1f%%" %
              (lab, len(d), r, rho, diff.mean(), 100 * (diff.abs() <= 5).mean(), 100 * (diff.abs() <= 10).mean()))
        out.setdefault("t3", []).append(dict(bar=lab, n=int(len(d)), pearson=round(float(r), 3), spearman=round(float(rho), 3),
                                              mean_diff=round(float(diff.mean()), 2), within5=round(float((diff.abs() <= 5).mean()), 3),
                                              within10=round(float((diff.abs() <= 10).mean()), 3), gateway=gw[0]))
    jj = j[j.saturated_before_action == 0]
    d = jj.dropna(subset=["y_mean_1000", "client_1000"])
    r, _ = stats.pearsonr(d.y_mean_1000, d.client_1000)
    print("non-saturated only, 1 s bar: n=%d Pearson %.3f" % (len(d), r))
json.dump(out, open("t123.json", "w"), indent=1, default=str)
