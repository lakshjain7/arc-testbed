#!/usr/bin/env python3
"""Summarise a load generator run: what failed and why, and per 15 s how each action did.
   python3 loadgen/analyze.py [run_dir]   (default: this cluster's latest run)"""
import glob, json, os, sys
from collections import Counter, defaultdict

base = os.path.join(os.path.expanduser(os.environ.get("ARC_DATA_ROOT", "~/arc-data")),
                    os.environ.get("ARC_CLUSTER", "arc"), "loadgen")
d = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(base, "run-*")))[-1]
rows = [json.loads(l) for l in open(os.path.join(d, "requests.jsonl"))]
t0 = min(r["t"] for r in rows)
ok = sum(1 for r in rows if r["ok"])
print(f"{d}: {len(rows)} requests, {ok} ok ({100 * ok / len(rows):.1f}%)")
print("\nwhy requests failed (op, http, error):")
for (op, http, err), n in Counter((r["op"], r["http"], r.get("err", "")) for r in rows if not r["ok"]).most_common(12):
    print(f"  {n:4d}  {op:7s} HTTP {http:<3}  {err}")
print("\nper 15 s: ok/total and median ms, by op")
b = defaultdict(lambda: defaultdict(list))
for r in rows:
    b[int((r["t"] - t0) // 15)][r["op"]].append(r)
for k in sorted(b):
    parts = []
    for op, rs in sorted(b[k].items()):
        ms = sorted(x["ms"] for x in rs)
        parts.append(f"{op} {sum(x['ok'] for x in rs)}/{len(rs)} {ms[len(ms)//2]:.0f}ms")
    print(f"  {k*15:4d}s  " + "   ".join(parts))
