#!/usr/bin/env bash
# One-screen health check of a cluster: pods, Nacos, CPU limits, Prometheus, MySQL, memory, and
# (with --book) a real login + search + booking that must change the database.
#   ops/health.sh [--book]
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
echo "=== cluster $ARC_CLUSTER (UI :$UI_PORT, Prometheus :$PROM_PORT) ==="
echo "--- Train Ticket pods by READY ---"
$K get pods --no-headers | grep '^ts-' | awk '{print $2}' | sort | uniq -c
$K get pods --no-headers | grep -v Completed | awk '{split($2,a,"/"); if (a[1]!=a[2]) print "  not ready:", $1, $2, $3}'
bash "$ARC_ROOT/ops/nacos-health.sh" | tail -1
echo "--- CPU limit of running services (want 2) ---"
for s in $($K get deploy --no-headers | awk '$2!="0/0"{print $1}' | grep -E '^ts-.*-service$'); do
  c=$($K get deploy "$s" -o jsonpath='{.spec.template.spec.containers[0].resources.limits.cpu}')
  [ "$c" = "2" ] || echo "  $s has cpu limit $c"
done; echo "  checked"
echo "--- telemetry agent on running services ---"
n=0; miss=""
for s in $($K get deploy --no-headers | awk '$2!="0/0"{print $1}' | grep -E '^ts-.*-service$'); do
  $K get deploy "$s" -o jsonpath='{.spec.template.spec.containers[0].env[*].name}' | grep -q JAVA_TOOL_OPTIONS && n=$((n+1)) || miss="$miss $s"
done; echo "  $n with agent | missing:${miss:- none}"
echo "--- Prometheus ---"
curl -s -m 5 -o /dev/null -w "  $PROM_URL -> HTTP %{http_code}\n" "$PROM_URL/-/ready" || echo "  NOT reachable at $PROM_URL"
curl -s -m 10 "$PROM_URL/api/v1/targets?state=active" | python3 -c "
import sys,json
try:
  t=[x for x in json.load(sys.stdin)['data']['activeTargets'] if '8889' in x['scrapeUrl']]
  print('  collector scraped every', [x.get('scrapeInterval') for x in t] or 'NOT FOUND (no span metrics!)')
except Exception as e: print('  could not read targets:', e)"
echo "--- MySQL ---"
L=$(bash "$ARC_ROOT/ops/mysql-leader.sh" || echo NONE); echo "  writable leader: $L"
echo "--- memory ---"; free -m | awk 'NR==2{print "  available MB:", $7, "of", $2}'
if [ "${1:-}" = "--book" ]; then
  echo "--- real login + search + booking ---"
  yes "" | timeout 300 bash "$ARC_ROOT/ops/demo.sh" 2>&1 | grep -E "HTTP|orders:|FAILED|logged in"
fi
