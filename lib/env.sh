#!/usr/bin/env bash
# Shared settings for every ARC script. Source it:   . "$(dirname "$0")/../lib/env.sh"
#
# One machine can run several independent clusters. Each is chosen with two variables:
#   ARC_CLUSTER   name of the kind cluster            (default: arc)
#   ARC_INDEX     0, 1, 2 ... gives each cluster its own host ports and data folder
# Example, second cluster:   ARC_CLUSTER=arc2 ARC_INDEX=1 ./setup/setup-cluster.sh
export PATH="$HOME/.local/bin:$PATH"

export ARC_CLUSTER="${ARC_CLUSTER:-arc}"
export ARC_INDEX="${ARC_INDEX:-0}"
export ARC_ROOT="${ARC_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# Host ports (all on localhost). The cluster's kind config maps them to fixed NodePorts.
export UI_PORT="${UI_PORT:-$((32677 + 10 * ARC_INDEX))}"        # Train Ticket website / API
export PROM_PORT="${PROM_PORT:-$((19090 + ARC_INDEX))}"          # Prometheus
export GRAFANA_PORT="${GRAFANA_PORT:-$((13000 + ARC_INDEX))}"    # Grafana
export VIEWER_PORT="${VIEWER_PORT:-$((8090 + ARC_INDEX))}"       # live graph viewer
export UI_URL="http://localhost:${UI_PORT}"
export PROM_URL="${PROM_URL:-http://localhost:${PROM_PORT}}"

# Data. Raw episodes are never edited; labels are recomputed from them.
export ARC_DATA_ROOT="${ARC_DATA_ROOT:-$HOME/arc-data}"
export ARC_DATA="${ARC_DATA_ROOT}/${ARC_CLUSTER}"                # raw/  loadgen/  logs/
export ARC_CALIB="${ARC_CALIB:-${ARC_DATA_ROOT}/calibration}"    # thresholds, shared by clusters on this machine
mkdir -p "$ARC_DATA/raw" "$ARC_DATA/loadgen" "$ARC_DATA/logs" "$ARC_CALIB"

export KCTX="kind-${ARC_CLUSTER}"
export NS="train-ticket"
K="kubectl --context ${KCTX} -n ${NS}"
KS="kubectl --context ${KCTX} -n kube-system"

# The 20 services on the search / book / pay / order-list path (the "core" profile).
CORE_SERVICES="ts-config-service ts-verification-code-service ts-auth-service ts-user-service
ts-station-service ts-train-service ts-route-service ts-price-service ts-basic-service
ts-order-service ts-order-other-service ts-seat-service ts-travel-service ts-security-service
ts-contacts-service ts-preserve-service ts-inside-payment-service ts-payment-service
ts-notification-service ts-gateway-service"

avail_mb() { free -m | awk '/^Mem:/{print $7}'; }
say() { echo "$(date +%T) $*"; }
