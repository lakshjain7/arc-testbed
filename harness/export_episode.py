#!/usr/bin/env python3
"""Copy one episode's measurements out of Prometheus into files, before Prometheus forgets them.

Prometheus keeps 24 h and loses everything if its pod restarts, so every episode is exported
the moment it ends. Raw files are never edited afterwards; labels (ΔSLO) are computed from them
in a separate step, so a change to the ΔSLO formula never requires re-running experiments.

Writes to <out>/<episode_id>/:
  services.csv.gz   one row per service per 5 s step: rps, errors, p50/p95/p99, CPU, memory,
                    CPU-cap throttling, restarts, ready            <- node features + SLO channels
  edges.csv.gz      one row per caller->callee per 5 s step: rps, failed rps   <- the graph
  client.csv.gz     every load-generator request in the episode (what users saw)
  events.json       Kubernetes events in the episode (kills, restarts, scheduling)
  meta.json         the window boundaries plus whatever the caller passed in --meta

Windows are labelled on every row: B0 (healthy baseline), B1 (just before the action),
M (after the action), or "-" for time between windows (fault ramp-up, action grace).

Standard library only.
  export_episode.py --id ep_test --b0 T0 T1 --b1 T2 T3 --m T4 T5 [--meta extra.json]
  (times are Unix seconds)
"""
import argparse, csv, glob, gzip, json, os, subprocess, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arcenv

PROM = arcenv.PROM_URL
STEP = 5
NS = "train-ticket"
SERVER = 'span_kind="SPAN_KIND_SERVER"'
C = f'namespace="{NS}",container=~"ts-.*-service"'

# name -> (PromQL, label that identifies the service).
# Lookback windows must hold >= 2 scrapes or rate() returns nothing (the first test export came
# out empty because the collector was scraped every 15 s against a 15 s window). Trace metrics
# are scraped every 5 s -> 20 s window (4 samples); cAdvisor every 15 s -> 45 s window (3 samples).
TR, RS = "20s", "45s"
SERVICE_QUERIES = {
    "rps":       (f'sum by (service_name) (rate(traces_span_metrics_calls_total{{{SERVER}}}[{TR}]))', "service_name"),
    "err_rps":   (f'sum by (service_name) (rate(traces_span_metrics_calls_total{{{SERVER},status_code="STATUS_CODE_ERROR"}}[{TR}]))', "service_name"),
    "p50_ms":    (f'histogram_quantile(0.50, sum by (service_name, le) (rate(traces_span_metrics_duration_milliseconds_bucket{{{SERVER}}}[{TR}])))', "service_name"),
    "p95_ms":    (f'histogram_quantile(0.95, sum by (service_name, le) (rate(traces_span_metrics_duration_milliseconds_bucket{{{SERVER}}}[{TR}])))', "service_name"),
    "p99_ms":    (f'histogram_quantile(0.99, sum by (service_name, le) (rate(traces_span_metrics_duration_milliseconds_bucket{{{SERVER}}}[{TR}])))', "service_name"),
    "cpu_cores": (f'sum by (container) (rate(container_cpu_usage_seconds_total{{{C}}}[{RS}]))', "container"),
    "mem_mb":    (f'sum by (container) (container_memory_working_set_bytes{{{C}}}) / 1048576', "container"),
    "throttled": (f'sum by (container) (rate(container_cpu_cfs_throttled_periods_total{{{C}}}[{RS}])) / '
                  f'sum by (container) (rate(container_cpu_cfs_periods_total{{{C}}}[{RS}]))', "container"),
    "restarts":  (f'sum by (container) (kube_pod_container_status_restarts_total{{namespace="{NS}",container=~"ts-.*-service"}})', "container"),
    "ready":     (f'min by (container) (kube_pod_container_status_ready{{namespace="{NS}",container=~"ts-.*-service"}})', "container"),
}
# Raw cumulative counters, for exact pooled statistics over a whole window (the labels use these;
# averaging per-step p95s of a service with ~4 requests per step was pure noise). key = bucket
# upper bound in ms ("le"), or "calls" / "errors".
COUNTER_QUERIES = {
    "le":     (f'sum by (service_name, le) (traces_span_metrics_duration_milliseconds_bucket{{{SERVER}}})', "le"),
    "calls":  (f'sum by (service_name) (traces_span_metrics_calls_total{{{SERVER}}})', None),
    "errors": (f'sum by (service_name) (traces_span_metrics_calls_total{{{SERVER},status_code="STATUS_CODE_ERROR"}})', None),
}
# Label v2 needs latency per OPERATION (span name) and split by status, so each request can be
# classed "bad" exactly: every error, plus every success slower than that operation's threshold.
# (Per service only, the gateway looked slower whenever a window happened to hold more bookings.)
OP_QUERY = (f'sum by (service_name, span_name, status_code, le) '
            f'(traces_span_metrics_duration_milliseconds_bucket{{{SERVER}}})')
