#!/usr/bin/env bash
# Stop THIS cluster's load generator (uses its pid file; other clusters are not touched).
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
PF="$ARC_DATA/loadgen/loadgen.pid"
if [ -f "$PF" ] && kill -0 "$(cat "$PF")" 2>/dev/null; then
  kill "$(cat "$PF")" && echo "stopped load generator for $ARC_CLUSTER (pid $(cat "$PF"))"
  sleep 2
else
  echo "no load generator running for $ARC_CLUSTER"
fi
rm -f "$PF"
