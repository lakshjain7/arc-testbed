#!/usr/bin/env bash
# Start extra Train Ticket services on a cluster that is already up (batch 2: the wider system).
# Each one gets its image loaded, the telemetry agent and the 2-core limit, then is started; one at a
# time, because starting many JVMs together crash-loops Nacos registration.
#   ops/add-services.sh ts-travel2-service ts-preserve-other-service
#   ops/add-services.sh flow1            a named group from the list below
#   ops/add-services.sh remove flow1     scale a group back to 0 (frees ~450 MB per service)
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
group() { case "$1" in
  flow1) echo "ts-travel2-service ts-preserve-other-service" ;;     # other train types: search2, book2, orders2
  *) echo "$1" ;; esac; }
REMOVE=0; [ "${1:-}" = remove ] && { REMOVE=1; shift; }
[ $# -gt 0 ] || { sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1; }
LIST=""; for a in "$@"; do LIST="$LIST $(group "$a")"; done

if [ $REMOVE = 1 ]; then
  for s in $LIST; do $K scale deploy/"$s" --replicas=0 >/dev/null && say "$s stopped"; done
  exit 0
fi

node=$(kind get nodes --name "$ARC_CLUSTER" | head -1)
for s in $LIST; do
  $K get deploy "$s" >/dev/null 2>&1 || { say "$s: no such deployment"; continue; }
  [ "$(avail_mb)" -lt 1200 ] && { say "STOPPING: only $(avail_mb) MB free (each service needs ~450 MB)"; exit 1; }
  img=$($K get deploy "$s" -o jsonpath='{.spec.template.spec.containers[0].image}')
  if ! docker exec "$node" crictl inspecti "$img" >/dev/null 2>&1; then
    say "$s: loading image $img"
    plat="linux/$(docker version -f '{{.Server.Arch}}')"; tar="$ARC_DATA_ROOT/cache/img-add.tar"; mkdir -p "$(dirname "$tar")"
    if docker pull -q --platform "$plat" "$img" >/dev/null 2>&1 \
       && { docker save --platform "$plat" "$img" -o "$tar" >/dev/null 2>&1 || docker save "$img" -o "$tar" >/dev/null 2>&1; } \
       && kind load image-archive --name "$ARC_CLUSTER" "$tar" >/dev/null 2>&1; then :; else say "   could not preload; the node will download it itself (slower)"; fi
    rm -f "$tar"
  fi
  # same patch as setup-cluster.sh stage "instrument" (a no-op when it is already there)
  $K patch deploy "$s" --type=strategic -p "{\"spec\":{\"template\":{\"spec\":{
    \"containers\":[{\"name\":\"$s\",\"env\":[
      {\"name\":\"JAVA_TOOL_OPTIONS\",\"value\":\"-javaagent:/otel/opentelemetry-javaagent.jar\"},
      {\"name\":\"OTEL_SERVICE_NAME\",\"value\":\"$s\"},
      {\"name\":\"OTEL_EXPORTER_OTLP_ENDPOINT\",\"value\":\"http://otel-collector:4318\"},
      {\"name\":\"OTEL_TRACES_EXPORTER\",\"value\":\"otlp\"},
      {\"name\":\"OTEL_METRICS_EXPORTER\",\"value\":\"none\"},
      {\"name\":\"OTEL_LOGS_EXPORTER\",\"value\":\"none\"}],
     \"volumeMounts\":[{\"name\":\"otel-agent\",\"mountPath\":\"/otel\",\"readOnly\":true}],
     \"resources\":{\"limits\":{\"cpu\":\"2\"}}}],
    \"volumes\":[{\"name\":\"otel-agent\",\"hostPath\":{\"path\":\"/opt/otel\",\"type\":\"Directory\"}}]}}}}" >/dev/null
  $K scale deploy/"$s" --replicas=1 >/dev/null
  if $K rollout status deploy/"$s" --timeout=900s >/dev/null 2>&1; then say "$s ready  ($(avail_mb) MB free)"
  else say "$s NOT READY after 15 min:"; $K get pods -l app="$s" --no-headers; fi
done
bash "$ARC_ROOT/ops/nacos-health.sh" | tail -1
echo "Next: bash loadgen/warmup.sh, then run the load with the matching mix (ARC_MIX=wide)."
