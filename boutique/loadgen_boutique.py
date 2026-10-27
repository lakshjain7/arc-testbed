#!/usr/bin/env python3
"""ARC load generator for Online Boutique.

Same open-loop engine, same output files and the same rolling status.json as loadgen/loadgen.py (it reuses
that Generator, so the harness reads both alike); only the user flows differ. A flow is one HTTP request to
the storefront, which fans out to the other services over gRPC:

  home      the start page                          frontend -> productcatalog, currency, cart, recommendation, ad
  browse    one product page                        frontend -> productcatalog, currency, cart, recommendation, ad
  currency  change the display currency             frontend -> currency (then a redirect to home)
  cart      view the cart                           frontend -> cart, productcatalog, currency, recommendation, shipping
  add       put a product in the cart               frontend -> productcatalog, cart
  checkout  add a product, then place the order     frontend -> checkout -> cart, productcatalog, currency, shipping, payment, email

Every virtual user is a session cookie drawn from a pool of 50, so carts persist across requests as for real users.

  python3 loadgen_boutique.py --rate 4 --duration 300
"""
import os, random, sys, time, urllib.error, urllib.parse, urllib.request, uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "loadgen"))
os.environ.setdefault("ARC_MIX", "boutique")
idx = os.environ.get("ARC_INDEX", "1")
os.environ.setdefault("ARC_CLUSTER", "boutique")
os.environ.setdefault("ARC_INDEX", idx)
os.environ.setdefault("UI_PORT", str(32677 + 10 * int(idx)))
import loadgen as L

PRODUCTS = ["OLJCESPC7Z", "66VCHSJNUP", "1YMWWN1N4O", "L9ECAV7KIM", "2ZYFJ3GM2N", "0PUK6V6EV0", "LS4PSXUNUM", "9SIQT8TOJO", "6E92ZMYYFZ"]
CURRENCIES = ["EUR", "USD", "JPY", "CAD", "GBP", "TRY"]
# checkout is the only flow that reaches checkout, payment, email and shipping: at 8 req/s it needs enough weight for
# those services to see the 30 requests per 30 s window the labels require (smoke test: 14 % at 4 req/s left them "inconclusive")
L.MIXES["boutique"] = "browse=34,home=12,currency=6,add=14,cart=14,checkout=20"
L.MIX_EXTRAS["boutique"] = ""
USERS = [str(uuid.uuid4()) for _ in range(50)]


class NoSession:
    """Boutique has no login; the session is a cookie chosen per request."""
    def __init__(self, base, timeout):
        self.base, self.timeout = base, timeout

    def ensure(self, force=False):
        pass


def hcall(base, method, path, timeout, user, form=None):
    """Returns (http_code, seconds). http_code 0 = no response (timeout/refused). Redirects are followed."""
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    req = urllib.request.Request(base + path, method=method, data=data)
    req.add_header("Cookie", "shop_session-id=" + user)
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            return r.status, time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t0
    except Exception:
        return 0, time.time() - t0


class BoutiqueGenerator(L.Generator):
    def _go(self, method, path, form=None, user=None):
        user = user or self.rng.choice(USERS)
        code, dt = hcall(self.a.base, method, path, self.a.timeout, user, form)
        return code, dt

    def _res(self, code, dt, detail):
        ok = code == 200
        return code, ok, dt, detail, None if ok else "http %s" % code

    def op_home(self):
        c, dt = self._go("GET", "/")
        return self._res(c, dt, "")

    def op_browse(self):
        p = self.rng.choice(PRODUCTS)
        c, dt = self._go("GET", "/product/" + p)
        return self._res(c, dt, p)

    def op_currency(self):
        cur = self.rng.choice(CURRENCIES)
        c, dt = self._go("POST", "/setCurrency", {"currency_code": cur})
        return self._res(c, dt, cur)

    def op_cart(self):
        c, dt = self._go("GET", "/cart")
        return self._res(c, dt, "")

    def op_add(self):
        p = self.rng.choice(PRODUCTS)
        c, dt = self._go("POST", "/cart", {"product_id": p, "quantity": str(self.rng.randint(1, 3))})
        return self._res(c, dt, p)

    def op_checkout(self):
        user = self.rng.choice(USERS)
        p = self.rng.choice(PRODUCTS)
        c1, dt1 = self._go("POST", "/cart", {"product_id": p, "quantity": "1"}, user)
        if c1 != 200:
            return self._res(c1, dt1, "add " + p)
        c2, dt2 = self._go("POST", "/cart/checkout", {
            "email": "someone@example.com", "street_address": "1600 Amphitheatre Parkway", "zip_code": "94043",
            "city": "Mountain View", "state": "CA", "country": "United States",
            "credit_card_number": "4432801561520454", "credit_card_expiration_month": "1",
            "credit_card_expiration_year": str(time.localtime().tm_year + 2), "credit_card_cvv": "672"}, user)
        return self._res(c2, dt1 + dt2, "checkout " + p)


L.Session = NoSession
L.Generator = BoutiqueGenerator

if __name__ == "__main__":
    L.main()
