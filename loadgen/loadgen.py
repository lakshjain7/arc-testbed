#!/usr/bin/env python3
"""ARC load generator for Train Ticket.

Open-loop: requests are *started* on a fixed random schedule (Poisson arrivals at
--rate per second) no matter how slow earlier ones are. A closed-loop generator
waits for each reply before sending the next, so when a fault slows the system it
quietly sends less traffic and hides the damage. Open-loop keeps the offered load
constant, which is what a before/after (B1 vs M) comparison needs.

Traffic mix (default, "core"): search 55%, view orders 15%, book 20%, pay 10%. These four flows
touch the 20 core services. Bookings never ask for food or insurance.
More flows exist for the wider system (batch 2); each needs extra services running:
  search2 / book2 / orders2   the slower train types (K, Z, T): ts-travel2-service, ts-preserve-other-service
A mix is given as --mix (or ARC_MIX) either by name ("core", "wide") or in full ("search=40,book=15,...").

Outputs, under --out (default <ARC_DATA_ROOT>/<ARC_CLUSTER>/loadgen, i.e. ~/arc-data/arc/loadgen):
  run-<timestamp>/requests.jsonl  one line per request: when, what, HTTP code, ms, business ok
  status.json                     rolling 30 s summary, rewritten every 2 s (the viewer shows it)

Standard library only, so it runs anywhere Python 3.8+ is installed.

  python3 loadgen.py --rate 2                  # run until Ctrl+C
  python3 loadgen.py --rate 2 --duration 300   # 5 minutes
"""
import argparse, datetime, json, os, random, signal, sys, threading, time, urllib.error, urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor

# City pairs that return trains (checked 2026-09-28), with the trains on each.
ROUTES = [
    ("shanghai", "suzhou", ["D1345"]),
    ("suzhou", "shanghai", ["G1234", "G1236", "G1237"]),
    ("nanjing", "shanghai", ["G1234", "G1235", "G1236"]),
    ("nanjing", "suzhou", ["G1234", "G1236"]),
    ("nanjing", "wuxi", ["G1234"]),
]
# The same for the other train types (travel2), checked 2026-10-11.
ROUTES2 = [
    ("shanghai", "nanjing", ["Z1234"]), ("shanghai", "taiyuan", ["T1235", "Z1234"]), ("nanjing", "taiyuan", ["Z1234"]),
    ("nanjing", "beijing", ["Z1235"]), ("nanjing", "xuzhou", ["Z1235"]), ("xuzhou", "beijing", ["Z1235"]),
    ("taiyuan", "shanghai", ["Z1236"]), ("taiyuan", "shijiazhuang", ["Z1236"]), ("shijiazhuang", "shanghai", ["Z1236"]),
    ("shanghaihongqiao", "hangzhou", ["K1345"]), ("shanghaihongqiao", "jiaxingnan", ["K1345"]), ("jiaxingnan", "hangzhou", ["K1345"]),
]
MIXES = {
    "core": "search=55,orders=15,book=20,pay=10",
    "wide": "search=40,search2=13,orders=10,orders2=5,book=14,book2=6,pay=12",
}
USER, PASSWORD = "fdse_microservice", "111111"
PAY_MAX_AGE_S = 300


class Session:
    """One logged-in user. Re-logs in every 20 min or after a 401/403."""

    def __init__(self, base, timeout):
        self.base, self.timeout = base, timeout
        self.lock = threading.Lock()
        self.token = self.user_id = None
        self.contacts = []
        self.logged_at = 0.0

    def ensure(self, force=False):
        with self.lock:
            if not force and self.token and time.time() - self.logged_at < 1200:
                return
            code, body, _ = call(self.base, "POST", "/api/v1/users/login",
                                 {"username": USER, "password": PASSWORD}, None, 60)
            if not body or not body.get("data"):
                raise RuntimeError("login failed (HTTP %s)" % code)
            self.token, self.user_id = body["data"]["token"], body["data"]["userId"]
            _, c, _ = call(self.base, "GET", "/api/v1/contactservice/contacts/account/" + self.user_id,
                           None, self.token, 60)
            self.contacts = [x["id"] for x in (c or {}).get("data") or []]
            self.logged_at = time.time()


