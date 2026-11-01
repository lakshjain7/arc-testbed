#!/usr/bin/env python3
"""Build the ARC dataset v1.1 release: the v1.0 tables and archives (unchanged rows) plus the Online Boutique part.

  python3 release/merge_v11.py --v10 ~/arc-release --boutique ~/arc-release-v1.1-boutique --out ~/arc-release-v1.1

v1.0 rows are copied as they are; the only additions to them are the new columns `system` (= train-ticket), `contaminated` (= 0)
and the three new split columns. The six v1.0 raw archives are copied byte for byte. Standard library only.
"""
import argparse, csv, gzip, hashlib, os, shutil

TABLES = ("episodes", "service_labels", "client_flows", "splits")
DOCS = ("README.md", "DATASHEET.md", "SCHEMA.md", "CITATION.cff", "LICENSE-DATA.md", "LICENSE-CODE.txt", "arc_data.py")


def read(path):
    with gzip.open(path, "rt", newline="") as f:
        return list(csv.DictReader(f))


def write(path, rows):
    cols = []
    for r in rows:
        for c in r:
            if c not in cols:
                cols.append(c)
    with gzip.open(path, "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v10", required=True)
    ap.add_argument("--boutique", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    v10, bq, out = (os.path.expanduser(x) for x in (a.v10, a.boutique, a.out))
    zen, hf = os.path.join(out, "zenodo"), os.path.join(out, "hf")
    for d in (zen, hf):
        os.makedirs(d, exist_ok=True)
    report = []
    for t in TABLES:
        old = read(os.path.join(v10, "zenodo", t + ".csv.gz"))
        new = read(os.path.join(bq, "zenodo", t + ".csv.gz"))
        for r in old:
            r.setdefault("system", "train-ticket")
            if t == "episodes":
                r.setdefault("contaminated", "0")
            if t == "splits":
                r["in_system_boutique"] = ""
                r["train_tt_test_boutique"], r["train_boutique_test_tt"] = "train", "test"
        rows = [dict(system=r.pop("system"), **r) for r in old] + new if t != "splits" else old + new
        for d in (zen, hf):
            write(os.path.join(d, t + ".csv.gz"), rows)
        report.append(f"{t}: v1.0 {len(old)} + Boutique {len(new)} = {len(rows)}")
    for fn in os.listdir(os.path.join(v10, "zenodo")):
        if fn.startswith("arc-raw-") and fn.endswith("-v1.0.tar.gz"):
            shutil.copy(os.path.join(v10, "zenodo", fn), zen)
    for fn in os.listdir(os.path.join(bq, "zenodo")):
        if fn.startswith("arc-raw-boutique-"):
            shutil.copy(os.path.join(bq, "zenodo", fn), zen)
    for fn in DOCS:
        for d in (zen, hf):
            shutil.copy(os.path.join(here, fn), d)
    for d in (zen, hf):
        sums = [f"{sha256(os.path.join(d, f))}  {f}" for f in sorted(os.listdir(d)) if f != "SHA256SUMS.txt" and os.path.isfile(os.path.join(d, f))]
        open(os.path.join(d, "SHA256SUMS.txt"), "w", newline="\n").write("\n".join(sums) + "\n")
    open(os.path.join(out, "build-report.txt"), "w").write("\n".join(report) + "\n")
    print("\n".join(report))


if __name__ == "__main__":
    main()