# Callers' failed calls into each service: a killed service records no server spans at all, so
# its damage is only visible from the caller side.
EDGE_FAILED_CUM = 'sum by (client, server) (traces_service_graph_request_failed_total)'
EDGE_QUERIES = {
    "rps":        f'sum by (client, server) (rate(traces_service_graph_request_total[{TR}]))',
    "failed_rps": f'sum by (client, server) (rate(traces_service_graph_request_failed_total[{TR}]))',
}


def prom_range(q, start, end):
    url = PROM + "/api/v1/query_range?" + urllib.parse.urlencode(
        {"query": q, "start": start, "end": end, "step": STEP})
    with urllib.request.urlopen(url, timeout=60) as r:
        body = json.load(r)
    if body.get("status") != "success":
        raise RuntimeError(f"Prometheus error for {q[:60]}…: {body}")
    return body["data"]["result"]


def window_of(t, w):
    for name in ("B0", "B1", "M"):
        if w[name][0] <= t <= w[name][1]:
            return name
    return "-"


def num(v):
    try:
        f = float(v)
        return None if f != f or f in (float("inf"), float("-inf")) else round(f, 4)
    except (TypeError, ValueError):
        return None


def export_services(start, end, w, path):
    grid = {}  # (t, service) -> {field: value}
    for field, (q, label) in SERVICE_QUERIES.items():
        for series in prom_range(q, start, end):
            svc = series["metric"].get(label)
            if not svc:
                continue
            for t, v in series["values"]:
                grid.setdefault((int(t), svc), {})[field] = num(v)
    fields = list(SERVICE_QUERIES)
    with gzip.open(path, "wt", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["t", "window", "service"] + fields)
        for (t, svc) in sorted(grid):
            row = grid[(t, svc)]
            wr.writerow([t, window_of(t, w), svc] + [row.get(k) for k in fields])
    return len(grid), len({s for _, s in grid})


def export_counters(start, end, w, path):
    # start one step early so the first step of the first window has a previous value to diff against
    rows = []
    for kind, (q, label) in COUNTER_QUERIES.items():
        for series in prom_range(q, start - STEP, end):
            svc = series["metric"].get("service_name")
            key = series["metric"].get(label) if label else kind
            for t, v in series["values"]:
                rows.append((int(t), svc, key, num(v)))
    rows.sort(key=lambda r: (r[0], r[1] or "", r[2]))
    with gzip.open(path, "wt", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["t", "window", "service", "key", "value"])
        for t, svc, key, v in rows:
            wr.writerow([t, window_of(t, w), svc, key, v])
    return len(rows)


def export_op_counters(start, end, w, path):
    """Cumulative bucket counters per (service, operation, status, le), plus callers' cumulative
    failed calls per edge. Only series that change inside the episode are kept (the rest are flat)."""
    rows = []
    for series in prom_range(OP_QUERY, start - STEP, end):
        m = series["metric"]
        vals = [(int(t), num(v)) for t, v in series["values"]]
        if len({v for _, v in vals}) <= 1:
            continue
        st = "error" if m.get("status_code") == "STATUS_CODE_ERROR" else "ok"
        for t, v in vals:
            rows.append((t, m.get("service_name"), m.get("span_name"), st, m.get("le"), v))
    for series in prom_range(EDGE_FAILED_CUM, start - STEP, end):
        m = series["metric"]
        vals = [(int(t), num(v)) for t, v in series["values"]]
        if len({v for _, v in vals}) <= 1:
            continue
        for t, v in vals:
            rows.append((t, m.get("server"), "caller:" + str(m.get("client")), "failed", "", v))
    rows.sort(key=lambda r: (r[0], str(r[1]), str(r[2]), r[3], str(r[4])))
    with gzip.open(path, "wt", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["t", "window", "service", "op", "status", "le", "value"])
        for t, svc, op, st, le, v in rows:
            wr.writerow([t, window_of(t, w), svc, op, st, le, v])
    return len(rows)


def export_edges(start, end, w, path):
    grid = {}
    for field, q in EDGE_QUERIES.items():
        for series in prom_range(q, start, end):
            m = series["metric"]
            for t, v in series["values"]:
                grid.setdefault((int(t), m.get("client"), m.get("server")), {})[field] = num(v)
    with gzip.open(path, "wt", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["t", "window", "client", "server", "rps", "failed_rps"])
        for k in sorted(grid, key=lambda k: (k[0], str(k[1]), str(k[2]))):
            wr.writerow([k[0], window_of(k[0], w), k[1], k[2], grid[k].get("rps"), grid[k].get("failed_rps")])
    return len(grid), len({(k[1], k[2]) for k in grid})


