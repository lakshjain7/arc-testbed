#!/usr/bin/env python3
"""Build the ARC dataset v1.0 release from the parts recorded on the lab machine. Standard library only.

  python3 release/build_release.py --out ~/arc-release  \
      batch1=~/arc-batch1 wide1=~/arc-wide1 wide1db=~/arc-wide1db wide2=~/arc-wide2 reptest=~/arc-reptest held=~/arc-held

Each part folder holds `arc/raw/<episode>/` (the raw files of an episode), `calibration/` and optionally `arc/plans/`.
Raw data is never modified: archives are written from a scrubbed copy (host name and user paths replaced in the
JSON files; the number of replacements is reported). Output, under --out:

  zenodo/   arc-raw-<part>-v1.0.tar.gz (one per part), tables, docs   -> the archive record
  hf/       tables, docs, loader                                      -> the Hugging Face dataset repo
  SHA256SUMS.txt, build-report.txt
Tables (CSV, gzip): episodes, service_labels, client_flows, splits.
"""
import argparse, csv, gzip, hashlib, io, json, os, re, shutil, sys, tarfile, time
from collections import Counter, defaultdict

PLAN_RE = re.compile(r"ep_(?P<plan>.+?)_(?P<cluster>arc\d*|boutique)_b(?P<block>\d+)_(?P<pos>\d+)(?P<redo>_r)?$")
CAMPAIGN_PLANS = {"main", "main2", "wide1", "wide1db", "wide2", "held"}
REPTEST_RE = re.compile(r"ep_rep")                    # the repeatability recipes
SCRUB = [(re.compile(r"/home/[A-Za-z0-9_.-]+"), "/home/user"), (re.compile(r"[A-Za-z]:\\Users\\[^\\\"]+"), r"C:\\Users\\user")]
HOST_FIELDS = ("host",)


