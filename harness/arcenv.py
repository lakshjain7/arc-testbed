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
NS = "train-ticket"
K = ["kubectl", "--context", KCTX, "-n", NS]

PILOT_TARGETS = ["ts-seat-service", "ts-order-service", "ts-travel-service", "ts-basic-service",
                 "ts-preserve-service", "ts-station-service"]


def script(*parts):
    """Path of a file inside the repository, e.g. script("ops", "reset-data.sh")."""
    return os.path.join(ROOT, *parts)
