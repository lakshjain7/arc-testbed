"""Build v1.0-style tables for the Online Boutique campaign from the raw episode folders."""
import glob
import json
import os
import re
import pandas as pd

ROOT = "C:/Users/Laksh/Documents/arc-boutique/data/"
OUT = "C:/Users/Laksh/Documents/arc-boutique/tables/"
os.makedirs(OUT, exist_ok=True)
APP = {"adservice", "cartservice", "checkoutservice", "currencyservice", "emailservice", "frontend", "paymentservice",
       "productcatalogservice", "recommendationservice", "shippingservice", "redis-cart"}
CONTAM = set(json.load(open("C:/Users/Laksh/Documents/arc-testbed/release/contaminated_boutique.json"))["episodes"])

eps, svc, flows = [], [], []
for d in sorted(glob.glob(ROOT + "boutique/raw/*")):
    eid = os.path.basename(d)
    if eid.startswith("smk_"):
        continue
    m = json.load(open(d + "/meta.json"))
    lp = d + "/labels_v2.json"
    lab = json.load(open(lp)) if os.path.exists(lp) else None
    mm = re.match(r"ep_(main|cal)_boutique_(?:b(\d+)_(\d+))?(_r)?$", eid)
    kind = "campaign" if eid.startswith("ep_main") else "calibration"
    block = int(mm.group(2)) if mm and mm.group(2) else None
    pos = int(mm.group(3)) if mm and mm.group(3) else None
    ok = m.get("status") == "ok"
    row = dict(episode_id=eid, kind=kind, plan="main" if kind == "campaign" else "calibration", block=block, position=pos,
               is_repeat=int(eid.endswith("_r")), status=m.get("status"), discard_reason=m.get("discard_reason"),
               contaminated=int(eid in CONTAM), usable=int(ok and eid not in CONTAM and kind == "campaign"),
               fault=m.get("fault_type"), fault_level=m.get("fault_param"), fault_target=m.get("fault_target"),
               action=m.get("action_type"), action_target=m.get("action_target"), delay_s=m.get("action_delay_s"),
               load_rate_req_s=m.get("load_rate"), load_mix=m.get("load_mix"))
    if lab:
        s = lab["summary"]
        row.update(saturated_before_action=int(bool(lab.get("saturated_before_action"))), stalled=int(bool(lab.get("stalled"))),
                   user_damage=s.get("user_damage"), user_damage_abs1000=s.get("user_damage_abs1000"),
                   collateral_harmed=s.get("collateral_harmed"))
        for name, v in lab["services"].items():
            if name not in APP:
                continue
            svc.append(dict(episode_id=eid, service=name, is_action_target=int(name == m.get("action_target")),
                            is_fault_target=int(name == m.get("fault_target")), verdict=v.get("verdict"),
                            n_before=v.get("N_B1L"), bad_before=v.get("X_B1L"), n_after=v.get("N_M"), bad_after=v.get("X_M"),
                            p_before=v.get("p_B1L"), p_after=v.get("p_M"), y_mean=v.get("y_mean"), y_peak=v.get("y_peak"),
                            y_mean_1000=(v.get("abs") or {}).get("1000", {}).get("y_mean"), t_recover_s=v.get("t_recover_s")))
        for name, v in lab["client_flows"].items():
            flows.append(dict(episode_id=eid, flow=name, n_before=v.get("N_B1L"), n_after=v.get("N_M"), p_before=v.get("p_B1L"),
                              p_after=v.get("p_M"), y_mean=v.get("y_mean"), bar_ms=v.get("T_ms"),
                              y_mean_1000=(v.get("abs") or {}).get("1000", {}).get("y_mean")))
    eps.append(row)
E, S, F = pd.DataFrame(eps), pd.DataFrame(svc), pd.DataFrame(flows)
E.to_csv(OUT + "episodes.csv.gz", index=False)
S.to_csv(OUT + "service_labels.csv.gz", index=False)
F.to_csv(OUT + "client_flows.csv.gz", index=False)
print("episodes", E.shape, "service rows", S.shape, "flow rows", F.shape)
print(E[E.kind == "campaign"].groupby(["status", "contaminated"]).size())
print(E[(E.kind == "campaign") & (E.status == "ok")].fault.value_counts().to_dict())
print(E[(E.kind == "campaign") & (E.status == "ok")].action.value_counts().to_dict())
print("saturated:", int(E[(E.kind == "campaign") & (E.status == "ok")].saturated_before_action.sum()))
