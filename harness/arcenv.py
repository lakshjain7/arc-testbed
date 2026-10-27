"""Shared settings for the Python side; mirrors lib/env.sh.

    ARC_CLUSTER   kind cluster name (default "arc")
    ARC_INDEX     0, 1, 2 ...: each cluster gets its own host ports and data folder
"""
import os

CLUSTER = os.environ.get("ARC_CLUSTER", "arc")
INDEX = int(os.environ.get("ARC_INDEX", "0"))
ROOT = os.environ.get("ARC_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

UI_PORT = int(os.environ.get("UI_PORT", 32677 + 10 * INDEX))
PROM_PORT = int(os.environ.get("PROM_PORT", 19090 + INDEX))
UI_URL = f"http://localhost:{UI_PORT}"
PROM_URL = os.environ.get("PROM_URL", f"http://localhost:{PROM_PORT}")

DATA_ROOT = os.path.expanduser(os.environ.get("ARC_DATA_ROOT", "~/arc-data"))
DATA = os.path.join(DATA_ROOT, CLUSTER)
RAW = os.path.join(DATA, "raw")
LOADGEN_DIR = os.path.join(DATA, "loadgen")
LOGS = os.path.join(DATA, "logs")
CALIB = os.path.expanduser(os.environ.get("ARC_CALIB", os.path.join(DATA_ROOT, "calibration")))
for _d in (RAW, LOADGEN_DIR, LOGS, CALIB):
    os.makedirs(_d, exist_ok=True)

KCTX = f"kind-{CLUSTER}"
# The application under test. "trainticket" (default) or "boutique" (Google's Online Boutique, second system).
APP = os.environ.get("ARC_APP", "trainticket")
NS = "boutique" if APP == "boutique" else "train-ticket"
K = ["kubectl", "--context", KCTX, "-n", NS]

if APP == "boutique":
    # frontend is left out: it is the only entry point, so any fault or action on it breaks every flow at once
    PILOT_TARGETS = ["productcatalogservice", "currencyservice", "recommendationservice", "checkoutservice",
                     "cartservice", "shippingservice", "paymentservice", "adservice", "emailservice"]
    SERVICE_SERVER_RE = "(ad|cart|checkout|currency|email|payment|productcatalog|recommendation|shipping)service|frontend"
    LOADGEN_SCRIPT = ("boutique", "loadgen_boutique.py")
    RESET_SCRIPT = ("boutique", "reset-state.sh")
    BASE_CPU = "1"                      # CPU limit every service has in the deployment (setup-boutique.sh)
else:
    PILOT_TARGETS = ["ts-seat-service", "ts-order-service", "ts-travel-service", "ts-basic-service",
                     "ts-preserve-service", "ts-station-service"]
    SERVICE_SERVER_RE = "ts-.*"
    LOADGEN_SCRIPT = ("loadgen", "loadgen.py")
    RESET_SCRIPT = ("ops", "reset-data.sh")
    BASE_CPU = "2"


def pod_sel(svc):
    """PromQL label selector for one service's container (Boutique's containers are all called "server")."""
    if APP == "boutique":
        return f'namespace="{NS}",pod=~"{svc}-[^-]+-[^-]+",container="server"'
    return f'container="{svc}"'


def script(*parts):
    """Path of a file inside the repository, e.g. script("ops", "reset-data.sh")."""
    return os.path.join(ROOT, *parts)
