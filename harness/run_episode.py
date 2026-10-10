#!/usr/bin/env python3
"""Run one ARC episode end to end and export it.

  health gate -> database reset -> steady-state gate -> B0 (120 s) -> fault -> wait (delay)
  -> B1 = last 30 s -> action -> 5 s grace -> M (180 s) -> remove fault -> undo action -> export
  -> label -> health gate again (an unhealthy cluster marks the episode "discarded")

The cluster is chosen with ARC_CLUSTER / ARC_INDEX (lib/env.sh). A continuous load generator
should already be running for that cluster; if none is, the episode starts its own.

Faults (each verified after injection): none, pod-kill, network-delay (ms), net-loss (percent),
        cpu-squeeze (limit = multiple of recent CPU use), blackhole.   --fault-param sets the level.
Actions (each with a checked post-condition, undone after M): noop, restart-pod, rollout-restart,
        scale-up, cpu-bump, drain.
A no-fault no-op episode measures how much the numbers move when nothing happens: the noise
floor that real damage has to stand out from.

  run_episode.py --fault none --action noop
  run_episode.py --fault pod-kill --fault-target ts-seat-service --action noop --delay 60
  run_episode.py --fault network-delay --fault-param 100 --fault-target ts-order-service \
                 --action restart-pod --target ts-order-service --delay 90
"""
import argparse, json, os, random, signal, subprocess, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arcenv

ARC = arcenv.ROOT
K = arcenv.K
# M = 180 s: surge-type actions (rollout-restart, scale-up) do their damage 80-130 s after the action
# (pod Ready 70-85 s, callers' 35 s instance cache, then the cold JVM); 120 s cut that off.
B0_S, B1_S, GRACE_S, M_S = 120, 30, 5, 180
MIN_FREE_MB = 1000              # surge-type actions start an extra JVM (~0.45 GB)
# Steady-state gate before B0: after idle or restarts the JVMs are cold (first requests time out,
# p95 11 s in a measured B0). Wait until the load generator's last 30 s show no failures and
# p95 under STEADY_P95_MS, STEADY_CHECKS times in a row (10 s apart), for at most STEADY_MAX_S.
STEADY_P95_MS, STEADY_CHECKS, STEADY_MAX_S = 3000, 3, 360
LOADGEN_STATUS = os.path.join(arcenv.LOADGEN_DIR, "status.json")
TARGETS = arcenv.PILOT_TARGETS
# quarantine (NetworkPolicy) is kept but NOT used: the smoke test showed callers keep their already-open
# keep-alive connections, so the policy blocked nothing (0 failed searches). drain replaces it: the
# target's instance is disabled in Nacos, so callers stop routing to it once their cache refreshes.
ACTIONS = ["noop", "restart-pod", "rollout-restart", "scale-up", "cpu-bump", "drain", "quarantine"]
SURGE_ACTIONS = {"rollout-restart", "scale-up"}
REPLACING_ACTIONS = {"restart-pod", "rollout-restart"}


def sh(args, check=True):
    r = subprocess.run(args, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(args)} -> {r.stderr.strip()[:300]}")
    return r.stdout


def log(msg):
    try:
        print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)
    except OSError:          # the terminal went away; the cleanup that is logging must still finish
        pass


def _stop(signum, frame):
    """A closed terminal or `kill` must end like Ctrl+C: through the `finally` that removes the fault."""
    for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(s, signal.SIG_IGN)     # a second signal must not interrupt the cleanup
    raise KeyboardInterrupt


def wait_until(t):
    while (d := t - time.time()) > 0:
        time.sleep(min(d, 5))


