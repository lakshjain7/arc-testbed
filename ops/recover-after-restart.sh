#!/usr/bin/env bash
# After Docker or the machine restarted the whole cluster: every Java service boots at once, which
# crash-loops Nacos registration. Scale all services to 0, wait for MySQL + Nacos, then bring the
# services back in small batches.          recover-after-restart.sh [batch size = 2]
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
B=${1:-2}
say "waiting for the Kubernetes API ($KCTX)"
until kubectl --context "$KCTX" get nodes >/dev/null 2>&1; do sleep 5; done
WANT=$($K get deploy --no-headers | awk '$1 ~ /^ts-.*-service$/ {print $1}' | while read -r s; do
  [ "$($K get deploy "$s" -o jsonpath='{.spec.replicas}')" != "0" ] && echo "$s"; done)
echo "$WANT" > "$ARC_DATA/logs/services-to-restore.txt"
say "scaling $(echo "$WANT" | grep -c .) services to 0 (list saved in $ARC_DATA/logs/services-to-restore.txt)"
for s in $WANT; do $K scale deploy/"$s" --replicas=0 >/dev/null; done
say "waiting for MySQL and Nacos"
for i in $(seq 1 120); do
  db=$($K get pods --no-headers | grep -E '^(tsdb|nacosdb)-mysql' | awk '{split($2,a,"/"); if (a[1]!=a[2]) print}' | wc -l)
  na=$($K get pods --no-headers | awk '$1=="nacos-0" && $2=="1/1"' | wc -l)
  [ "$db" = "0" ] && [ "$na" = "1" ] && { say "MySQL and Nacos ready"; break; }
  sleep 10
done
# max_connections=500 lives only in MySQL's memory and is lost on restart (default 151 is too few)
for p in $($K get pods --no-headers | awk '/^(tsdb|nacosdb)-mysql-[0-9]+/{print $1}'); do
  $K exec "$p" -c mysql -- mysql -uroot -e "SET GLOBAL max_connections = 500;" >/dev/null 2>&1
done
say "MySQL writable leader: $(bash "$ARC_ROOT/ops/mysql-leader.sh" || echo NONE)"
set -- $WANT
while [ $# -gt 0 ]; do
  batch=""; for _ in $(seq 1 "$B"); do [ $# -gt 0 ] && { batch="$batch $1"; shift; }; done
  for s in $batch; do $K scale deploy/"$s" --replicas=1 >/dev/null; done
  for s in $batch; do
    if $K rollout status deploy/"$s" --timeout=420s >/dev/null 2>&1; then say "  $s ready"
    else say "  $s NOT READY after 7 min"; fi
  done
  sleep 15
done
say "RECOVERY DONE"
$K get pods --no-headers | grep '^ts-' | awk '{print $2}' | sort | uniq -c
bash "$ARC_ROOT/ops/nacos-health.sh" | tail -1
echo "Next: bash loadgen/warmup.sh   (services are cold after a restart)"
