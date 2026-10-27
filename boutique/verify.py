#!/usr/bin/env python3
"""Which Online Boutique services show up in the telemetry? Prints, per service: server spans, p95 and the
edges found in the service graph. A service that is missing has no tracing and must be fixed before any
episode is run."""
import argparse, json, urllib.parse, urllib.request

EXPECT = ["adservice", "cartservice", "checkoutservice", "currencyservice", "emailservice", "frontend",
          "paymentservice", "productcatalogservice", "recommendationservice", "shippingservice"]


def q(prom, expr):
    url = prom + "/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    return json.load(urllib.request.urlopen(url, timeout=20))["data"]["result"]


ap = argparse.ArgumentParser()
ap.add_argument("--prom", default="http://localhost:19091")
a = ap.parse_args()
S = 'span_kind="SPAN_KIND_SERVER"'
calls = {r["metric"]["service_name"]: float(r["value"][1]) for r in q(a.prom, f'sum by (service_name) (traces_span_metrics_calls_total{{{S}}})')}
p95 = {r["metric"]["service_name"]: float(r["value"][1]) for r in q(a.prom, f'histogram_quantile(0.95, sum by (service_name, le) (rate(traces_span_metrics_duration_milliseconds_bucket{{{S}}}[2m])))')}
edges = [(r["metric"]["client"], r["metric"]["server"], float(r["value"][1])) for r in q(a.prom, 'sum by (client, server) (traces_service_graph_request_total)')]
print(f"{'service':24s} {'server calls':>12s} {'p95 ms':>8s}")
missing = []
for s in EXPECT:
    c = calls.get(s)
    print(f"{s:24s} {c if c is not None else 'MISSING':>12} {p95.get(s, float('nan')):8.1f}")
    if c is None:
        missing.append(s)
print("edges:", ", ".join(f"{c}->{s} ({n:.0f})" for c, s, n in sorted(edges)))
print("MISSING (no server spans): " + (", ".join(missing) if missing else "none"))
