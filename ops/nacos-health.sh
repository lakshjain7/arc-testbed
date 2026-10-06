#!/usr/bin/env bash
# For every running ts-* service: is it registered in Nacos and marked healthy?
# The last line is machine-readable:  MISSING_OR_UNHEALTHY:<space-separated services or empty>
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
missing=""
for s in $($K get deploy --no-headers | awk '$2!="0/0"{print $1}' | grep -E '^ts-.*-service$'); do
  r=$($K exec nacos-0 -c k8snacos -- curl -s -m 5 "localhost:8848/nacos/v1/ns/instance/list?serviceName=$s" 2>/dev/null)
  st=$(echo "$r" | python3 -c "import sys,json
try:
  h=json.load(sys.stdin).get('hosts') or []
  print('%d instance(s), healthy=%s' % (len(h), [x.get('healthy') for x in h]))
except Exception: print('?')")
  case "$st" in 0*|*False*|\?) missing="$missing $s"; flag="  <-- PROBLEM";; *) flag="";; esac
  printf "  %-30s %s%s\n" "$s" "$st" "$flag"
done
echo "MISSING_OR_UNHEALTHY:$missing"
