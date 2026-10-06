#!/usr/bin/env bash
# Find the load this machine carries cleanly: run the generator at increasing rates and report
# success, latency and CPU throttling at each. Pick the highest rate that is ~100% successful with
# stable latency, then use about 2/3 of it for episodes (faults need headroom to show damage).
#   loadgen/step-test.sh "2 4 6" 180
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
RATES="${1:-2 4 6}"; SECS="${2:-180}"
for r in $RATES; do
  echo; echo "################ $r req/s for ${SECS}s ################"
  python3 "$ARC_ROOT/loadgen/loadgen.py" --rate "$r" --duration "$SECS" --seed 7 --print-every 60
  python3 "$ARC_ROOT/loadgen/analyze.py" | sed -n '1,8p'
  echo "--- most CPU-throttled services (last 3 min) ---"
  curl -s "$PROM_URL/api/v1/query" --data-urlencode "query=topk(5, sum by (container) (increase(container_cpu_cfs_throttled_periods_total{namespace=\"$NS\",container=~\"ts-.*\"}[3m])) / sum by (container) (increase(container_cpu_cfs_periods_total{namespace=\"$NS\",container=~\"ts-.*\"}[3m])))" \
    | python3 -c "import sys,json
for r in json.load(sys.stdin)['data']['result']: print('   %-28s throttled %3.0f%%' % (r['metric']['container'], 100*float(r['value'][1])))" 2>/dev/null
  echo "   memory available: $(avail_mb) MB   load average: $(cut -d' ' -f1-3 /proc/loadavg)"
done
echo "STEP TEST DONE"
