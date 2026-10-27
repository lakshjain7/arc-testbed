#!/usr/bin/env bash
# Stop THIS cluster's load generator. Uses the pid file, and also finds generators by process (a restart can leave
# the pid file pointing at nothing while an old generator keeps running: lab finding F26, 25-26 Oct 2026).
# A generator belongs to this cluster when its environment says ARC_CLUSTER=<this cluster> (the first cluster, "arc",
# is also the default for a process that never set it).
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
PF="$ARC_DATA/loadgen/loadgen.pid"
pids=""
[ -f "$PF" ] && kill -0 "$(cat "$PF")" 2>/dev/null && pids="$(cat "$PF")"
for p in $(pgrep -f 'loadgen(_boutique)?\.py' 2>/dev/null); do
  [ "$p" = "$$" ] && continue
  c=$(tr '\0' '\n' < /proc/$p/environ 2>/dev/null | sed -n 's/^ARC_CLUSTER=//p')
  [ "${c:-arc}" = "$ARC_CLUSTER" ] && pids="$pids $p"
done
pids=$(echo $pids | tr ' ' '\n' | sort -u | tr '\n' ' ')
if [ -n "${pids// /}" ]; then
  kill $pids && echo "stopped load generator for $ARC_CLUSTER (pid $pids)"
  sleep 2
else
  echo "no load generator running for $ARC_CLUSTER"
fi
rm -f "$PF"