# ---- health -------------------------------------------------------------------------------
def health():
    """Returns (ok, reason). Every ts-* pod 1/1 and not restarting, every service in Nacos."""
    pods = json.loads(sh(K + ["get", "pods", "-o", "json"]))["items"]
    bad = []
    for p in pods:
        name = p["metadata"]["name"]
        if not name.startswith("ts-") or p["status"].get("phase") == "Succeeded":
            continue
        cs = (p["status"].get("containerStatuses") or [{}])[0]
        if not cs.get("ready"):
            bad.append(name)
    if bad:
        return False, "not ready: " + ", ".join(bad)
    out = sh(["bash", arcenv.script("ops", "nacos-health.sh")], check=False)
    missing = out.strip().splitlines()[-1].split(":", 1)[-1].strip() if out else "?"
    if missing:
        return False, "missing from Nacos: " + missing
    return True, "ok"


def loadgen_status():
    try:
        st = json.load(open(LOADGEN_STATUS))
    except (OSError, ValueError):
        return None
    fresh = st.get("state") == "running" and time.time() - st.get("updated", 0) < 10
    return st if fresh else None


def wait_steady():
    """Block until the load generator reports steady, healthy traffic. Returns (ok, seconds waited)."""
    t0, good = time.time(), 0
    while time.time() - t0 < STEADY_MAX_S:
        st = loadgen_status()
        if st and st.get("failed_pct") == 0 and st.get("p95_ms") is not None and st["p95_ms"] < STEADY_P95_MS \
                and st.get("rate_actual", 0) > 0.5 * st.get("rate_target", 1):
            good += 1
            if good >= STEADY_CHECKS:
                return True, round(time.time() - t0)
        else:
            good = 0
        time.sleep(10)
    return False, round(time.time() - t0)


def orders_count():
    out = sh(K + ["exec", "tsdb-mysql-0", "-c", "mysql", "--", "mysql", "-uroot", "-N", "-e",
                  "select count(*), sum(status=1) from ts.orders"], check=False)
    try:
        total, paid = out.split()
        return {"orders": int(total), "paid": int(paid)}
    except ValueError:
        return None


# ---- actions ------------------------------------------------------------------------------
def pod_of(svc):
    items = json.loads(sh(K + ["get", "pods", "-l", f"app={svc}", "-o", "json"]))["items"]
    running = [p for p in items if p["status"].get("phase") == "Running"
               and not p["metadata"].get("deletionTimestamp")]      # skip pods already being killed
    return running[0] if running else None


def free_mb():
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def apply_action(action, target, ep):
    """Apply the action; return (applied: bool, details: dict). Post-conditions are checked."""
    if action == "noop":
        return True, {}
    if action == "rollout-restart":
        gen = json.loads(sh(K + ["get", "deploy", target, "-o", "json"]))["metadata"]["generation"]
        sh(K + ["rollout", "restart", f"deploy/{target}"])
        for _ in range(10):
            d = json.loads(sh(K + ["get", "deploy", target, "-o", "json"]))
            if d["status"].get("observedGeneration", 0) > gen:
                return True, {"generation": d["status"]["observedGeneration"]}
            time.sleep(1)
        return False, {"error": "rollout not observed within 10 s"}
    if action == "scale-up":
        sh(K + ["scale", f"deploy/{target}", "--replicas=2"])
        for _ in range(10):
            items = json.loads(sh(K + ["get", "pods", "-l", f"app={target}", "-o", "json"]))["items"]
            if len([p for p in items if not p["metadata"].get("deletionTimestamp")]) >= 2:
                return True, {"pods": [p["metadata"]["name"] for p in items]}
            time.sleep(1)
        return False, {"error": "second pod not created within 10 s"}
    if action == "cpu-bump":
        p = pod_of(target)
        if not p:
            return False, {"error": "no running pod"}
        rc = p["status"]["containerStatuses"][0].get("restartCount", 0)
        sh(K + ["patch", "pod", p["metadata"]["name"], "--subresource", "resize", "-p",
                json.dumps({"spec": {"containers": [{"name": target, "resources": {"limits": {"cpu": "4"}}}]}})])
        for _ in range(15):
            q = json.loads(sh(K + ["get", "pod", p["metadata"]["name"], "-o", "json"]))
            cs = q["status"]["containerStatuses"][0]
            if (cs.get("resources") or {}).get("limits", {}).get("cpu") == "4" and cs.get("restartCount", 0) == rc:
                return True, {"pod": p["metadata"]["name"]}
            time.sleep(1)
        return False, {"error": "cpu limit not 4 within 15 s, or the container restarted"}
    if action == "drain":
        ok, info = nacos_enable(target, False)
        return ok, info
    if action == "quarantine":
        np_ = {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
               "metadata": {"name": quarantine_name(ep), "namespace": "train-ticket"},
               "spec": {"podSelector": {"matchLabels": {"app": target}}, "policyTypes": ["Ingress"], "ingress": []}}
        r = subprocess.run(K + ["apply", "-f", "-"], input=json.dumps(np_), capture_output=True, text=True)
        return (r.returncode == 0), ({"policy": quarantine_name(ep)} if r.returncode == 0 else {"error": r.stderr[:200]})
    if action == "restart-pod":
        p = pod_of(target)
        if not p:
            return False, {"error": "no running pod"}
        old = p["metadata"]["name"]
        sh(K + ["delete", "pod", old, "--grace-period=0", "--force", "--wait=false"])
        # post-condition: a different pod for the service exists within 30 s
        for _ in range(30):
            q = pod_of(target)
            if q and q["metadata"]["name"] != old:
                return True, {"old_pod": old, "new_pod": q["metadata"]["name"]}
            time.sleep(1)
        return False, {"old_pod": old, "error": "no replacement pod within 30 s"}
    raise ValueError(action)