def call(base, method, path, body, token, timeout):
    """Returns (http_code, parsed_json_or_None, seconds). http_code 0 = no response (timeout/refused)."""
    req = urllib.request.Request(base + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code, text = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, text = e.code, e.read()
    except Exception as e:  # timeout, connection refused/reset
        return 0, {"_error": type(e).__name__}, time.time() - t0
    try:
        return code, json.loads(text), time.time() - t0
    except Exception:
        return code, None, time.time() - t0


class Generator:
    def __init__(self, a):
        self.a = a
        self.rng = random.Random(a.seed)
        self.s = Session(a.base, a.timeout)
        # (orderId, trainNumber, seen_at) from "orders". Only orders first seen in the last PAY_MAX_AGE_S
        # are paid: ops/reset-data.sh deletes orders older than 10 min between episodes, and paying a
        # deleted order would show up as a false business failure.
        # The order list is NOT in time order, so the whole list is scanned. (Reading only its last 50
        # entries starved the pay flow for 10 minutes at a time: 13 of 52 pilot episodes had no payment.)
        self.unpaid = deque()
        self.claimed = set()                     # orders already queued or paid, so none is paid twice
        self.baselined = set()                   # order lists looked at once: what was already there is old, skip it
        self.recent = deque()                    # (t_end, op, ok, ms) for the rolling summary
        self.lock = threading.Lock()
        self.inflight = 0
        self.totals = {"sent": 0, "ok": 0, "failed": 0, "shed": 0}
        ops, weights = zip(*[(k, float(v)) for k, v in (x.split("=") for x in MIXES.get(a.mix, a.mix).split(","))])
        for o in ops:
            if not hasattr(self, "op_" + o):
                sys.exit(f"unknown flow '{o}' in --mix")
        self.ops, self.weights = ops, weights
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.run_dir = os.path.join(os.path.expanduser(a.out), "run-" + stamp)
        os.makedirs(self.run_dir, exist_ok=True)
        self.log = open(os.path.join(self.run_dir, "requests.jsonl"), "a", buffering=1)
        self.status_path = os.path.join(os.path.expanduser(a.out), "status.json")
        self.pool = ThreadPoolExecutor(max_workers=a.max_inflight)
        self.stop = threading.Event()
        self.started = time.time()

    # ---- the four user actions -------------------------------------------------
    def op_search(self):
        frm, to, _ = self.rng.choice(ROUTES)
        day = self._date(1, 7)
        code, b, dt = call(self.a.base, "POST", "/api/v1/travelservice/trips/left",
                           {"startPlace": frm, "endPlace": to, "departureTime": day}, self.s.token, self.a.timeout)
        ok = bool(b) and b.get("status") == 1 and len(b.get("data") or []) > 0
        return code, ok, dt, f"{frm}-{to}", None if ok else _why(b)

    def _order_list(self, path, kind):
        code, b, dt = call(self.a.base, "POST", path,
                           {"loginId": self.s.user_id, "enableStateQuery": False,
                            "enableTravelDateQuery": False, "enableBoughtDateQuery": False},
                           self.s.token, self.a.timeout)
        ok = bool(b) and b.get("status") == 1
        if ok:
            with self.lock:
                now = time.time()
                for o in (b.get("data") or []):
                    if o.get("status") == 0 and o.get("id") and o["id"] not in self.claimed:
                        self.claimed.add(o["id"])
                        if kind in self.baselined:   # new since the previous look, so it is fresh
                            self.unpaid.append((o["id"], o.get("trainNumber"), now))
                self.baselined.add(kind)
        return code, ok, dt, "", None if ok else _why(b)

    def op_orders(self):
        return self._order_list("/api/v1/orderservice/order/refresh", "orders")

    def op_orders2(self):                         # orders on the other train types live in their own service
        return self._order_list("/api/v1/orderOtherService/orderOther/refresh", "orders2")

    def _book(self, path, routes):
        frm, to, trains = self.rng.choice(routes)
        train = self.rng.choice(trains)
        body = {"accountId": self.s.user_id, "contactsId": self.rng.choice(self.s.contacts or [""]),
                "tripId": train, "seatType": self.rng.choice([2, 3]), "loginToken": self.s.token,
                "date": self._date(1, 30), "from": frm, "to": to,
                "assurance": 0, "foodType": 0, "isWithin": False}
        code, b, dt = call(self.a.base, "POST", path, body, self.s.token, self.a.timeout)
        ok = bool(b) and b.get("status") == 1
        return code, ok, dt, f"{train}:{frm}-{to}", None if ok else _why(b)

    def op_book(self):
        return self._book("/api/v1/preserveservice/preserve", ROUTES)

    def op_book2(self):
        return self._book("/api/v1/preserveotherservice/preserveOther", ROUTES2)

    def op_search2(self):
        frm, to, _ = self.rng.choice(ROUTES2)
        code, b, dt = call(self.a.base, "POST", "/api/v1/travel2service/trips/left",
                           {"startPlace": frm, "endPlace": to, "departureTime": self._date(1, 7)}, self.s.token, self.a.timeout)
        ok = bool(b) and b.get("status") == 1 and len(b.get("data") or []) > 0
        return code, ok, dt, f"{frm}-{to}", None if ok else _why(b)

    def op_pay(self):
        oid, train, _ = self.unpaid.popleft()     # run() only picks "pay" when a fresh order exists
        code, b, dt = call(self.a.base, "POST", "/api/v1/inside_pay_service/inside_payment",
                           {"orderId": oid, "tripId": train}, self.s.token, self.a.timeout)
        ok = bool(b) and b.get("status") == 1
        return code, ok, dt, train or "", None if ok else _why(b)

    def _date(self, lo, hi):
        # Spread bookings over a month so no single train/date fills up and slows the seat queries.
        return (datetime.date.today() + datetime.timedelta(days=self.rng.randint(lo, hi))).isoformat()

    # ---- scheduling ----------------------------------------------------------
    def fire(self, op):
        try:
            if op != "login":
                self.s.ensure()
            code, ok, dt, detail, err = getattr(self, "op_" + op)()
            if code in (401, 403):
                self.s.ensure(force=True)
        except Exception as e:
            code, ok, dt, detail, err = 0, False, 0.0, "", type(e).__name__
        t_end = time.time()
        rec = {"t": round(t_end - dt, 3), "op": op, "detail": detail, "http": code,
               "ms": round(dt * 1000, 1), "ok": ok}
        if err:
            rec["err"] = str(err)[:120]
        with self.lock:
            self.log.write(json.dumps(rec) + "\n")
            self.inflight -= 1
            self.totals["ok" if ok else "failed"] += 1
            self.recent.append((t_end, op, ok, dt * 1000))

    def run(self):
        self.s.ensure()
        threading.Thread(target=self.reporter, daemon=True).start()
        next_t = time.time()
        end = self.started + self.a.duration if self.a.duration else float("inf")
        while not self.stop.is_set() and time.time() < end:
            next_t += self.rng.expovariate(self.a.rate)          # Poisson arrivals
            delay = next_t - time.time()
            if delay > 0:
                self.stop.wait(delay)
            op = self.rng.choices(self.ops, self.weights)[0]
            if op == "pay":
                with self.lock:
                    while self.unpaid and time.time() - self.unpaid[0][2] > PAY_MAX_AGE_S:
                        self.unpaid.popleft()                   # too old: may have been cleaned up
                    if not self.unpaid:
                        op = "search"                           # nothing to pay yet: behave like a browsing user
            with self.lock:
                self.totals["sent"] += 1
                if self.inflight >= self.a.max_inflight:
                    self.totals["shed"] += 1                    # client can't keep up: record, don't queue
                    self.log.write(json.dumps({"t": round(time.time(), 3), "op": op, "http": 0, "ms": 0,
                                               "ok": False, "err": "client_saturated"}) + "\n")
                    continue
                self.inflight += 1
            self.pool.submit(self.fire, op)
        self.stop.set()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.write_status(final=True)
        self.log.close()

    # ---- live summary --------------------------------------------------------
    def summary(self, window=30.0):
        now = time.time()
        with self.lock:
            while self.recent and now - self.recent[0][0] > 120:
                self.recent.popleft()
            rows = [r for r in self.recent if now - r[0] <= window]
            inflight, totals = self.inflight, dict(self.totals)
        per_op = {}
        for op in self.ops:
            ms = sorted(r[3] for r in rows if r[1] == op)
            bad = sum(1 for r in rows if r[1] == op and not r[2])
            per_op[op] = {"n": len(ms), "failed": bad,
                          "p50_ms": round(_pct(ms, 50)) if ms else None,
                          "p95_ms": round(_pct(ms, 95)) if ms else None}
        all_ms = sorted(r[3] for r in rows)
        return {"updated": now, "running_s": round(now - self.started), "rate_target": self.a.rate,
                "rate_actual": round(len(rows) / window, 2), "window_s": window, "inflight": inflight,
                "failed_pct": round(100 * sum(1 for r in rows if not r[2]) / len(rows), 1) if rows else None,
                "p95_ms": round(_pct(all_ms, 95)) if all_ms else None, "per_op": per_op,
                "totals": totals, "unpaid_pool": len(self.unpaid), "run_dir": self.run_dir}

    def write_status(self, final=False):
        st = self.summary()
        st["state"] = "stopped" if final else "running"
        tmp = self.status_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(st, f)
        os.replace(tmp, self.status_path)
        return st

    def reporter(self):
        last_print = 0
        while not self.stop.is_set():
            st = self.write_status()
            if time.time() - last_print >= self.a.print_every:
                last_print = time.time()
                ops = "  ".join(f"{k}:{v['n']}/{v['failed']}✗ p95={v['p95_ms']}" for k, v in st["per_op"].items())
                print(f"[{st['running_s']:>5}s] {st['rate_actual']:.1f} req/s  failed={st['failed_pct']}%  "
                      f"p95={st['p95_ms']}ms  inflight={st['inflight']}  | {ops}", flush=True)
            self.stop.wait(2)


def _pct(sorted_vals, p):
    k = (len(sorted_vals) - 1) * p / 100
    f = int(k)
    return sorted_vals[f] if f + 1 >= len(sorted_vals) else sorted_vals[f] + (sorted_vals[f + 1] - sorted_vals[f]) * (k - f)


def _why(b):
    if not b:
        return "no JSON body"
    return b.get("_error") or b.get("msg") or "status=%s" % b.get("status")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    idx = int(os.environ.get("ARC_INDEX", "0"))
    ui_port = os.environ.get("UI_PORT", str(32677 + 10 * idx))
    data = os.path.join(os.path.expanduser(os.environ.get("ARC_DATA_ROOT", "~/arc-data")),
                        os.environ.get("ARC_CLUSTER", "arc"), "loadgen")
    p.add_argument("--base", default=f"http://localhost:{ui_port}", help="Train Ticket UI address")
    p.add_argument("--rate", type=float, default=2.0, help="requests started per second (open-loop)")
    p.add_argument("--mix", default=os.environ.get("ARC_MIX", "core"),
                   help="'core' (default), 'wide', or flows with weights, e.g. search=55,orders=15,book=20,pay=10")
    p.add_argument("--duration", type=float, default=0, help="seconds; 0 = until Ctrl+C")
    p.add_argument("--timeout", type=float, default=15, help="a request slower than this counts as failed")
    p.add_argument("--max-inflight", type=int, default=64, help="cap on requests waiting at once")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--out", default=data, help="default: <ARC_DATA_ROOT>/<ARC_CLUSTER>/loadgen")
    p.add_argument("--print-every", type=float, default=10)
    a = p.parse_args()
    g = Generator(a)
    pidfile = os.path.join(os.path.expanduser(a.out), "loadgen.pid")     # lets stop-loadgen.sh stop THIS cluster's generator
    with open(pidfile, "w") as f:
        f.write(str(os.getpid()))
    signal.signal(signal.SIGTERM, lambda *_: g.stop.set())
    print(f"load generator: {a.rate} req/s, mix {a.mix}, timeout {a.timeout}s -> {g.run_dir}", flush=True)
    try:
        g.run()
    except KeyboardInterrupt:
        g.stop.set()
    st = g.write_status(final=True)
    print(f"done. totals {st['totals']}  log: {g.run_dir}/requests.jsonl", flush=True)


if __name__ == "__main__":
    main()
