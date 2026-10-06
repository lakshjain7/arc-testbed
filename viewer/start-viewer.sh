#!/usr/bin/env bash
# Live service graph of one cluster in the browser (nodes = services, edges = who calls whom).
#   viewer/start-viewer.sh            then open http://localhost:8090   (8091 for ARC_INDEX=1, ...)
#   viewer/start-viewer.sh stop
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
PF="$ARC_DATA/logs/viewer.pid"
[ -f "$PF" ] && kill "$(cat "$PF")" 2>/dev/null; rm -f "$PF"
[ "${1:-}" = "stop" ] && { echo "viewer stopped"; exit 0; }
# A cluster made by setup/setup-cluster.sh publishes Prometheus on $PROM_PORT by itself. If it does not
# answer (older cluster), fall back to a port-forward.
if ! curl -s -m 3 -o /dev/null "$PROM_URL/-/ready"; then
  nohup kubectl --context "$KCTX" -n kube-system port-forward svc/prometheus "$PROM_PORT:9090" >"$ARC_DATA/logs/prom-forward.log" 2>&1 &
  sleep 2
fi
nohup python3 "$ARC_ROOT/viewer/server.py" >"$ARC_DATA/logs/viewer.log" 2>&1 &
echo $! >"$PF"
sleep 1
echo "viewer for $ARC_CLUSTER: http://localhost:$VIEWER_PORT     website: $UI_URL     Prometheus: $PROM_URL"