_DRAINED = {}   # service -> (ip, port): a disabled instance is HIDDEN from Nacos' list API, so re-enabling
               # must use the address saved at drain time (smoke test 7 left station disabled otherwise)


def nacos_enable(svc, enabled):
    """Take a service instance out of (or back into) rotation in Nacos. Verified by reading it back."""
    base = K + ["exec", "nacos-0", "-c", "k8snacos", "--", "curl", "-s"]
    lst = json.loads(sh(base + [f"localhost:8848/nacos/v1/ns/instance/list?serviceName={svc}"], check=False) or "{}")
    hosts = lst.get("hosts") or []
    if hosts:
        h = hosts[0]
    elif svc in _DRAINED:
        h = {"ip": _DRAINED[svc][0], "port": _DRAINED[svc][1]}
    else:
        p = pod_of(svc)          # fallback: the pod's own address and container port
        if not p:
            return False, {"error": "service has no instance in Nacos and no running pod"}
        h = {"ip": p["status"].get("podIP"), "port": p["spec"]["containers"][0]["ports"][0]["containerPort"]}
    if not enabled:
        _DRAINED[svc] = (h["ip"], h["port"])
    flag = "true" if enabled else "false"
    sh(base + ["-X", "PUT", f"localhost:8848/nacos/v1/ns/instance?serviceName={svc}&ip={h['ip']}"
               f"&port={h['port']}&enabled={flag}&ephemeral=true"], check=False)
    for _ in range(10):
        time.sleep(1)
        now = json.loads(sh(base + [f"localhost:8848/nacos/v1/ns/instance/list?serviceName={svc}"], check=False) or "{}")
        hs = now.get("hosts") or []
        # Nacos drops disabled instances from the healthy list, so "no hosts" also means disabled
        if (not enabled and all(not x.get("enabled") for x in hs)) or (enabled and any(x.get("enabled") for x in hs)):
            return True, {"ip": h["ip"], "port": h["port"], "enabled": enabled}
    return False, {"error": f"enabled={flag} not visible after 10 s", "hosts": hs}


def quarantine_name(ep):
    return "arc-q-" + ep.replace("_", "-").lower()[:50]