def export_client(start, end, w, path, loadgen_dir):
    rows = []
    for fn in glob.glob(os.path.join(os.path.expanduser(loadgen_dir), "run-*", "requests.jsonl")):
        if os.path.getmtime(fn) < start:
            continue
        with open(fn) as f:
            for line in f:
                r = json.loads(line)
                if start <= r["t"] <= end:
                    rows.append(r)
    rows.sort(key=lambda r: r["t"])
    with gzip.open(path, "wt", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["t", "window", "op", "detail", "http", "ms", "ok", "err"])
        for r in rows:
            wr.writerow([r["t"], window_of(r["t"], w), r["op"], r.get("detail", ""), r["http"], r["ms"],
                         int(bool(r["ok"])), r.get("err", "")])
    return len(rows)


def export_events(start, end, path):
    out = subprocess.run(arcenv.K + ["get", "events", "-o", "json"],
                         capture_output=True, text=True).stdout or '{"items":[]}'
    keep = []
    for e in json.loads(out)["items"]:
        ts = e.get("lastTimestamp") or e.get("eventTime") or (e.get("metadata") or {}).get("creationTimestamp")
        if not ts:
            continue
        t = time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
        if start <= t <= end:
            keep.append({"t": t, "type": e.get("type"), "reason": e.get("reason"),
                         "object": f'{e["involvedObject"].get("kind")}/{e["involvedObject"].get("name")}',
                         "message": (e.get("message") or "")[:300], "count": e.get("count")})
    json.dump(sorted(keep, key=lambda x: x["t"]), open(path, "w"), indent=1)
    return len(keep)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--id", required=True)
    p.add_argument("--b0", nargs=2, type=float, required=True, metavar=("START", "END"))
    p.add_argument("--b1", nargs=2, type=float, required=True, metavar=("START", "END"))
    p.add_argument("--m", nargs=2, type=float, required=True, metavar=("START", "END"))
    p.add_argument("--meta", help="JSON file with fault/action/outcome fields to store alongside")
    p.add_argument("--out", default=arcenv.RAW)
    p.add_argument("--loadgen-dir", default=arcenv.LOADGEN_DIR)
    a = p.parse_args()

    w = {"B0": a.b0, "B1": a.b1, "M": a.m}
    start, end = min(x[0] for x in w.values()), max(x[1] for x in w.values())
    d = os.path.join(os.path.expanduser(a.out), a.id)
    os.makedirs(d, exist_ok=True)
    t0 = time.time()
    n_s, n_svc = export_services(start, end, w, os.path.join(d, "services.csv.gz"))
    n_e, n_edge = export_edges(start, end, w, os.path.join(d, "edges.csv.gz"))
    n_k = export_counters(start, end, w, os.path.join(d, "counters.csv.gz"))
    n_o = export_op_counters(start, end, w, os.path.join(d, "op_counters.csv.gz"))
    n_c = export_client(start, end, w, os.path.join(d, "client.csv.gz"), a.loadgen_dir)
    n_ev = export_events(start, end, os.path.join(d, "events.json"))
    meta = json.load(open(a.meta)) if a.meta else {}
    import socket
    meta.update({"episode_id": a.id, "windows": w, "step_s": STEP, "prometheus": PROM,
                 "cluster": arcenv.CLUSTER, "host": socket.gethostname(),
                 "exported_at": time.time(), "exporter_version": 3,
                 "counts": {"service_rows": n_s, "services": n_svc, "edge_rows": n_e, "edges": n_edge,
                            "counter_rows": n_k, "op_counter_rows": n_o,
                            "client_requests": n_c, "k8s_events": n_ev}})
    json.dump(meta, open(os.path.join(d, "meta.json"), "w"), indent=1)
    size = sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d))
    print(f"{a.id}: {n_svc} services x {n_s // max(n_svc, 1)} steps, {n_edge} edges, {n_c} client requests, "
          f"{n_ev} k8s events -> {d} ({size / 1024:.0f} KB, {time.time() - t0:.1f}s)")
    # An export with no trace data means the collector or its scrape is broken; never let that
    # pass silently (the first exports came out empty because of a 60 s flush + 15 s scrape).
    if n_o == 0 or n_edge == 0:
        print(f"WARNING {a.id}: no span metrics ({n_o} op-counter rows, {n_edge} edges). Check the collector "
              f"and that Prometheus scrapes it every 5 s (ops/health.sh).")
        sys.exit(4)


if __name__ == "__main__":
    main()
