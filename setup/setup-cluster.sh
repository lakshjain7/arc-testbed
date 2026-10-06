#!/usr/bin/env bash
# Build one complete ARC cluster on a fresh machine, in stages. Each stage is safe to re-run.
#
#   bash setup/setup-cluster.sh                      all stages, cluster "arc" (index 0)
#   ARC_CLUSTER=arc2 ARC_INDEX=1 bash setup/setup-cluster.sh        a second cluster
#   bash setup/setup-cluster.sh --from instrument    resume from a stage
#   bash setup/setup-cluster.sh --only verify        run one stage
#
# Stages:  cluster -> images -> deploy -> tame -> instrument -> bringup -> prometheus -> chaos -> verify
# Options (environment):
#   PROFILE=core|full   core = the 20 services on the search/book/pay path (default, ~14 GB)
#                       full = all ~45 Train Ticket services (~26 GB; only useful if the load uses them)
#   ARC_BATCH=3         how many Java services start at once (more crash-loops Nacos registration)
#   ARC_FIX_DNS=1       point the kind nodes at 8.8.8.8 (only if in-node image pulls fail on DNS)
#
# Everything here was learned the hard way; docs/RUNBOOK.md has the stories.
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
set -u
PROFILE="${PROFILE:-core}"; BATCH="${ARC_BATCH:-3}"
STAGES="cluster images deploy tame instrument bringup prometheus chaos verify"
FROM=cluster; ONLY=""
while [ $# -gt 0 ]; do case "$1" in --from) FROM=$2; shift 2;; --only) ONLY=$2; shift 2;; *) echo "unknown option $1"; exit 1;; esac; done
CHART_SRC="${CHART_SRC:-$HOME/src/xlab-train-ticket}"
CHART_COMMIT=c9537c1533514bb6ba9bd664b9312c2b9cee413c      # xlab-uiuc/train-ticket, 2026-04-15: the version everything was validated on
CACHE="$ARC_DATA_ROOT/cache"; mkdir -p "$CACHE"
NODES() { kind get nodes --name "$ARC_CLUSTER" 2>/dev/null; }
LOG="$ARC_DATA/logs/setup-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
say "cluster=$ARC_CLUSTER index=$ARC_INDEX profile=$PROFILE  UI :$UI_PORT  Prometheus :$PROM_PORT  Grafana :$GRAFANA_PORT  log: $LOG"

# ------------------------------------------------------------------------------------------------
stage_cluster() {
  docker info >/dev/null 2>&1 || { say "Docker is not reachable. Start Docker first."; exit 1; }
  local need=14000; [ "$PROFILE" = full ] && need=26000
  [ "$(avail_mb)" -lt "$need" ] && say "WARNING: only $(avail_mb) MB free; the $PROFILE profile needs about $need MB."
  if kind get clusters 2>/dev/null | grep -qx "$ARC_CLUSTER"; then say "cluster '$ARC_CLUSTER' already exists"; else
    # Kubelet pulls ONE image at a time by default; allow 3 so one big image can't block a node.
    # Host ports -> fixed NodePorts: 32677 website, 30090 Prometheus, 30030 Grafana.
    cat > "$CACHE/kind-$ARC_CLUSTER.yaml" <<YAML
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: $ARC_CLUSTER
kubeadmConfigPatches:
  - |
    kind: KubeletConfiguration
    serializeImagePulls: false
    maxParallelImagePulls: 3
nodes:
  - role: control-plane
    kubeadmConfigPatches:
      - |
        kind: InitConfiguration
        nodeRegistration:
          taints: []
    extraPortMappings:
      - {containerPort: 32677, hostPort: $UI_PORT, protocol: TCP}
      - {containerPort: 30090, hostPort: $PROM_PORT, protocol: TCP}
      - {containerPort: 30030, hostPort: $GRAFANA_PORT, protocol: TCP}
  - role: worker
  - role: worker
YAML
    kind create cluster --config "$CACHE/kind-$ARC_CLUSTER.yaml" --image kindest/node:v1.34.0 --wait 180s || exit 1
  fi
  if [ "${ARC_FIX_DNS:-0}" = 1 ]; then
    for n in $(NODES); do docker exec "$n" sh -c 'printf "nameserver 8.8.8.8\nnameserver 1.1.1.1\noptions timeout:2 attempts:5\n" > /etc/resolv.conf'; done
    say "node DNS set to 8.8.8.8"
  fi
  kubectl --context "$KCTX" get nodes
}

# pull one image on the host (fast path) and copy it into every node; skip if the nodes have it
load_image() {
  local img=$1 node tar="$CACHE/img-$ARC_CLUSTER.tar" plat
  node=$(NODES | head -1)
  if docker exec "$node" crictl inspecti "$img" >/dev/null 2>&1 || docker exec "$node" crictl inspecti "docker.io/$img" >/dev/null 2>&1 \
     || docker exec "$node" crictl inspecti "docker.io/library/$img" >/dev/null 2>&1; then echo "   have   $img"; return 0; fi
  plat="linux/$(docker version -f '{{.Server.Arch}}')"
  local ok=0; for _ in 1 2 3 4 5; do docker pull -q --platform "$plat" "$img" >/dev/null 2>&1 && { ok=1; break; }; sleep 5; done
  [ $ok = 1 ] || { echo "   PULL-FAIL $img"; return 1; }
  rm -f "$tar"
  # multi-platform images break plain `kind load docker-image`; export one platform as an archive
  docker save --platform "$plat" "$img" -o "$tar" >/dev/null 2>&1 || docker save "$img" -o "$tar" >/dev/null 2>&1
  if kind load image-archive --name "$ARC_CLUSTER" "$tar" >/dev/null 2>&1; then echo "   loaded $img"; else echo "   LOAD-FAIL $img"; rm -f "$tar"; return 1; fi
  rm -f "$tar"
}

stage_images() {
  local fails=0 n=0 total; total=$(grep -vcE '^\s*(#|$)' "$ARC_ROOT/setup/images.txt")
  say "preloading $total images (first time: tens of minutes, mostly download; later clusters: minutes)"
  while read -r img; do
    case "$img" in ''|\#*) continue;; esac
    n=$((n+1)); printf "[%2d/%d]" "$n" "$total"; load_image "$img" || fails=$((fails+1))
  done < "$ARC_ROOT/setup/images.txt"
  [ $fails -gt 0 ] && { say "$fails image(s) failed. Fix the network/proxy and re-run:  --only images"; exit 1; }
  say "all images are on the nodes"
}

stage_deploy() {
  if [ ! -d "$CHART_SRC/.git" ]; then
    mkdir -p "$(dirname "$CHART_SRC")"; git clone -q https://github.com/xlab-uiuc/train-ticket.git "$CHART_SRC" || exit 1
  fi
  git -C "$CHART_SRC" checkout -q "$CHART_COMMIT" 2>/dev/null || say "WARNING: could not check out $CHART_COMMIT; using $(git -C "$CHART_SRC" rev-parse --short HEAD)"
  if $K get deploy ts-travel-service >/dev/null 2>&1; then say "Train Ticket is already deployed"; return 0; fi
  # The deploy job applies ~45 Deployments at once. Starting 45 JVMs together piles up and
  # crash-loops Nacos registration, so a watcher keeps every ts-* Deployment at 0 replicas until
  # telemetry and CPU limits are in place; stage "bringup" then starts them in small batches.
  ( while :; do
      for d in $($K get deploy --no-headers 2>/dev/null | awk '$1 ~ /^ts-/ {print $1}'); do
        [ "$($K get deploy "$d" -o jsonpath='{.spec.replicas}' 2>/dev/null)" != "0" ] && $K scale deploy/"$d" --replicas=0 >/dev/null 2>&1
      done; sleep 4
    done ) & TAMER=$!
  trap 'kill $TAMER 2>/dev/null' EXIT
  say "helm install (creates the in-cluster deploy job; it installs MySQL x2, Nacos, RabbitMQ, then the services)"
  helm --kube-context "$KCTX" upgrade --install train-ticket "$CHART_SRC" --namespace "$NS" --create-namespace \
       --set job.imagePullPolicy=IfNotPresent --timeout 10m >/dev/null || { say "helm install failed"; exit 1; }
  local t0; t0=$(date +%s)
  until [ "$($K get job train-ticket-deploy -o jsonpath='{.status.succeeded}' 2>/dev/null)" = "1" ]; do
    [ $(( $(date +%s) - t0 )) -gt 3600 ] && { say "deploy job not finished after 60 min; see: $K logs job/train-ticket-deploy"; exit 1; }
    say "  deploy job running: $($K get pods --no-headers 2>/dev/null | grep -vc Completed) pods, $($K get deploy --no-headers 2>/dev/null | wc -l) deployments | $($K logs job/train-ticket-deploy --tail=1 2>/dev/null | cut -c1-90)"
    sleep 30
  done
  sleep 8; kill $TAMER 2>/dev/null; trap - EXIT
  say "deploy job finished in $(( ($(date +%s) - t0) / 60 )) min; all services held at 0 replicas"
}

stage_tame() {
  for d in $($K get deploy --no-headers | awk '$1 ~ /^ts-/ {print $1}'); do $K scale deploy/"$d" --replicas=0 >/dev/null; done
  say "unused monitoring off (alertsnitch, alertmanager)"
  for d in alertsnitch alertsnitch-mysql alertmanager; do $KS get deploy $d >/dev/null 2>&1 && $KS scale deploy/$d --replicas=0 >/dev/null; done
  # Nacos 2.0.1 cluster mode does not keep its 3 copies consistent after restarts (measured: they
  # knew 8, 8 and 20 services) -> random 503s. One standalone copy is consistent by construction.
  # Its default heap is 1 GB per copy; 512 MB is plenty.
  if [ "$($K get sts nacos -o jsonpath='{.spec.replicas}')" != "1" ] || ! $K get sts nacos -o yaml | grep -q "value: standalone"; then
    say "Nacos -> 1 standalone copy, heap capped"
    $K scale sts/nacos --replicas=1 >/dev/null
    $K set env sts/nacos MODE=standalone SPRING_DATASOURCE_PLATFORM=mysql JVM_XMS=256m JVM_XMX=512m JVM_XMN=128m >/dev/null
    sleep 5; $K delete pod nacos-0 --wait=false >/dev/null 2>&1      # a StatefulSet won't replace a not-Ready pod by itself
  fi
  say "waiting for MySQL (nacosdb, tsdb), Nacos, RabbitMQ"
  for i in $(seq 1 90); do
    db=$($K get pods --no-headers | grep -E '^(tsdb|nacosdb)-mysql' | awk '{split($2,a,"/"); if (a[1]!=a[2]) print}' | wc -l)
    na=$($K get pods --no-headers | awk '$1=="nacos-0" && $2=="1/1"' | wc -l)
    api=$($K exec nacos-0 -c k8snacos -- curl -s -m 3 -o /dev/null -w '%{http_code}' "localhost:8848/nacos/v1/ns/service/list?pageNo=1&pageSize=1" 2>/dev/null)
    [ "$db" = 0 ] && [ "$na" = 1 ] && [ "$api" = 200 ] && break
    sleep 10
  done
  [ "${api:-}" = 200 ] || { say "Nacos API not answering after 15 min; see: $K logs nacos-0 -c k8snacos"; exit 1; }
  # the deploy job sets max_connections=500 only in memory; re-apply (20 services x 10-connection pools)
  for p in $($K get pods --no-headers | awk '/^(tsdb|nacosdb)-mysql-[0-9]+/{print $1}'); do
    $K exec "$p" -c mysql -- mysql -uroot -e "SET GLOBAL max_connections = 500;" >/dev/null 2>&1
  done
  say "infrastructure ready; MySQL writable leader: $(bash "$ARC_ROOT/ops/mysql-leader.sh" || echo NONE)"
}

stage_instrument() {
  local jar="$CACHE/opentelemetry-javaagent-2.31.1.jar"
  if [ ! -s "$jar" ]; then
    say "downloading the OpenTelemetry Java agent v2.31.1 (25 MB)"
    curl -fsSL -o "$jar" https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/download/v2.31.1/opentelemetry-javaagent.jar || { say "download failed"; exit 1; }
  fi
  for n in $(NODES); do docker exec "$n" mkdir -p /opt/otel && docker cp "$jar" "$n:/opt/otel/opentelemetry-javaagent.jar"; done
  say "agent jar copied to every node (/opt/otel)"
  $K apply -f "$ARC_ROOT/setup/otel-collector.yaml" >/dev/null && $K rollout status deploy/otel-collector --timeout=180s >/dev/null && say "collector running"
  # Patch every Java service while it is at 0 replicas, so nothing restarts:
  #  - the agent (traces -> collector on :4318; the agent speaks http/protobuf, NOT the :4317 gRPC port)
  #  - CPU limit 2 cores (the chart's 500m made a single search take 2-3 s and 1 req/s time out)
  local n=0
  for s in $($K get deploy --no-headers | awk '$1 ~ /^ts-.*-service$/ {print $1}'); do
    $K patch deploy "$s" --type=strategic -p "$(cat <<JSON
{"spec":{"template":{"spec":{
  "containers":[{"name":"$s","env":[
    {"name":"JAVA_TOOL_OPTIONS","value":"-javaagent:/otel/opentelemetry-javaagent.jar"},
    {"name":"OTEL_SERVICE_NAME","value":"$s"},
    {"name":"OTEL_EXPORTER_OTLP_ENDPOINT","value":"http://otel-collector:4318"},
    {"name":"OTEL_TRACES_EXPORTER","value":"otlp"},
    {"name":"OTEL_METRICS_EXPORTER","value":"none"},
    {"name":"OTEL_LOGS_EXPORTER","value":"none"}],
   "volumeMounts":[{"name":"otel-agent","mountPath":"/otel","readOnly":true}],
   "resources":{"limits":{"cpu":"2"}}}],
  "volumes":[{"name":"otel-agent","hostPath":{"path":"/opt/otel","type":"Directory"}}]}}}}
JSON
)" >/dev/null && n=$((n+1))
  done
  say "telemetry agent + 2-core limit set on $n services (still at 0 replicas)"
}

