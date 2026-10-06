#!/usr/bin/env python3
"""ARC live service-graph viewer.

Serves index.html on VIEWER_PORT (8090 + ARC_INDEX), proxies /api/* to this cluster's Prometheus,
lists pod status via kubectl, and can send one search or one booking through the
Train Ticket UI so you can watch the edges light up.
"""
import datetime, json, os, subprocess, sys, time, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "harness"))
import arcenv

PROM = arcenv.PROM_URL
UI = arcenv.UI_URL
PORT = int(os.environ.get("VIEWER_PORT", 8090 + arcenv.INDEX))
LOADGEN_STATUS = Path(arcenv.LOADGEN_DIR) / "status.json"
KUBECTL = arcenv.K
_pods = {"t": 0, "data": []}


def http_json(url, body=None, token=None, timeout=90):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code, text = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        code, text = e.code, e.read().decode(errors="replace")
    except Exception as e:  # timeout, refused
        code, text = 0, str(e)
    try:
        data = json.loads(text)
    except Exception:
        data = None
    return code, data, round(time.time() - t0, 2)


def login():
    code, d, _ = http_json(UI + "/api/v1/users/login",
                           {"username": "fdse_microservice", "password": "111111"})
    if not d or not d.get("data"):
        raise RuntimeError("login failed (HTTP %s)" % code)
    return d["data"]["token"], d["data"]["userId"]


def do_search():
    tok, _ = login()
    day = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    code, d, secs = http_json(UI + "/api/v1/travelservice/trips/left",
                              {"startPlace": "shanghai", "endPlace": "suzhou", "departureTime": day}, tok)
    n = len(d.get("data") or []) if d else 0
    return {"what": "search", "http": code, "seconds": secs, "detail": "%d trips found" % n}


def do_booking():
    tok, uid = login()
    day = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    _, c, _ = http_json(UI + "/api/v1/contactservice/contacts/account/" + uid, None, tok)
    cid = c["data"][0]["id"]
    body = {"accountId": uid, "contactsId": cid, "tripId": "D1345", "seatType": 2, "loginToken": tok,
            "date": day, "from": "shanghai", "to": "suzhou", "assurance": 0, "foodType": 0, "isWithin": False}
    code, d, secs = http_json(UI + "/api/v1/preserveservice/preserve", body, tok, timeout=180)
    return {"what": "booking", "http": code, "seconds": secs,
            "detail": (d or {}).get("msg", "no JSON body (gateway timeout?)")}


def pods():
    if time.time() - _pods["t"] > 5:
        out = subprocess.run(KUBECTL + ["get", "pods", "-o", "json"], capture_output=True, text=True).stdout
        res = []
        for p in json.loads(out or '{"items":[]}')["items"]:
            app = p["metadata"].get("labels", {}).get("app") or p["metadata"]["name"]
            cs = (p["status"].get("containerStatuses") or [{}])[0]
            res.append({"app": app, "ready": bool(cs.get("ready")), "restarts": cs.get("restartCount", 0),
                        "phase": p["status"].get("phase")})
        _pods.update(t=time.time(), data=res)
    return _pods["data"]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path in ("/", "/index.html"):
            return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if u.path.startswith("/api/"):
            try:
                with urllib.request.urlopen(PROM + self.path, timeout=20) as r:
                    return self.send(200, r.read())
            except Exception as e:
                return self.send(502, {"error": "Prometheus unreachable: %s" % e})
        if u.path == "/pods":
            return self.send(200, pods())
        if u.path == "/loadgen":
            try:
                return self.send(200, LOADGEN_STATUS.read_bytes())
            except OSError:
                return self.send(200, {"state": "never run"})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        try:
            if self.path == "/act/search":
                return self.send(200, do_search())
            if self.path == "/act/book":
                return self.send(200, do_booking())
        except Exception as e:
            return self.send(200, {"what": self.path.rsplit("/", 1)[-1], "http": 0, "seconds": 0, "detail": str(e)})
        self.send(404, {"error": "not found"})


if __name__ == "__main__":
    print(f"viewer for cluster {arcenv.CLUSTER} on http://localhost:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
