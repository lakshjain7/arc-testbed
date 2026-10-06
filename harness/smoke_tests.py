#!/usr/bin/env python3
"""Five smoke tests before the pilot (research/06 §5.4). Each checks that a new fault or action
really does what the pilot assumes. Needs the continuous load generator running.

  1 cpu-stress      throttling of the target rises while the fault is on, and falls after removal
  2 quarantine      searches start failing through the blocked service; it stays Ready; recovers
  3 fault survival  300 ms delay on seat, then restart seat: is the fault on the new pod?
  4 blackhole heal  100% loss on station for 3 min; station back in Nacos within 60 s of removal
  5 scale-up reset  order 1 -> 2 -> 1: the surviving pod is the older (warm) one
  6 cpu-squeeze     station's CPU limit cut to 250m: station is throttled, other services are NOT slowed
  7 drain           station disabled in Nacos: searches (which need station) fail; re-enable recovers
  8 cpu-bump        order's CPU limit 2 -> 4 -> 2 in place, with no container restart

  smoke_tests.py [1 2 3 4 5]
"""
import json, os, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_episode as R

PROM = R.arcenv.PROM_URL


def prom(q):
    url = PROM + "/api/v1/query?" + urllib.parse.urlencode({"query": q})
    with urllib.request.urlopen(url, timeout=30) as r:
        res = json.load(r)["data"]["result"]
    return float(res[0]["value"][1]) if res else None


def users(op=None):
    st = R.loadgen_status() or {}
    if op:
        v = (st.get("per_op") or {}).get(op, {})
        return v.get("n"), v.get("failed"), v.get("p50_ms")
    return st.get("failed_pct"), st.get("p95_ms")


def say(msg):
    print(f"{time.strftime('%H:%M:%S')}   {msg}", flush=True)


def result(n, ok, why):
    print(f"==> TEST {n}: {'PASS' if ok else 'FAIL'}  {why}\n", flush=True)
    return ok


def throttle(svc):
    return prom(f'sum(rate(container_cpu_cfs_throttled_periods_total{{container="{svc}"}}[30s])) / '
                f'sum(rate(container_cpu_cfs_periods_total{{container="{svc}"}}[30s]))') or 0.0


def t1():
    svc, name = "ts-station-service", "arc-smoke-stress"
    before = throttle(svc); say(f"station throttled {100*before:.0f}% of periods before")
    ok, info = R.apply_fault("cpu-stress", svc, name, None); say(f"StressChaos verified={ok} {info}")
    time.sleep(60)
    during = throttle(svc); say(f"during stress: throttled {100*during:.0f}%   users p95 {users()[1]} ms")
    R.remove_fault("cpu-stress", name); time.sleep(60)
    after = throttle(svc); say(f"60 s after removal: throttled {100*after:.0f}%")
    return result(1, ok and during > before + 0.2 and after < during / 2,
                  f"throttle {100*before:.0f}% -> {100*during:.0f}% -> {100*after:.0f}%")