def reset_action(action, target, ep):
    """Undo the action after M so the next episode starts from the same system. Returns a note."""
    if action == "scale-up":
        sh(K + ["scale", f"deploy/{target}", "--replicas=1"], check=False)
        time.sleep(40)          # callers' instance cache (35 s) must forget the removed pod
        return "scaled back to 1"
    if action == "cpu-bump":
        p = pod_of(target)
        if p:
            sh(K + ["patch", "pod", p["metadata"]["name"], "--subresource", "resize", "-p",
                    json.dumps({"spec": {"containers": [{"name": target, "resources": {"limits": {"cpu": "2"}}}]}})],
               check=False)
        return "cpu limit back to 2"
    if action == "quarantine":
        sh(K + ["delete", "networkpolicy", quarantine_name(ep), "--ignore-not-found"], check=False)
        time.sleep(40)
        return "network policy removed"
    if action == "drain":
        ok, _ = nacos_enable(target, True)
        time.sleep(40)          # callers' instance cache must pick the instance up again
        return f"instance re-enabled in Nacos (verified={ok})"
    return ""


def fault_on_new_pod(fault, chaos_name, target):
    """After a pod-replacing action: is the Chaos Mesh fault also on the NEW pod? (If not, the action
    silently 'cured' a network/stress fault.) None when not applicable."""
    if fault in ("none", "pod-kill"):
        return None
    if fault == "cpu-squeeze":      # a replacement pod gets the Deployment's 2 cores: the squeeze is gone
        p = pod_of(target)
        cpu = ((p or {}).get("status", {}).get("containerStatuses") or [{}])[0].get("resources", {}).get("limits", {}).get("cpu")
        return cpu is not None and cpu_millis(cpu) < 2000
    kind = CHAOS_KIND[fault]
    st = json.loads(sh(K + ["get", kind, chaos_name, "-o", "json"], check=False) or "{}")
    recs = ((st.get("status") or {}).get("experiment") or {}).get("containerRecords") or []
    p = pod_of(target)
    if not p:
        return None
    name = p["metadata"]["name"]
    return any(name in (r.get("id") or "") for r in recs)


# ---- faults (Chaos Mesh) --------------------------------------------------------------------
# cpu-stress (Chaos Mesh StressChaos) is kept for reference but NOT used: the smoke test showed the stress
# processes run outside the target container on kind + cgroup v2 (target never throttled, whole host at
# load 25, every service timing out). cpu-squeeze replaces it: the target's CPU limit is cut in place.
FAULTS = ["none", "pod-kill", "network-delay", "net-loss", "cpu-squeeze", "blackhole", "cpu-stress"]
SQUEEZE_MIN_M = 10        # 10m is the smallest CPU quota Kubernetes enforces. Was 25m: on a fast machine the quiet
                          # services use 6-17m, so every level hit the floor and gave the same limit (lab, 2026-10-10)


def prom_scalar(q):
    import urllib.parse, urllib.request
    try:
        url = arcenv.PROM_URL + "/api/v1/query?" + urllib.parse.urlencode({"query": q})
        with urllib.request.urlopen(url, timeout=20) as r:
            res = json.load(r)["data"]["result"]
        return float(res[0]["value"][1]) if res else None
    except Exception:
        return None
CHAOS_KIND = {"pod-kill": "podchaos", "network-delay": "networkchaos", "net-loss": "networkchaos",
              "blackhole": "networkchaos", "cpu-stress": "stresschaos"}
# Default levels. The pilot's 300 ms delay, 1/4-CPU squeeze and blackhole SATURATED the system (users
# >= 80% bad before the action in 39% of episodes), which hides the action's effect. Milder defaults;
# the campaign draws from several levels per fault (harness/run_campaign.py).
FAULT_DEFAULT_PARAM = {"network-delay": 50, "net-loss": 15, "cpu-squeeze": 2.5}


