#!/usr/bin/env python3
"""ΔSLO label v2 for one episode: the per-service "bad-request ratio" (research/05-damage-label-formulation.md).

A request is BAD if it failed OR it was slower than its operation's latency threshold T[service, op].
One number per service captures both, so a fast failure no longer looks "fast" (the seat-kill episode
showed latency 30x worse while errors fell from 100% to 14%).

  X, N          bad and total requests in a window. For a service with no server spans in a 5 s step
                (e.g. just killed), callers' failed calls into it count as its requests, both N and X.
  B1L           label baseline = the 60 s before the action (the model's input stays the 30 s B1)
  G             grace between the action and M;  M is split into 30 s blocks
  p_hat = X/N,  p_tilde = (X + 0.5) / (N + 1)   (smoothed, so tiny counts don't give 0% or 100%)

  y_mean        p_hat(M) - p_hat(B1L)                          main regression target
  y_peak        max over blocks of p_tilde(b) - p_tilde(B1L)   worst 30 s
  y_excess      X(G+M) - p_hat(B1L) * N(G+M)                   extra bad requests (includes the grace window)
  t_recover_s   seconds from the action until the service is back within DELTA of B1L and stays there
  verdict       per block: LB = delta_b - z * sqrt(phi_s) * SE_b,  UB = delta_b + ...
                harm if max LB > DELTA; no_harm if max UB < DELTA; otherwise inconclusive
                (phi_s and z come from calibrate_v2.py fitted on no-fault no-op episodes)

Stalls (whole-system freezes seen by the load generator) are cut out of B1L and M (±5 s). If more than
25% of M or 50% of B1L is cut, the episode is marked "stalled".
Per client flow (search / orders / book / pay) the same bad-ratio is computed from what users saw;
that is the only place Train Ticket's HTTP-200 business failures are visible.

Each label also carries `saturated_before_action` (users already >= 80% bad in the baseline) and a
`summary` of magnitudes: collateral_peak_sum / collateral_mean_sum over services other than the
action and fault targets, and user_damage (rise of the bad ratio summed over client flows).

  labels_v2.py ~/arc-data/arc/raw/ep_x [--quiet]
"""
import csv, gzip, json, math, os, sys
from collections import defaultdict

VERSION = 2
DELTA = 0.05                      # a 5-point rise in the bad-request ratio is "harm"
BLOCK_S, STEP = 30, 5
B1L_S = 60
LAT_FLOOR_MS = 100
FALLBACK_T_MS = 1000
STALL_TIMEOUTS, STALL_MEDIAN_MS, SLICE_S, STALL_PAD = 2, 1000, 15, 5
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import arcenv

# Thresholds are fitted per MACHINE (latencies differ between the laptop and the lab box) by
# calibrate_v2.py, and live outside the repository in <ARC_DATA_ROOT>/calibration.
SLO_FILE = os.path.join(arcenv.CALIB, "slo_thresholds.json")
CAL_FILE = os.path.join(arcenv.CALIB, "calibration_v2.json")
DEFAULT_CAL = {"z": 2.5, "phi": {}}
SATURATED_BAD = 0.8     # pilot: in 39% of episodes users were already >= 80% bad BEFORE the action,
                        # so no action could show more damage. Flag those; analyse them separately.


def _f(v):
    try:
        x = float(v)
        return None if math.isnan(x) else x
    except (TypeError, ValueError):
        return None


def load_json(p, default):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return default


# ---- reading --------------------------------------------------------------------------------
def step_increments(d):
    """-> per service: list of (t, op, status, le, increment) from cumulative counters (resets handled)."""
    series = defaultdict(list)
    for r in csv.DictReader(gzip.open(os.path.join(d, "op_counters.csv.gz"), "rt")):
        v = _f(r["value"])
        if v is not None:
            series[(r["service"], r["op"], r["status"], r["le"])].append((int(r["t"]), v))
    inc = defaultdict(list)
    for (svc, op, st, le), pts in series.items():
        pts.sort()
        for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
            x = v1 - v0 if v1 >= v0 else v1
            if x:
                inc[svc].append((t1, op, st, le, x))
    return inc