def t2():
    svc, ep = "ts-station-service", "smoke_q"
    time.sleep(1)
    n0, f0, _ = users("search"); say(f"search before: {f0}/{n0} failed (last 30 s)")
    ok, info = R.apply_action("quarantine", svc, ep); say(f"NetworkPolicy applied={ok} {info}")
    time.sleep(40)
    n1, f1, p1 = users("search"); pod = R.pod_of(svc)
    ready = bool(pod and pod["status"]["containerStatuses"][0].get("ready"))
    say(f"quarantined: search {f1}/{n1} failed, p50 {p1} ms; station Ready={ready}")
    R.reset_action("quarantine", svc, ep)      # includes the 40 s cache wait
    time.sleep(20)
    n2, f2, _ = users("search"); say(f"after removal: search {f2}/{n2} failed")
    blocked = (f1 or 0) > max(2, 3 * (f0 or 0))
    return result(2, ok and blocked and ready and (f2 or 0) <= max(2, (f1 or 0) // 3),
                  f"search failures {f0} -> {f1} -> {f2}, station stayed Ready={ready}")


def t3():
    svc, name, ep = "ts-seat-service", "arc-smoke-survive", "smoke_s"
    _, _, p0 = users("search"); say(f"search p50 before: {p0} ms")
    ok, info = R.apply_fault("network-delay", svc, name, 300); time.sleep(30)
    _, _, p1 = users("search"); say(f"with 300 ms delay on seat: search p50 {p1} ms (verified={ok})")
    applied, ainfo = R.apply_action("restart-pod", svc, ep); time.sleep(5)
    on_new = R.fault_on_new_pod("network-delay", name, svc)
    say(f"restarted seat ({ainfo.get('new_pod')}); fault on the new pod according to Chaos Mesh: {on_new}")
    say("waiting 150 s for the new seat to become Ready and warm ...")
    time.sleep(150)
    _, _, p2 = users("search"); say(f"after restart: search p50 {p2} ms")
    R.remove_fault("network-delay", name); time.sleep(30)
    _, _, p3 = users("search"); say(f"after removing the fault: search p50 {p3} ms")
    still = p2 is not None and p3 is not None and p2 > p3 + 150
    return result(3, ok and applied, f"fault_on_new_pod (Chaos Mesh records) = {on_new}; "
                  f"latency says the delay {'SURVIVED' if still else 'did NOT survive'} the restart "
                  f"(p50 {p0} -> {p1} -> {p2} -> {p3} ms). Recorded either way; not a pass/fail condition.")


def t4():
    svc, name = "ts-station-service", "arc-smoke-blackhole"
    ok, info = R.apply_fault("blackhole", svc, name, None); say(f"blackhole on station verified={ok}")
    time.sleep(60)
    n1, f1, _ = users("search"); say(f"during blackhole: search {f1}/{n1} failed")
    time.sleep(120)
    R.remove_fault("blackhole", name); t0 = time.time(); say("blackhole removed; waiting for Nacos + searches")
    healthy = False
    while time.time() - t0 < 90:
        h, why = R.health()
        n, f, _ = users("search")
        if h and f is not None and f <= 1:
            healthy = True
            break
        time.sleep(10)
    say(f"recovered={healthy} after {time.time()-t0:.0f}s  ({why})")
    return result(4, ok and (f1 or 0) > 0 and healthy, f"search failures during {f1}, healthy again after {time.time()-t0:.0f}s")


def t5():
    svc, ep = "ts-order-service", "smoke_scale"
    old = R.pod_of(svc)["metadata"]["name"]
    free = R.free_mb(); say(f"free memory {free} MB; order pod {old}")
    if (free or 0) < R.MIN_FREE_MB:
        return result(5, False, f"skipped: only {free} MB free")
    ok, info = R.apply_action("scale-up", svc, ep); say(f"scale-up applied={ok} {info}")
    time.sleep(120)
    R.reset_action("scale-up", svc, ep)
    time.sleep(10)
    items = json.loads(R.sh(R.K + ["get", "pods", "-l", f"app={svc}", "-o", "json"]))["items"]
    alive = [p["metadata"]["name"] for p in items if not p["metadata"].get("deletionTimestamp")]
    say(f"after scale back to 1: {alive}")
    return result(5, ok and alive == [old], f"survivor {'is' if alive == [old] else 'is NOT'} the original warm pod")


def cores(svc):
    return prom(f'sum(rate(container_cpu_usage_seconds_total{{container="{svc}"}}[30s]))') or 0.0


def t6():
    # seat: busy enough (~0.14 cores) that a quarter of its CPU really bites; station uses ~0.03
    svc, others = "ts-seat-service", ["ts-order-service", "ts-station-service"]
    thr0 = throttle(svc); oth0 = {o: throttle(o) for o in others}
    _, p0 = users(); say(f"before: {svc} throttled {100*thr0:.0f}%, users p95 {p0} ms")
    ok, info = R.apply_fault("cpu-squeeze", svc, "smoke", None); say(f"squeeze applied/verified={ok} {info}")
    time.sleep(60)
    thr1 = throttle(svc); oth1 = {o: throttle(o) for o in others}; _, p1 = users()
    say(f"squeezed: {svc} throttled {100*thr1:.0f}%, others {', '.join(f'{o[3:-8]} {100*v:.0f}%' for o, v in oth1.items())}; users p95 {p1} ms")
    R.remove_fault("cpu-squeeze", "smoke", svc); time.sleep(45)
    thr2 = throttle(svc); say(f"restored: {svc} throttled {100*thr2:.0f}%")
    others_ok = all(oth1[o] < oth0[o] + 0.1 for o in others)
    return result(6, ok and thr1 > thr0 + 0.2 and others_ok and thr2 < thr1 / 2,
                  f"{svc} throttle {100*thr0:.0f}% -> {100*thr1:.0f}% -> {100*thr2:.0f}%, other services unaffected={others_ok}")


def t7():
    svc, ep = "ts-station-service", "smoke_drain"
    n0, f0, _ = users("search"); say(f"search before: {f0}/{n0} failed")
    ok, info = R.apply_action("drain", svc, ep); say(f"drain applied={ok} {info}")
    time.sleep(50)          # callers' 35 s instance cache must expire first
    n1, f1, _ = users("search")
    lst = R.sh(R.K + ["exec", "nacos-0", "-c", "k8snacos", "--", "curl", "-s",
                      f"localhost:8848/nacos/v1/ns/instance/list?serviceName={svc}"], check=False)
    say(f"drained: search {f1}/{n1} failed; Nacos now: {lst[:160]}")
    note = R.reset_action("drain", svc, ep); say(note)      # includes a 40 s wait
    time.sleep(20)
    n2, f2, _ = users("search"); say(f"after re-enable: search {f2}/{n2} failed")
    return result(7, ok and (f1 or 0) > max(3, 3 * (f0 or 0)) and (f2 or 0) <= max(2, (f1 or 0) // 3),
                  f"search failures {f0} -> {f1} -> {f2}")


def t8():
    svc, ep = "ts-order-service", "smoke_bump"
    rc0 = R.pod_of(svc)["status"]["containerStatuses"][0].get("restartCount", 0)
    ok, info = R.apply_action("cpu-bump", svc, ep); say(f"cpu-bump applied={ok} {info}")
    lim = R.pod_of(svc)["status"]["containerStatuses"][0].get("resources", {}).get("limits", {}).get("cpu")
    time.sleep(20)
    note = R.reset_action("cpu-bump", svc, ep); time.sleep(5)
    p = R.pod_of(svc)["status"]["containerStatuses"][0]
    back, rc1 = p.get("resources", {}).get("limits", {}).get("cpu"), p.get("restartCount", 0)
    say(f"limit during {lim}, after reset {back}; restarts {rc0} -> {rc1}")
    return result(8, ok and lim == "4" and back == "2" and rc1 == rc0, f"cpu 2 -> {lim} -> {back}, no restart={rc1 == rc0}")


if __name__ == "__main__":
    tests = {"1": t1, "2": t2, "3": t3, "4": t4, "5": t5, "6": t6, "7": t7, "8": t8}
    chosen = sys.argv[1:] or list(tests)
    if not R.loadgen_status():
        sys.exit("start the continuous load generator first")
    out = {}
    for k in chosen:
        print(f"################ TEST {k}: {__doc__.splitlines()[2 + int(k)].strip()}", flush=True)
        try:
            out[k] = tests[k]()
        except Exception as e:
            out[k] = result(k, False, f"crashed: {type(e).__name__}: {e}")
        time.sleep(30)
    print("SMOKE SUMMARY:", {k: ("PASS" if v else "FAIL") for k, v in out.items()}, flush=True)
