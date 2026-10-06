#!/usr/bin/env python3
"""Per-15 s timeline of what users saw in an episode (client.csv.gz): requests, failures, median/max ms.
   episode-timeline.py ~/arc-data/arc/raw/ep_x"""
import csv, gzip, json, os, sys, time
from collections import defaultdict
d = os.path.expanduser(sys.argv[1])
rows = list(csv.DictReader(gzip.open(d + "/client.csv.gz", "rt")))
meta = json.load(open(d + "/meta.json"))
t0 = min(float(r["t"]) for r in rows)
b = defaultdict(list)
for r in rows:
    b[int((float(r["t"]) - t0) // 15)].append(r)
for k in sorted(b):
    rs = b[k]; ms = sorted(float(r["ms"]) for r in rs)
    slow = [f"{r['op']}:{float(r['ms'])/1000:.1f}s" for r in rs if float(r["ms"]) > 2000]
    print(f"  {time.strftime('%H:%M:%S', time.localtime(t0 + 15*k))} [{rs[0]['window']:>2}] n={len(rs):3d} fail={sum(r['ok']=='0' for r in rs)} "
          f"median={ms[len(ms)//2]:6.0f}ms max={ms[-1]:7.0f}ms  {' '.join(slow[:4])}")
ev = json.load(open(d + "/events.json"))
print("k8s events:", len(ev), [e["reason"] + " " + e["object"] for e in ev][:5])
