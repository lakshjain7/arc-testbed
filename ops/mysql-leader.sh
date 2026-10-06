#!/usr/bin/env bash
# Print the tsdb MySQL pod that accepts writes (read_only = 0). Replicas are read-only, and the
# leader changes after restarts, so never hard-code it.
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
for p in $($K get pods --no-headers 2>/dev/null | awk '/^tsdb-mysql-[0-9]+/{print $1}'); do
  ro=$($K exec "$p" -c mysql -- mysql -uroot -N -e "select @@global.read_only" 2>/dev/null | tr -d '\r')
  [ "$ro" = "0" ] && { echo "$p"; exit 0; }
done
exit 1