def sha256(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(buf):
            h.update(b)
    return h.hexdigest()


def scrub_json(obj, counter):
    """Replace host names and user paths in a parsed JSON value; count what changed."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in HOST_FIELDS and isinstance(v, str) and v:
                counter["host"] += 1
                out[k] = "lab-machine"
            else:
                out[k] = scrub_json(v, counter)
        return out
    if isinstance(obj, list):
        return [scrub_json(v, counter) for v in obj]
    if isinstance(obj, str):
        for rx, rep in SCRUB:
            obj, n = rx.subn(rep, obj)
            counter["path"] += n
        return obj
    return obj


def classify(ep, part):
    if ep.startswith("ep_cal_"):
        return "calibration"
    m = PLAN_RE.match(ep)
    if m and m["plan"] in CAMPAIGN_PLANS:
        return "campaign"
    if part == "reptest" and REPTEST_RE.match(ep):
        return "campaign"
    return "other"


def pack_part(part, root, out_zip, counter):
    """tar.gz of one part: raw/<episode>/..., calibration/..., plans/... (scrubbed copy)."""
    raw = os.path.join(root, "arc", "raw")
    n = 0
    with tarfile.open(out_zip, "w:gz", compresslevel=6) as tf:
        def add_bytes(name, data):
            ti = tarfile.TarInfo(f"{part}/{name}")
            ti.size, ti.mtime, ti.mode = len(data), int(time.time()), 0o644
            tf.addfile(ti, io.BytesIO(data))

        def add_tree(base, arcbase):
            for dp, _, fs in os.walk(base):
                for fn in sorted(fs):
                    p = os.path.join(dp, fn)
                    rel = arcbase + "/" + os.path.relpath(p, base).replace(os.sep, "/")
                    if fn.endswith(".json") and not fn.endswith(".tar.gz"):
                        try:
                            data = json.dumps(scrub_json(json.load(open(p, encoding="utf-8")), counter), indent=1).encode()
                        except ValueError:
                            data = open(p, "rb").read()
                        add_bytes(rel, data)
                    else:
                        tf.add(p, arcname=f"{part}/{rel}")
        for ep in sorted(os.listdir(raw)):
            if os.path.isfile(os.path.join(raw, ep, "meta.json")):
                add_tree(os.path.join(raw, ep), f"raw/{ep}")
                n += 1
        for sub in ("calibration",):
            if os.path.isdir(os.path.join(root, sub)):
                add_tree(os.path.join(root, sub), sub)
        plans = os.path.join(root, "arc", "plans")
        if os.path.isdir(plans):
            add_tree(plans, "plans")
    return n


def rows_for_episode(d, part, ep):
    m = json.load(open(os.path.join(d, "meta.json")))
    lab = json.load(open(os.path.join(d, "labels_v2.json"))) if os.path.exists(os.path.join(d, "labels_v2.json")) else None
    return m, lab


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--index", help="lab index episodes.csv (default: <last part>/index/episodes.csv)")
    ap.add_argument("--version", default="1.0")
    ap.add_argument("--no-archives", action="store_true", help="tables only (fast)")
    ap.add_argument("parts", nargs="+", help="name=folder")
    a = ap.parse_args()
    out = os.path.expanduser(a.out)
    zen, hf = os.path.join(out, "zenodo"), os.path.join(out, "hf")
    for d in (zen, hf):
        os.makedirs(d, exist_ok=True)
    parts = [(p.split("=", 1)[0], os.path.expanduser(p.split("=", 1)[1])) for p in a.parts]
    index = {}
    idx_path = a.index or os.path.join(parts[-1][1], "index", "episodes.csv")
    if os.path.exists(idx_path):
        index = {r["episode_id"]: r for r in csv.DictReader(open(idx_path))}
    report, counter = [], Counter()

    eps, svc, flows = [], [], []
    for part, root in parts:
        raw = os.path.join(root, "arc", "raw")
        for ep in sorted(os.listdir(raw)):
            d = os.path.join(raw, ep)
            if not os.path.isfile(os.path.join(d, "meta.json")):
                continue
            kind = classify(ep, part)
            m, lab = rows_for_episode(d, part, ep)
            ix = index.get(ep, {})
            pm = PLAN_RE.match(ep)
            row = {"episode_id": ep, "part": part, "kind": kind, "plan": pm["plan"] if pm else "", "block": int(pm["block"]) if pm else "",
                   "position": int(pm["pos"]) if pm else "", "is_repeat": int(bool(pm and pm["redo"])),
                   "status": m.get("status"), "discard_reason": m.get("discard_reason") or "",
                   "usable": ix.get("usable", "1" if m.get("status") == "ok" else "0"),
                   "fault": m.get("fault_type"), "fault_level": m.get("fault_param"), "fault_target": m.get("fault_target") or "",
                   "action": m.get("action_type"), "action_target": m.get("action_target") or "",
                   "action_on_fault_target": int(bool(m.get("action_on_fault_target"))),
                   "delay_s": m.get("action_delay_s"), "load_rate_req_s": m.get("load_rate"), "load_mix": m.get("load_mix"),
                   "recorded": ix.get("recorded", ""), "healthy_after": m.get("healthy_after"),
                   "saturated_before_action": int(bool(lab and lab.get("saturated_before_action"))),
                   "stalled": int(bool(lab and lab.get("stalled")))}
            if lab:
                s = lab["summary"]
                row.update(user_damage_pts=s.get("user_damage"), user_damage_abs500_pts=s.get("user_damage_abs500"),
                           user_damage_abs1000_pts=s.get("user_damage_abs1000"), collateral_harmed=s.get("collateral_harmed"),
                           collateral_mean_sum_pts=s.get("collateral_mean_sum"), collateral_peak_sum_pts=s.get("collateral_peak_sum"))
                for sv, v in lab["services"].items():
                    ab = v.get("abs", {})
                    svc.append({"episode_id": ep, "part": part, "kind": kind, "service": sv, "is_action_target": int(sv == lab.get("action_target")),
                                "is_fault_target": int(sv == lab.get("fault_target")), "verdict": v.get("verdict"),
                                "n_before": v.get("N_B1L"), "bad_before": v.get("X_B1L"), "n_after": v.get("N_M"), "bad_after": v.get("X_M"),
                                "p_before": v.get("p_B1L"), "p_after": v.get("p_M"),
                                "y_mean": v.get("y_mean"), "y_mean_se": v.get("se_mean"), "y_peak": v.get("y_peak"), "y_excess": v.get("y_excess"),
                                "t_recover_s": v.get("t_recover_s"), "recovered_by_end": int(bool(v.get("recovered_by_end"))),
                                "y_mean_500": (ab.get("500") or {}).get("y_mean"), "y_peak_500": (ab.get("500") or {}).get("y_peak"),
                                "y_mean_1000": (ab.get("1000") or {}).get("y_mean"), "y_peak_1000": (ab.get("1000") or {}).get("y_peak"),
                                "block_deltas": json.dumps(v.get("block_deltas"))})
                for fl, v in (lab.get("client_flows") or {}).items():
                    ab = v.get("abs", {})
                    flows.append({"episode_id": ep, "flow": fl, "n_before": v.get("N_B1L"), "n_after": v.get("N_M"),
                                  "p_before": v.get("p_B1L"), "p_after": v.get("p_M"), "y_mean": v.get("y_mean"), "bar_ms": v.get("T_ms"),
                                  "y_mean_500": (ab.get("500") or {}).get("y_mean"), "y_mean_1000": (ab.get("1000") or {}).get("y_mean")})
            eps.append(row)

    # splits (protocols as in docs/DATASET-V1.md); only campaign episodes that are usable take part
    splits = []
    for r in eps:
        if r["kind"] != "campaign" or str(r["usable"]) != "1":
            continue
        part, blk = r["part"], r["block"] if r["block"] != "" else 0
        s = {"episode_id": r["episode_id"], "part": part}
        s["in_system"] = ("test" if blk % 5 == 0 else "train") if part in ("batch1", "wide1", "wide1db", "wide2", "held") else ""
        s["unseen_system"] = "train" if part == "batch1" else "test" if part == "wide1" else ""
        s["unseen_fault"] = "train" if part == "wide1" else "test" if part == "wide1db" else ""
        s["held_out_faults"] = "test" if part == "held" else "train" if part != "reptest" else ""
        s["higher_load"] = "train" if part in ("batch1", "wide1", "wide1db") else "test" if part == "wide2" else ""
        s["noise_ceiling"] = "repeat" if part == "reptest" else ""
        s["wide2_first_half"] = int(part == "wide2" and blk <= 24)      # blocks 1-24: before the cancel-flow drift (F21)
        splits.append(s)

    def write(name, rows, dest):
        if not rows:
            return 0
        cols = list(rows[0])
        for r in rows:
            for c in r:
                if c not in cols:
                    cols.append(c)
        for d in dest:
            with gzip.open(os.path.join(d, name + ".csv.gz"), "wt", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                w.writerows(rows)
        return len(rows)

    n = {t: write(t, rows, [zen, hf]) for t, rows in (("episodes", eps), ("service_labels", svc), ("client_flows", flows), ("splits", splits))}
    report.append("tables: " + json.dumps(n))
    kinds = Counter((r["part"], r["kind"], str(r["usable"])) for r in eps)
    report.append("episodes by (part, kind, usable): " + json.dumps({"/".join(k): v for k, v in sorted(kinds.items())}))
    camp = {r["episode_id"] for r in eps if r["kind"] == "campaign" and str(r["usable"]) == "1"}
    cs = [r for r in svc if r["episode_id"] in camp]
    scored = sum(1 for r in cs if (r["n_before"] or 0) >= 30 and (r["n_after"] or 0) >= 30)
    sat = sum(1 for r in eps if r["episode_id"] in camp and r["saturated_before_action"])
    report.append(f"campaign episodes {len(camp)}; service rows {len(cs)} (all kinds {len(svc)}); scored (>=30 requests before and after) {scored}; saturated episodes {sat}")

    if not a.no_archives:
        for part, root in parts:
            z = os.path.join(zen, f"arc-raw-{part}-v{a.version}.tar.gz")
            t0 = time.time()
            n_ep = pack_part(part, root, z, counter)
            report.append(f"archive {os.path.basename(z)}: {n_ep} episodes, {os.path.getsize(z) / 1e6:.1f} MB, {time.time() - t0:.0f} s")
    report.append(f"scrubbed: {dict(counter)}")

    for fn in ("README.md", "DATASHEET.md", "SCHEMA.md", "CITATION.cff", "LICENSE-DATA.md", "LICENSE-CODE.txt", "arc_data.py"):
        src = os.path.join(os.path.dirname(os.path.abspath(__file__)), fn)
        if os.path.exists(src):
            for d in (zen, hf):
                shutil.copy(src, d)
    for d in (zen, hf):
        sums = []
        for fn in sorted(os.listdir(d)):
            if fn != "SHA256SUMS.txt" and os.path.isfile(os.path.join(d, fn)):
                sums.append(f"{sha256(os.path.join(d, fn))}  {fn}")
        open(os.path.join(d, "SHA256SUMS.txt"), "w").write("\n".join(sums) + "\n")
    open(os.path.join(out, "build-report.txt"), "w").write("\n".join(report) + "\n")
    print("\n".join(report))


if __name__ == "__main__":
    main()
