#!/usr/bin/env python3
"""Patch the Prometheus config that ships with Train Ticket. Reads the ConfigMap JSON on stdin and
writes the patched ConfigMap JSON on stdout. Idempotent.

Why each change (all measured on the laptop):
  - no `global:` block at all -> Prometheus scraped once a MINUTE. A 30 s window then holds 0-1 samples.
    Set 15 s globally.
  - the OTel collector (span metrics + service graph) is scraped by the `kubernetes-pods` job; set it
    and `kubernetes-service-endpoints` (kube-state-metrics) to 5 s.
  - drop `kubernetes-apiservers` (~22,800 series) and `kubernetes-nodes-kubelet` (~6,100): never read.
"""
import json, re, sys

cm = json.load(sys.stdin)
y = cm["data"]["prometheus.yml"]

if not re.search(r"(?m)^global:", y):
    y = "global:\n  scrape_interval: 15s\n  evaluation_interval: 15s\n\n" + y

for job in ("kubernetes-service-endpoints", "kubernetes-pods"):
    pat = re.compile(r"(?m)^- job_name: *['\"]?%s['\"]?[ \t]*\n" % re.escape(job))
    m = pat.search(y)
    if m and not y[m.end():].startswith("  scrape_interval:"):
        y = y[:m.end()] + "  scrape_interval: 5s\n" + y[m.end():]

blocks = re.split(r"(?m)^(?=- job_name:)", y)
drop = re.compile(r"- job_name: *['\"]?(kubernetes-apiservers|kubernetes-nodes-kubelet)['\"]?\s*$")
y = "".join(b for b in blocks if not (b and drop.match(b.splitlines()[0])))

cm["data"]["prometheus.yml"] = y
for k in ("resourceVersion", "uid", "creationTimestamp", "managedFields", "annotations"):
    cm["metadata"].pop(k, None)
json.dump(cm, sys.stdout)
