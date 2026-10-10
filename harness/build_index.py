#!/usr/bin/env python3
"""Two spreadsheets that describe the whole dataset, so it can be read in Excel without opening folders.

  episodes.csv         one row per episode: what was done, whether it is usable, how much damage
  service_labels.csv   one row per (episode, service): the training labels

  build_index.py                           every cluster under ARC_DATA_ROOT -> <ARC_DATA_ROOT>/index/
  build_index.py RAW_DIR [RAW_DIR ...] --out DIR
"""
import csv, glob, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arcenv

args = sys.argv[1:]
out = os.path.join(arcenv.DATA_ROOT, "index")
if "--out" in args:
    out = os.path.expanduser(args[args.index("--out") + 1])
    args = [a for a in args if a not in ("--out", args[args.index("--out") + 1])]
roots = [os.path.expanduser(a) for a in args] or glob.glob(os.path.join(arcenv.DATA_ROOT, "*", "raw"))
os.makedirs(out, exist_ok=True)


def load(p):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return {}


def pts(v):
    return "" if v is None else round(100 * v, 2)


E_COLS = ["episode_id", "cluster", "host", "recorded", "status", "discard_reason", "usable", "fault", "fault_level",
          "fault_target", "action", "action_target", "action_on_fault_target", "delay_s", "load_rate",
          "stalled", "saturated_before_action", "services_harm", "services_no_harm", "services_inconclusive",
          "services_no_data", "collateral_harmed", "collateral_peak_sum_pts", "collateral_mean_sum_pts",
          "user_damage_pts", "user_damage_abs500_pts", "user_damage_abs1000_pts", "collateral_peak_sum_abs1000_pts",
          "users_bad_before_abs1000_pct", "healthy_after", "recovery_after_s", "folder"]
S_COLS = ["episode_id", "service", "is_action_target", "is_fault_target", "verdict", "requests_before",
          "requests_after", "bad_before_pct", "bad_after_pct", "y_mean_pts", "y_peak_pts", "y_mean_abs500_pts", "y_peak_abs500_pts", "y_mean_abs1000_pts", "y_peak_abs1000_pts", "y_excess_requests",
          "t_recover_s", "recovered_by_end"]
erows, srows = [], []
for root in roots:
    for d in sorted(glob.glob(os.path.join(root, "*"))):
        m = load(os.path.join(d, "meta.json"))
        if not m:
            continue
        lab = load(os.path.join(d, "labels_v2.json"))
        svcs = lab.get("services", {})
        v = [s.get("verdict") for s in svcs.values()]
        sm = lab.get("summary", {})
        ep = m.get("episode_id") or os.path.basename(d)
        usable = m.get("status") == "ok" and bool(lab) and not lab.get("stalled")
        erows.append({
            "episode_id": ep, "cluster": m.get("cluster", ""), "host": m.get("host", ""),
            "recorded": time.strftime("%Y-%m-%d %H:%M", time.localtime(m["exported_at"])) if m.get("exported_at") else "",
            "status": m.get("status"), "discard_reason": m.get("discard_reason") or "", "usable": int(usable),
            "fault": m.get("fault_type"), "fault_level": m.get("fault_param") if m.get("fault_param") is not None else "",
            "fault_target": m.get("fault_target") or "", "action": m.get("action_type"),
            "action_target": m.get("action_target") or "", "action_on_fault_target": int(bool(m.get("action_on_fault_target"))),
            "delay_s": m.get("action_delay_s"), "load_rate": m.get("load_rate"),
            "stalled": int(bool(lab.get("stalled"))), "saturated_before_action": int(bool(lab.get("saturated_before_action"))),
            "services_harm": v.count("harm"), "services_no_harm": v.count("no_harm"),
            "services_inconclusive": v.count("inconclusive"), "services_no_data": v.count("no_data"),
            "collateral_harmed": sm.get("collateral_harmed", ""), "collateral_peak_sum_pts": pts(sm.get("collateral_peak_sum")),
            "collateral_mean_sum_pts": pts(sm.get("collateral_mean_sum")), "user_damage_pts": pts(sm.get("user_damage")),
            "user_damage_abs500_pts": pts(sm.get("user_damage_abs500")), "user_damage_abs1000_pts": pts(sm.get("user_damage_abs1000")),
            "collateral_peak_sum_abs1000_pts": pts(sm.get("collateral_peak_sum_abs1000")),
            "users_bad_before_abs1000_pct": pts(sm.get("users_bad_before_abs1000")),
            "healthy_after": "" if m.get("healthy_after") is None else int(bool(m.get("healthy_after"))),
            "recovery_after_s": m.get("recovery_after_s", ""), "folder": d})
        for s, r in svcs.items():
            srows.append({
                "episode_id": ep, "service": s, "is_action_target": int(s == m.get("action_target")),
                "is_fault_target": int(s == m.get("fault_target")), "verdict": r.get("verdict"),
                "requests_before": r.get("N_B1L"), "requests_after": r.get("N_M"),
                "bad_before_pct": pts(r.get("p_B1L")), "bad_after_pct": pts(r.get("p_M")),
                "y_mean_pts": pts(r.get("y_mean")), "y_peak_pts": pts(r.get("y_peak")),
                "y_mean_abs500_pts": pts((r.get("abs", {}).get("500") or {}).get("y_mean")),
                "y_peak_abs500_pts": pts((r.get("abs", {}).get("500") or {}).get("y_peak")),
                "y_mean_abs1000_pts": pts((r.get("abs", {}).get("1000") or {}).get("y_mean")),
                "y_peak_abs1000_pts": pts((r.get("abs", {}).get("1000") or {}).get("y_peak")),
                "y_excess_requests": "" if r.get("y_excess") is None else round(r["y_excess"], 1),
                "t_recover_s": r.get("t_recover_s", ""),
                "recovered_by_end": "" if r.get("recovered_by_end") is None else int(r["recovered_by_end"])})

for name, cols, rows in (("episodes.csv", E_COLS, erows), ("service_labels.csv", S_COLS, srows)):
    with open(os.path.join(out, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
ok = sum(r["usable"] for r in erows)
print(f"{len(erows)} episodes ({ok} usable), {len(srows)} service rows -> {out}/episodes.csv, service_labels.csv")