def chaos_cr(fault, target, name, param):
    sel = {"namespaces": ["train-ticket"], "labelSelectors": {"app": target}}
    md = {"name": name, "namespace": "train-ticket"}
    # duration 30m is only a safety net; every fault is removed explicitly at teardown
    if fault == "pod-kill":
        return {"apiVersion": "chaos-mesh.org/v1alpha1", "kind": "PodChaos", "metadata": md,
                "spec": {"action": "pod-kill", "mode": "one", "gracePeriod": 0, "selector": sel}}
    if fault == "network-delay":
        ms = int(param or FAULT_DEFAULT_PARAM[fault])
        return {"apiVersion": "chaos-mesh.org/v1alpha1", "kind": "NetworkChaos", "metadata": md,
                "spec": {"action": "delay", "mode": "all", "selector": sel, "direction": "to",
                         "delay": {"latency": f"{ms}ms", "jitter": f"{ms // 4}ms", "correlation": "25"},
                         "duration": "30m"}}
    if fault in ("net-loss", "blackhole"):
        pct = "100" if fault == "blackhole" else str(int(param or FAULT_DEFAULT_PARAM[fault]))
        return {"apiVersion": "chaos-mesh.org/v1alpha1", "kind": "NetworkChaos", "metadata": md,
                "spec": {"action": "loss", "mode": "all", "selector": sel, "direction": "to",
                         "loss": {"loss": pct, "correlation": "0" if fault == "blackhole" else "25"},
                         "duration": "30m"}}
    if fault == "cpu-stress":
        return {"apiVersion": "chaos-mesh.org/v1alpha1", "kind": "StressChaos", "metadata": md,
                "spec": {"mode": "all", "selector": sel, "containerNames": [target],
                         "stressors": {"cpu": {"workers": 2, "load": 100}}, "duration": "30m"}}
    raise ValueError(fault)


def cpu_millis(v):
    v = str(v)
    return int(v[:-1]) if v.endswith("m") else int(float(v) * 1000)


def set_cpu_limit(target, cpu, request=None):
    """In-place resize of the running pod's CPU limit (Kubernetes >= 1.33, no restart). Returns (ok, pod).
    Uses the DEFAULT (strategic merge) patch: a --type=merge patch replaces the whole resources block and
    is rejected ("limits cannot be removed"). A limit below the request is invalid, so the request is
    lowered too when needed."""
    p = pod_of(target)
    if not p:
        return False, None
    name = p["metadata"]["name"]
    rc = p["status"]["containerStatuses"][0].get("restartCount", 0)
    res = {"limits": {"cpu": cpu}}
    if request:
        res["requests"] = {"cpu": request}
    sh(K + ["patch", "pod", name, "--subresource", "resize", "-p",
            json.dumps({"spec": {"containers": [{"name": target, "resources": res}]}})], check=False)
    for _ in range(15):
        q = json.loads(sh(K + ["get", "pod", name, "-o", "json"], check=False) or "{}")
        cs = ((q.get("status") or {}).get("containerStatuses") or [{}])[0]
        if (cs.get("resources") or {}).get("limits", {}).get("cpu") == cpu and cs.get("restartCount", 0) == rc:
            return True, name
        time.sleep(1)
    return False, name


def restart_info(svc):
    """(pod uid, container restart count) of a service's pod; (None, 0) when there is none."""
    p = pod_of(svc)
    cs = ((p or {}).get("status", {}).get("containerStatuses") or [{}])[0]
    return (p or {}).get("metadata", {}).get("uid"), cs.get("restartCount", 0)