def client_rows(d):
    p = os.path.join(d, "client.csv.gz")
    return list(csv.DictReader(gzip.open(p, "rt"))) if os.path.exists(p) else []


def stall_ranges(rows):
    sl = defaultdict(lambda: {"ms": [], "to": 0})
    for r in rows:
        k = int(float(r["t"]) // SLICE_S)
        sl[k]["ms"].append(float(r["ms"]))
        sl[k]["to"] += r["err"] == "TimeoutError"
    out = []
    for k, s in sorted(sl.items()):
        ms = sorted(s["ms"])
        if s["to"] >= STALL_TIMEOUTS or ms[len(ms) // 2] > STALL_MEDIAN_MS:
            out.append((k * SLICE_S - STALL_PAD, (k + 1) * SLICE_S + STALL_PAD))
    return out


# ---- counting -------------------------------------------------------------------------------
def threshold(slo, svc, op):
    return slo.get(svc, {}).get(op, {}).get("T_ms", FALLBACK_T_MS)


def per_step_counts(incs, svc, slo):
    """-> {t: [N, X]} for one service. Bucket counters are cumulative by le, so for each (op, status):
    N = the +Inf bucket, slow = N - bucket(le = T). Errors are all bad."""
    by = defaultdict(lambda: defaultdict(float))    # (t, op, status) -> {le: inc}
    caller = defaultdict(float)
    for t, op, st, le, x in incs:
        if st == "failed":
            caller[t] += x
        else:
            by[(t, op, st)][le] += x
    steps = defaultdict(lambda: [0.0, 0.0])
    for (t, op, st), les in by.items():
        n = les.get("+Inf", 0.0)
        if st == "error":
            bad = n
        else:
            T = threshold(slo, svc, op)
            under = sum(v for le, v in les.items() if le not in ("+Inf", "") and abs(float(le) - T) < 1e-6)
            bad = max(n - under, 0.0)
        steps[t][0] += n
        steps[t][1] += bad
    for t, x in caller.items():          # service invisible (no server spans): callers' failures are its requests
        if steps[t][0] == 0:
            steps[t][0] += x
            steps[t][1] += x
    return steps


def pooled(steps, keep):
    n = sum(v[0] for t, v in steps.items() if keep(t))
    x = sum(v[1] for t, v in steps.items() if keep(t))
    return n, x


def smooth(x, n):
    return (x + 0.5) / (n + 1)


def se(p1, n1, p0, n0):
    return math.sqrt(p1 * (1 - p1) / max(n1, 1) + p0 * (1 - p0) / max(n0, 1))


# ---- the label ------------------------------------------------------------------------------
def label_episode(d, slo=None, cal=None):
    slo = load_json(SLO_FILE, {}) if slo is None else slo
    cal = load_json(CAL_FILE, DEFAULT_CAL) if cal is None else cal
    meta = json.load(open(os.path.join(d, "meta.json")))
    w = meta["windows"]
    t_act = w["B1"][1]
    m0, m1 = w["M"]
    rows = client_rows(d)
    stalls = stall_ranges(rows)
    # v2.1 (after the pilot): in a FAULT episode, client timeouts are usually caused by the fault itself,
    # not by an ambient laptop freeze; cutting them out discarded most delay/squeeze episodes. Stalls are
    # still recorded, but only cut out (and only mark an episode "stalled") when there is no fault.
    stalls_seen = stalls
    if meta.get("fault_type") not in (None, "none"):
        stalls = []
    in_stall = lambda t: any(a <= t - STEP and t <= b or a <= t <= b for a, b in stalls)

    b1l = lambda t: t_act - B1L_S < t <= t_act and not in_stall(t)
    g_m = lambda t: t_act < t <= m1 and not in_stall(t)
    m_ok = lambda t: m0 < t <= m1 and not in_stall(t)
    n_m_steps = int((m1 - m0) // STEP)
    m_cut = sum(1 for k in range(n_m_steps) if in_stall(m0 + (k + 1) * STEP)) / max(n_m_steps, 1)
    b_cut = sum(1 for k in range(B1L_S // STEP) if in_stall(t_act - B1L_S + (k + 1) * STEP)) / (B1L_S // STEP)
    stalled = m_cut > 0.25 or b_cut > 0.5

    blocks = []
    b = m0
    while b + BLOCK_S <= m1 + 1e-6:
        blocks.append((b, b + BLOCK_S))
        b += BLOCK_S

    z = cal.get("z", DEFAULT_CAL["z"])
    out = {}
    incs = step_increments(d)
    for svc in sorted(incs):
        steps = per_step_counts(incs[svc], svc, slo)
        nB, xB = pooled(steps, b1l)
        nM, xM = pooled(steps, m_ok)
        nGM, xGM = pooled(steps, g_m)
        phi = cal.get("phi", {}).get(svc, 1.0)
        rec = {"N_B1L": round(nB), "X_B1L": round(xB), "N_M": round(nM), "X_M": round(xM)}
        if nB == 0 or nM == 0:
            rec.update(verdict="no_data")
            out[svc] = rec
            continue
        pB, pM = xB / nB, xM / nM
        tB = smooth(xB, nB)
        rec.update(p_B1L=pB, p_M=pM, y_mean=pM - pB,
                   se_mean=math.sqrt(phi) * se(smooth(xM, nM), nM, tB, nB),
                   y_excess=xGM - pB * nGM)
        deltas, lbs, ubs = [], [], []
        for a, bb in blocks:
            n, x = pooled(steps, lambda t, a=a, bb=bb: a < t <= bb and not in_stall(t))
            if n == 0:
                deltas.append(None)
                continue
            tb = smooth(x, n)
            dlt = tb - tB
            s = math.sqrt(phi) * se(tb, n, tB, nB)
            deltas.append(dlt)
            lbs.append(dlt - z * s)
            ubs.append(dlt + z * s)
        valid = [x for x in deltas if x is not None]
        rec["y_peak"] = max(valid) if valid else None
        rec["block_deltas"] = deltas
        # recovery: first block from which every later block is within DELTA of the baseline
        t_rec = None
        for i in range(len(deltas)):
            if all(x is None or x <= DELTA for x in deltas[i:]):
                t_rec = (blocks[i][0] - t_act) if i else 0
                break
        rec["t_recover_s"] = t_rec if t_rec is not None else (m1 - t_act)
        rec["recovered_by_end"] = t_rec is not None
        if lbs and max(lbs) > DELTA:
            rec["verdict"] = "harm"
        elif ubs and max(ubs) < DELTA:
            rec["verdict"] = "no_harm"
        else:
            rec["verdict"] = "inconclusive"
        out[svc] = rec

    flows = client_flows(rows, t_act, m0, m1, slo, in_stall)
    b1_bad = [f["p_B1L"] for f in flows.values() if f.get("p_B1L") is not None]
    saturated = bool(b1_bad) and max(b1_bad) >= SATURATED_BAD
    # magnitudes for the whole episode (the pilot showed these carry the signal, not the binary verdict)
    excl = {meta.get("action_target"), meta.get("fault_target")}
    coll = [v for s, v in out.items() if s not in excl and v["verdict"] != "no_data"]
    summary = {
        "collateral_peak_sum": sum(max(0.0, v.get("y_peak") or 0.0) for v in coll),
        "collateral_mean_sum": sum(max(0.0, v.get("y_mean") or 0.0) for v in coll),
        "collateral_harmed": sum(v["verdict"] == "harm" for v in coll),
        "user_damage": sum(max(0.0, f["y_mean"]) for f in flows.values() if f.get("y_mean") is not None),
    }
    labels = {"episode_id": meta.get("episode_id"), "label_version": VERSION,
              "fault": meta.get("fault_type"), "fault_target": meta.get("fault_target"),
              "action": meta.get("action_type"), "action_target": meta.get("action_target"),
              "stalled": stalled, "stall_cut": {"M": round(m_cut, 2), "B1L": round(b_cut, 2)},
              "stall_slices_seen": len(stalls_seen), "stall_rule": "cut only when fault == none (v2.1)",
              "params": {"DELTA": DELTA, "z": z, "B1L_S": B1L_S, "BLOCK_S": BLOCK_S,
                         "slo_table": bool(slo), "calibrated": os.path.exists(CAL_FILE)},
              "saturated_before_action": saturated, "summary": summary,
              "services": out, "client_flows": flows}
    json.dump(labels, open(os.path.join(d, f"labels_v{VERSION}.json"), "w"), indent=1)
    return labels


def client_flows(rows, t_act, m0, m1, slo, in_stall):
    tc = slo.get("_client", {})
    res = {}
    for op in sorted({r["op"] for r in rows}):
        T = tc.get(op, {}).get("T_ms", FALLBACK_T_MS)
        def ratio(keep):
            rs = [r for r in rows if r["op"] == op and keep(float(r["t"])) and not in_stall(float(r["t"]))]
            bad = sum(1 for r in rs if r["ok"] != "1" or float(r["ms"]) > T)
            return len(rs), bad
        nB, xB = ratio(lambda t: t_act - B1L_S < t <= t_act)
        nM, xM = ratio(lambda t: m0 < t <= m1)
        res[op] = {"N_B1L": nB, "N_M": nM, "p_B1L": xB / nB if nB else None, "p_M": xM / nM if nM else None,
                   "y_mean": (xM / nM - xB / nB) if nB and nM else None, "T_ms": T}
    return res


def show(lab):
    pct = lambda v: "    -" if v is None else f"{100*v:5.1f}"
    print(f"{lab['episode_id']}: fault={lab['fault']}@{lab['fault_target']} action={lab['action']}@{lab['action_target']}"
          f"  stalled={lab['stalled']}  (slo table={'yes' if lab['params']['slo_table'] else 'NO, 1 s fallback'}, "
          f"calibrated={'yes' if lab['params']['calibrated'] else 'no'}, z={lab['params']['z']})")
    print(f"  {'service':26s} {'N B1L/M':>10s} {'bad% B1L→M':>12s} {'Δmean':>7s} {'Δpeak':>7s} {'excess':>7s} {'recover':>8s} verdict")
    for s, v in lab["services"].items():
        if v["verdict"] == "no_data":
            print(f"  {s:26s} {v['N_B1L']:4d}/{v['N_M']:<5d}  (no requests in a window)")
            continue
        print(f"  {s:26s} {v['N_B1L']:4d}/{v['N_M']:<5d} {pct(v['p_B1L'])}→{pct(v['p_M'])} {pct(v['y_mean'])}  "
              f"{pct(v['y_peak'])}  {v['y_excess']:6.0f} {v['t_recover_s']:6.0f}s  {v['verdict'].upper() if v['verdict']=='harm' else v['verdict']}")
    c = [v["verdict"] for v in lab["services"].values()]
    print(f"  -> harm {c.count('harm')}, no_harm {c.count('no_harm')}, inconclusive {c.count('inconclusive')}, no_data {c.count('no_data')}")
    print("  users (per flow, bad = failed or slower than healthy q99): " +
          ", ".join(f"{op} {pct(f['p_B1L']).strip()}→{pct(f['p_M']).strip()}%" for op, f in lab["client_flows"].items()))


if __name__ == "__main__":
    lab = label_episode(os.path.expanduser(sys.argv[1]))
    if "--quiet" not in sys.argv:
        show(lab)
