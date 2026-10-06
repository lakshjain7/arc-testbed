#!/usr/bin/env bash
# Open the Train Ticket database (read from any copy).
#   ops/db.sh                    interactive mysql prompt (type exit to leave)
#   ops/db.sh "select ..."       run one query and print a table
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
if [ -n "${1:-}" ]; then
  $K exec tsdb-mysql-0 -c mysql -- mysql -uroot -t ts -e "$1" 2>&1 | grep -v "Using a password"
else
  $K exec -it tsdb-mysql-0 -c mysql -- mysql -uroot ts
fi