def apply_fault(fault, target, name, param, used=None):
    """Apply and VERIFY the fault (a silent no-op would corrupt the label). Returns (verified, info)."""
    if fault == "none":
        return True, {}
    if fault == "cpu-squeeze":
        # CPU limit = level x what the service used on AVERAGE over the last 2 min (floor 10m), so the
        # squeeze bites equally hard on busy and quiet services (station uses ~0.03 cores, order ~0.3).
        # A JVM needs short bursts far above its average: a level below ~1 leaves it unable to answer
        # at all (0.5 and 0.35 gave station 90 % bad requests, 2026-10-07). CPU starvation is a cliff:
        # with use measured while healthy, 3x = 0-3 % bad, 2x = 55-100 %, 1.5x = 75-80 % (laptop, 2 req/s).
        # Use one level between 2 and 3, checked with dose_check.py on a busy and a quiet service.
        frac = float(param or FAULT_DEFAULT_PARAM[fault])
        # `used` can be passed in (dose_check measures it once while the service is healthy: right after
        # a previous squeeze the 2-minute average is inflated by the catch-up burst).
        used = used or prom_scalar(f'sum(rate(container_cpu_usage_seconds_total{{container="{target}"}}[2m]))') or 0.1
        lim = f"{max(SQUEEZE_MIN_M, int(used * 1000 * frac))}m"
        ok, pod = set_cpu_limit(target, lim, request=lim if cpu_millis(lim) < 100 else None)
        return ok, {"kind": "in-place resize", "pod": pod, "cpu_limit": lim, "fraction": frac,
                    "cpu_used_before": round(used, 3)}
    before = pod_of(target)
    cr = chaos_cr(fault, target, name, param)
    p = subprocess.run(K + ["apply", "-f", "-"], input=json.dumps(cr), capture_output=True, text=True)
    if p.returncode:
        return False, {"error": p.stderr.strip()[:300]}
    info = {"kind": cr["kind"], "name": name, "param": param}
    if fault == "pod-kill":
        old = before["metadata"]["uid"] if before else None
        for i in range(30):
            q = pod_of(target)
            if q and q["metadata"]["uid"] != old:
                return True, {**info, "old_uid": old, "new_uid": q["metadata"]["uid"], "verified_after_s": i}
            time.sleep(1)
        return False, {**info, "error": "target pod not replaced within 30 s"}
    # NetworkChaos etc.: wait for Chaos Mesh to report the fault injected on every selected pod
    for i in range(30):
        st = json.loads(sh(K + ["get", cr["kind"].lower(), name, "-o", "json"], check=False) or "{}")
        conds = {c["type"]: c["status"] for c in (st.get("status") or {}).get("conditions", [])}
        if conds.get("AllInjected") == "True":
            return True, {**info, "verified_after_s": i}
        time.sleep(1)
    return False, {**info, "error": "not AllInjected within 30 s", "conditions": conds}


def remove_fault(fault, name, target=None):
    """Delete the chaos object and wait until Chaos Mesh has restored the target (finalizer gone)."""
    if fault == "none" or not name:
        return True
    if fault == "cpu-squeeze":
        ok, _ = set_cpu_limit(target, "2", request="100m")   # a replaced pod already has these from its Deployment
        return ok
    kind = CHAOS_KIND[fault]
    r = subprocess.run(K + ["delete", kind, name, "--wait=true", "--timeout=90s"], capture_output=True, text=True)
    if r.returncode and "NotFound" not in r.stderr:
        log(f"teardown stuck; forcing finalizer off: {r.stderr.strip()[:120]}")
        subprocess.run(K + ["annotate", kind, name, "chaos-mesh.chaos-mesh.org/cleanFinalizer=forced", "--overwrite"],
                       capture_output=True)
        subprocess.run(K + ["delete", kind, name, "--wait=true", "--timeout=60s"], capture_output=True)
        return False
    return True


