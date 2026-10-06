#!/usr/bin/env bash
# Put a service instance back into (or take it out of) rotation in Nacos, by address.
# A disabled instance is HIDDEN from Nacos' list API, so the address comes from the pod.
# Use this if a "drain" action was ever left behind:   nacos-set-enabled.sh ts-station-service true
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
S=$1; EN=${2:-true}; IP=${3:-}; PORT=${4:-}
[ -z "$IP" ] && IP=$($K get pods -l app="$S" -o jsonpath='{.items[0].status.podIP}')
[ -z "$PORT" ] && PORT=$($K get pods -l app="$S" -o jsonpath='{.items[0].spec.containers[0].ports[0].containerPort}')
echo "PUT $S $IP:$PORT enabled=$EN"
$K exec nacos-0 -c k8snacos -- curl -s -X PUT "localhost:8848/nacos/v1/ns/instance?serviceName=$S&ip=$IP&port=$PORT&enabled=$EN&ephemeral=true"; echo
sleep 3
$K exec nacos-0 -c k8snacos -- curl -s "localhost:8848/nacos/v1/ns/instance/list?serviceName=$S" \
  | python3 -c "import sys,json; h=json.load(sys.stdin)['hosts']; print('listed now:', [(x['ip'], x['port'], x['enabled']) for x in h] or 'NONE')"