stage_bringup() {
  local list
  if [ "$PROFILE" = full ]; then
    list=$($K get deploy --no-headers | awk '$1 ~ /^ts-.*-service$/ {print $1}')
    say "full profile: making sure every service image is on the nodes"
    for img in $($K get deploy -o jsonpath='{range .items[*]}{.spec.template.spec.containers[0].image}{"\n"}{end}' | grep sregym | sort -u); do load_image "$img"; done
  else list=$CORE_SERVICES; fi
  $K scale deploy/rabbitmq deploy/flagd --replicas=1 >/dev/null 2>&1
  set -- $list
  say "starting $# services in batches of $BATCH (each batch must be Ready before the next)"
  while [ $# -gt 0 ]; do
    batch=""; for _ in $(seq 1 "$BATCH"); do [ $# -gt 0 ] && { batch="$batch $1"; shift; }; done
    [ "$(avail_mb)" -lt 1500 ] && { say "STOPPING: only $(avail_mb) MB free"; exit 1; }
    for s in $batch; do $K scale deploy/"$s" --replicas=1 >/dev/null; done
    for s in $batch; do
      if $K rollout status deploy/"$s" --timeout=480s >/dev/null 2>&1; then say "  $s ready  ($(avail_mb) MB free)"
      else say "  $s NOT READY after 8 min:"; $K get pods -l app="$s" --no-headers; fi
    done
    sleep 15
  done
  $K scale deploy/ts-ui-dashboard --replicas=1 >/dev/null; $K rollout status deploy/ts-ui-dashboard --timeout=180s >/dev/null && say "  website ready"
  bash "$ARC_ROOT/ops/nacos-health.sh" | tail -1
}

stage_prometheus() {
  $KS get cm prometheus-config -o json > "$ARC_DATA/logs/prometheus-config.before.json"
  python3 "$ARC_ROOT/setup/prom-config.py" < "$ARC_DATA/logs/prometheus-config.before.json" | $KS apply -f - >/dev/null
  # fixed NodePorts, so nothing depends on a fragile `kubectl port-forward`
  $KS patch svc prometheus -p '{"spec":{"type":"NodePort","ports":[{"port":9090,"nodePort":30090}]}}' >/dev/null 2>&1 || say "could not set Prometheus NodePort (check: $KS get svc prometheus)"
  $KS patch svc grafana -p '{"spec":{"type":"NodePort","ports":[{"port":3000,"nodePort":30030}]}}' >/dev/null 2>&1 || say "could not set Grafana NodePort"
  $KS rollout restart deploy/prometheus >/dev/null; $KS rollout status deploy/prometheus --timeout=180s >/dev/null
  for i in $(seq 1 30); do curl -s -m 3 "$PROM_URL/-/ready" >/dev/null 2>&1 && break; sleep 3; done
  curl -s -m 5 "$PROM_URL/api/v1/status/config" | python3 -c "
import sys,json,re
y=json.load(sys.stdin)['data']['yaml']
print('   scrape intervals:', sorted(set(re.findall(r'scrape_interval: (\S+)', y))), '| jobs:', re.findall(r'job_name: (\S+)', y))" \
    || say "Prometheus is not reachable at $PROM_URL"
}

stage_chaos() {
  helm repo add chaos-mesh https://charts.chaos-mesh.org >/dev/null 2>&1; helm repo update chaos-mesh >/dev/null 2>&1
  # kind nodes run containerd at /run/containerd/containerd.sock. With the wrong socket Chaos Mesh
  # reports success and injects nothing, hence the canary below.
  helm --kube-context "$KCTX" upgrade --install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh --create-namespace --version 2.6.3 \
    --set chaosDaemon.runtime=containerd --set chaosDaemon.socketPath=/run/containerd/containerd.sock \
    --set controllerManager.replicaCount=1 --set controllerManager.leaderElection.enabled=false \
    --set dashboard.create=false --set dnsServer.create=false \
    --set controllerManager.podChaos.podFailure.pauseImage=registry.k8s.io/pause:3.10 \
    --set images.tag=v2.6.3 --wait --timeout 10m >/dev/null || { say "Chaos Mesh install failed"; exit 1; }
  kubectl --context "$KCTX" -n chaos-mesh get pods --no-headers | awk '{print "   "$1, $2, $3}'
  bash "$ARC_ROOT/setup/chaos-canary.sh"
}

stage_verify() {
  bash "$ARC_ROOT/ops/health.sh"
  say "warming up (services are cold after their first start)"
  bash "$ARC_ROOT/loadgen/warmup.sh"
  bash "$ARC_ROOT/ops/health.sh" --book | tail -8
  cat <<TXT

Cluster $ARC_CLUSTER is up.
  website      http://localhost:$UI_PORT      (fdse_microservice / 111111)
  Prometheus   http://localhost:$PROM_PORT
  Grafana      http://localhost:$GRAFANA_PORT   (admin / admin)
Next (docs/LAB-SETUP.md, "Day 1"):
  bash loadgen/step-test.sh "2 4 6" 180        find the load this machine carries cleanly
  bash run/start-campaign.sh calibrate         no-fault episodes -> thresholds
  bash run/start-campaign.sh campaign          the dataset
TXT
}

run=0
for st in $STAGES; do
  [ -n "$ONLY" ] && { [ "$st" = "$ONLY" ] && { say "=== stage: $st ==="; "stage_$st"; }; continue; }
  [ "$st" = "$FROM" ] && run=1
  [ $run = 1 ] && { say "=== stage: $st ==="; "stage_$st"; }
done
say "done. log: $LOG"