# ---- episode --------------------------------------------------------------------------------
def main():
    for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(s, _stop)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--id")
    p.add_argument("--fault", default="none", choices=FAULTS)
    p.add_argument("--fault-target")
    p.add_argument("--fault-param", help="level: network-delay = latency ms (default 100); net-loss = percent "
                                         "(default 15); cpu-squeeze = CPU limit as a multiple of recent average use (default 2.5)")
    p.add_argument("--action", choices=ACTIONS)
    p.add_argument("--target", help="action target service (default: random from the pilot set)")
    p.add_argument("--delay", type=float, help="seconds from fault to action (default: random 60-300)")
    p.add_argument("--rate", type=float, default=2.0)
    p.add_argument("--seed", type=int)
    a = p.parse_args()

    rng = random.Random(a.seed)
    action = a.action or rng.choice(ACTIONS)
    target = a.target or rng.choice(TARGETS)
    fault_target = a.fault_target or rng.choice(TARGETS)
    delay = a.delay if a.delay is not None else rng.uniform(60, 300)
    ep = a.id or time.strftime("ep_%Y%m%d_%H%M%S")
    chaos_name = "arc-" + ep.replace("_", "-").lower()[:50]
    meta = {"episode_id": ep, "status": "ok", "discard_reason": None,
            "fault_type": a.fault, "fault_target": fault_target if a.fault != "none" else None,
            "fault_param": a.fault_param or FAULT_DEFAULT_PARAM.get(a.fault),
            "action_type": action, "action_target": target if action != "noop" else None,
            "action_on_fault_target": (a.fault != "none" and action != "noop" and target == fault_target),
            "action_delay_s": round(delay, 1), "load_rate": a.rate, "seed": a.seed,
            "m_seconds": M_S, "harness_version": 3}
    log(f"episode {ep} [{arcenv.CLUSTER}]: fault={a.fault}({meta['fault_param']})@{meta['fault_target']} "
        f"action={action}@{target} delay={delay:.0f}s")

    # Health gate. A service that was just blackholed or drained needs a couple of minutes to be
    # back in Nacos, so wait before giving up (the pilot discarded valid episodes for this).
    ok, why, waited_h = wait_healthy(300)
    meta["health_wait_before_s"] = waited_h
    if not ok:
        log(f"health gate FAILED before start (waited {waited_h}s): {why}")
        sys.exit(2)

    # Prefer a load generator that is already running continuously (start one with
    # `loadgen.py --rate 2 &` before a batch), so the system never idles between episodes.
    lg = None
    running = loadgen_status()
    if running:
        meta["load_rate"] = running.get("rate_target")
        log(f"using the running load generator ({running.get('rate_target')} req/s)")
    else:
        lg = subprocess.Popen([sys.executable, arcenv.script("loadgen", "loadgen.py"), "--rate", str(a.rate),
                               "--seed", str(rng.randrange(1 << 30)), "--print-every", "60"],
                              stdout=open(os.path.join(arcenv.LOGS, f"{ep}.loadgen.log"), "w"), stderr=subprocess.STDOUT)
        log(f"started a load generator at {a.rate} req/s (it stops when the episode ends)")
    try:
        # keep the database at a steady size (18 h of load made every request 5-10x slower)
        r = subprocess.run(["bash", arcenv.script("ops", "reset-data.sh"), "10"], capture_output=True, text=True)
        meta["reset_data"] = r.stdout.strip()[-200:]
        log(meta["reset_data"])
        time.sleep(15)
        steady, waited = wait_steady()
        meta["steady_wait_s"] = waited
        if not steady:
            log(f"system never reached steady state in {waited}s; aborting (nothing recorded)")
            sys.exit(3)
        log(f"steady after {waited}s")
        biz_before = orders_count()
        b0 = (time.time(), time.time() + B0_S)
        log("B0 (healthy baseline)"); wait_until(b0[1])

        t_fault = time.time()
        f_ok, f_info = apply_fault(a.fault, fault_target, chaos_name, a.fault_param)
        meta.update(fault_applied_at=t_fault, fault_verified=f_ok, fault_info=f_info)
        rs0 = restart_info(fault_target)        # after the fault is on (a pod-kill has already replaced the pod)
        log(f"fault {a.fault} on {fault_target} verified={f_ok} {f_info}; waiting {delay:.0f}s")
        if not f_ok:
            meta.update(status="discarded", discard_reason="fault not verified")

        t_action = t_fault + delay
        b1 = (t_action - B1_S, t_action)
        wait_until(t_action)
        meta["pods_by_node"] = pods_by_node()
        meta["free_mb_before_action"] = free_mb()
        if action in SURGE_ACTIONS and (meta["free_mb_before_action"] or 0) < MIN_FREE_MB:
            applied, a_info = False, {"error": f"only {meta['free_mb_before_action']} MB free"}
            meta.update(status="discarded", discard_reason="low_memory")
        else:
            applied, a_info = apply_action(action, target, ep)
        meta.update(action_applied_at=time.time(), action_applied=applied, action_info=a_info)
        log(f"action {action} on {target}: applied={applied} {a_info}")
        if not applied and meta["status"] == "ok":
            meta.update(status="discarded", discard_reason="action post-condition failed")
        if applied and action in REPLACING_ACTIONS and target == fault_target:
            time.sleep(5)
            meta["fault_on_new_pod"] = fault_on_new_pod(a.fault, chaos_name, target)
            log(f"fault still on the replacement pod: {meta['fault_on_new_pod']}")

        m = (t_action + GRACE_S, t_action + GRACE_S + M_S)
        log(f"M (after the action, {M_S}s)"); wait_until(m[1])
    finally:
        t_rm = time.time()
        # Did the fault target's container crash or its pod get replaced while the fault was on? A CPU
        # squeeze or a network fault that tips a service into a restart is a different, harsher incident.
        if locals().get("rs0") and a.fault != "none":
            rs1 = restart_info(fault_target)
            meta["fault_target_pod_replaced"] = rs1[0] != rs0[0]
            meta["fault_target_container_restarts"] = None if rs1[0] != rs0[0] else rs1[1] - rs0[1]
        clean = remove_fault(a.fault, chaos_name, fault_target)
        meta.update(fault_removed_at=t_rm, fault_teardown_clean=clean)
        if applied_action_needs_reset(locals()):
            meta["action_reset"] = reset_action(action, target, ep)
            log(f"action reset: {meta['action_reset']}")
        if lg:
            lg.terminate(); lg.wait(timeout=30)
    biz_after = orders_count()
    meta.update(business={"before": biz_before, "after": biz_after}, windows_note="exported below")

    # The episode's own windows are already measured, so slow recovery afterwards does not spoil it;
    # it is recorded, and the NEXT episode's health gate waits for the cluster.
    ok, why, waited_h = wait_healthy(240)
    meta.update(health_after=why, recovery_after_s=waited_h, healthy_after=ok)

    mp = os.path.join(arcenv.LOGS, f"{ep}.meta.json")
    json.dump(meta, open(mp, "w"), indent=1)
    ex = subprocess.run([sys.executable, arcenv.script("harness", "export_episode.py"), "--id", ep,
                         "--b0", str(b0[0]), str(b0[1]), "--b1", str(b1[0]), str(b1[1]),
                         "--m", str(m[0]), str(m[1]), "--meta", mp])
    ep_dir = os.path.join(arcenv.RAW, ep)
    if ex.returncode == 4 and os.path.exists(os.path.join(ep_dir, "meta.json")):   # exported, but no trace data
        saved = json.load(open(os.path.join(ep_dir, "meta.json")))
        saved.update(status="discarded", discard_reason="no span metrics in the export")
        json.dump(saved, open(os.path.join(ep_dir, "meta.json"), "w"), indent=1)
        meta.update(status="discarded", discard_reason="no span metrics in the export")
    elif ex.returncode:
        log(f"export FAILED (exit {ex.returncode}); the episode was not saved")
        sys.exit(5)
    subprocess.run([sys.executable, arcenv.script("harness", "labels_v2.py"), ep_dir, "--quiet"])
    log(f"episode {ep} {meta['status']}" + (f" ({meta['discard_reason']})" if meta["discard_reason"] else ""))


def wait_healthy(max_s):
    """Poll health() until it passes or max_s is over. Returns (ok, reason, seconds waited)."""
    t0 = time.time()
    while True:
        ok, why = health()
        if ok or time.time() - t0 >= max_s:
            return ok, why, round(time.time() - t0)
        time.sleep(15)


def applied_action_needs_reset(scope):
    """True if the action was actually applied and changes state that must be undone after M."""
    return scope.get("applied") and scope.get("action") in ("scale-up", "cpu-bump", "quarantine", "drain")


def pods_by_node():
    """Which node each pod runs on (needed to tell graph damage from 'same machine' damage)."""
    items = json.loads(sh(K + ["get", "pods", "-o", "json"], check=False) or '{"items":[]}')["items"]
    return {p["metadata"].get("labels", {}).get("app", p["metadata"]["name"]): p["spec"].get("nodeName")
            for p in items if p["status"].get("phase") == "Running"}


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("episode stopped on request; its fault was removed and its action undone. Nothing was recorded.")
        sys.exit(130)
