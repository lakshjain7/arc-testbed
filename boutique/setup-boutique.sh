#!/usr/bin/env bash
# Build the second testbed: Google's Online Boutique (11 gRPC microservices + Redis) on its own kind cluster,
# with the same telemetry pipeline as the Train Ticket testbed (OTel collector -> spanmetrics + servicegraph ->
# Prometheus, kube-state-metrics, cAdvisor) and Chaos Mesh, so the harness queries work unchanged.
#
#   bash boutique/setup-boutique.sh                       all stages
#   bash boutique/setup-boutique.sh --from instrument     resume
#   bash boutique/setup-boutique.sh --only verify
# Stages: cluster -> images -> deploy -> instrument -> monitoring -> chaos -> verify
# Runs next to the Train Ticket cluster (own ports: UI 32687, Prometheus 19091).
export ARC_CLUSTER="${ARC_CLUSTER:-boutique}" ARC_INDEX="${ARC_INDEX:-1}"
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
set -u
NS=boutique; K="kubectl --context ${KCTX} -n ${NS}"
APPV=v0.10.1
MANIFEST_URL="https://raw.githubusercontent.com/GoogleCloudPlatform/microservices-demo/${APPV}/release/kubernetes-manifests.yaml"
SERVICES="adservice cartservice checkoutservice currencyservice emailservice frontend paymentservice productcatalogservice recommendationservice shippingservice redis-cart"
STAGES="cluster images deploy instrument monitoring chaos verify"
FROM=cluster; ONLY=""
while [ $# -gt 0 ]; do case "$1" in --from) FROM=$2; shift 2;; --only) ONLY=$2; shift 2;; *) echo "unknown option $1"; exit 1;; esac; done
CACHE="$ARC_DATA_ROOT/cache"; mkdir -p "$CACHE"
NODES() { kind get nodes --name "$ARC_CLUSTER" 2>/dev/null; }
LOG="$ARC_DATA/logs/setup-boutique-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
say "cluster=$ARC_CLUSTER  UI :$UI_PORT  Prometheus :$PROM_PORT  log: $LOG"

stage_cluster() {
  docker info >/dev/null 2>&1 || { say "Docker is not reachable."; exit 1; }
  [ "$(avail_mb)" -lt 6000 ] && say "WARNING: only $(avail_mb) MB free; Online Boutique needs about 5 GB."
  if kind get clusters 2>/dev/null | grep -qx "$ARC_CLUSTER"; then say "cluster '$ARC_CLUSTER' already exists"; else
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
      - {containerPort: 30003, hostPort: $PROM_PORT, protocol: TCP}
  - role: worker
  - role: worker
YAML
    kind create cluster --config "$CACHE/kind-$ARC_CLUSTER.yaml" --image kindest/node:v1.34.0 --wait 180s || exit 1
  fi
  for n in $(NODES); do      # same open-files cap as the Train Ticket cluster (see setup-cluster.sh)
    docker exec "$n" sh -c 'f=/etc/systemd/system/containerd.service.d/10-nofile.conf; [ -f "$f" ] && exit 0
      mkdir -p "$(dirname "$f")" && printf "[Service]\nLimitNOFILE=1048576\n" > "$f" && systemctl daemon-reload && systemctl restart containerd' || true
  done
  kubectl --context "$KCTX" wait --for=condition=Ready nodes --all --timeout=120s >/dev/null
  kubectl --context "$KCTX" create ns "$NS" >/dev/null 2>&1 || true
  kubectl --context "$KCTX" get nodes
}

load_image() {   # same fast path as setup-cluster.sh: pull on the host, copy into every node
  local img=$1 node tar="$CACHE/img-$ARC_CLUSTER.tar" plat
  node=$(NODES | head -1)
  if docker exec "$node" crictl inspecti "$img" >/dev/null 2>&1 || docker exec "$node" crictl inspecti "docker.io/$img" >/dev/null 2>&1 \
     || docker exec "$node" crictl inspecti "docker.io/library/$img" >/dev/null 2>&1; then echo "   have   $img"; return 0; fi
  plat="linux/$(docker version -f '{{.Server.Arch}}')"
  local ok=0; for _ in 1 2 3 4 5; do docker pull -q --platform "$plat" "$img" >/dev/null 2>&1 && { ok=1; break; }; sleep 5; done
  [ $ok = 1 ] || { echo "   PULL-FAIL $img"; return 1; }
  rm -f "$tar"; docker save --platform "$plat" "$img" -o "$tar" >/dev/null 2>&1 || docker save "$img" -o "$tar" >/dev/null 2>&1
  if kind load image-archive --name "$ARC_CLUSTER" "$tar" >/dev/null 2>&1; then echo "   loaded $img"; else echo "   LOAD-FAIL $img"; rm -f "$tar"; return 1; fi
  rm -f "$tar"
}
stage_images() {
  local fails=0 n=0 total; total=$(grep -vcE '^\s*(#|$)' "$ARC_ROOT/boutique/images.txt")
  while read -r img; do case "$img" in ''|\#*) continue;; esac
    n=$((n+1)); printf "[%2d/%d]" "$n" "$total"; load_image "$img" || fails=$((fails+1))
  done < "$ARC_ROOT/boutique/images.txt"
  [ $fails -gt 0 ] && { say "$fails image(s) failed (report the exact error; do not work around a network block)"; exit 1; }
  say "all images are on the nodes"
}

stage_deploy() {
  local f="$CACHE/boutique-manifests-$APPV.yaml"
  [ -s "$f" ] || curl -fsSL -o "$f" "$MANIFEST_URL" || { say "could not download $MANIFEST_URL"; exit 1; }
  $K apply -f "$f" >/dev/null
  # We drive the load ourselves (open-loop, loadgen_boutique.py); the shipped Locust generator would add traffic we do not control.
  $K scale deploy/loadgenerator --replicas=0 >/dev/null 2>&1 || true
  # The UI is reachable on the host through NodePort 32677 (mapped to $UI_PORT by the kind config).
  $K patch svc frontend-external -p '{"spec":{"type":"NodePort","ports":[{"port":80,"targetPort":8080,"nodePort":32677}]}}' >/dev/null
  say "waiting for the services"
  for s in $SERVICES; do $K rollout status deploy/"$s" --timeout=300s >/dev/null 2>&1 && say "  $s ready" || say "  $s NOT READY"; done
}

stage_instrument() {
  $K apply -f "$ARC_ROOT/boutique/otel-collector.yaml" >/dev/null && $K rollout status deploy/otel-collector --timeout=180s >/dev/null && say "collector running"
  # Tracing on, to the collector, for every service (a superset of the variables the Go, Python, Node, Java and C#
  # services read; unknown ones are ignored). CPU limit 1 core so that a restarted service has a defined ceiling.
  for s in $SERVICES; do
    [ "$s" = redis-cart ] && continue
    $K set env deploy/"$s" ENABLE_TRACING=1 COLLECTOR_SERVICE_ADDR=otel-collector:4317 OTEL_SERVICE_NAME="$s" \
        OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317 OTEL_EXPORTER_OTLP_PROTOCOL=grpc \
        OTEL_TRACES_EXPORTER=otlp OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none >/dev/null
    $K set resources deploy/"$s" --limits=cpu=1 >/dev/null
  done
  for s in $SERVICES; do $K rollout status deploy/"$s" --timeout=300s >/dev/null 2>&1 || say "  $s NOT READY after instrumenting"; done
  say "tracing enabled on $(echo $SERVICES | wc -w) services"
}

stage_monitoring() {
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1; helm repo update prometheus-community >/dev/null 2>&1
  helm --kube-context "$KCTX" upgrade --install kube-state-metrics prometheus-community/kube-state-metrics -n "$NS" \
       --set image.registry=registry.k8s.io --set image.repository=kube-state-metrics/kube-state-metrics --set image.tag=v2.13.0 \
       --set 'metricLabelsAllowlist[0]=pods=[app]' --wait --timeout 5m >/dev/null || { say "kube-state-metrics install failed"; exit 1; }
  $K apply -f "$ARC_ROOT/boutique/prometheus.yaml" >/dev/null && $K rollout status deploy/prometheus --timeout=180s >/dev/null
  for i in $(seq 1 30); do curl -s -m 3 "$PROM_URL/-/ready" >/dev/null 2>&1 && break; sleep 3; done
  say "Prometheus at $PROM_URL"
}

stage_chaos() {
  helm repo add chaos-mesh https://charts.chaos-mesh.org >/dev/null 2>&1; helm repo update chaos-mesh >/dev/null 2>&1
  helm --kube-context "$KCTX" upgrade --install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh --create-namespace --version 2.6.3 \
    --set chaosDaemon.runtime=containerd --set chaosDaemon.socketPath=/run/containerd/containerd.sock \
    --set controllerManager.replicaCount=1 --set controllerManager.leaderElection.enabled=false \
    --set dashboard.create=false --set dnsServer.create=false \
    --set controllerManager.podChaos.podFailure.pauseImage=registry.k8s.io/pause:3.10 \
    --set images.tag=v2.6.3 --wait --timeout 10m 2> >(grep -v 'warnings.go' >&2) >/dev/null || { say "Chaos Mesh install failed"; exit 1; }
  kubectl --context "$KCTX" -n chaos-mesh get pods --no-headers | awk '{print "   "$1, $2, $3}'
}

stage_verify() {
  say "sending a little traffic, then listing which services appear in the telemetry"
  python3 "$ARC_ROOT/boutique/loadgen_boutique.py" --base "$UI_URL" --rate 3 --duration 60 --out "$ARC_DATA/loadgen" >/dev/null 2>&1
  sleep 10
  python3 "$ARC_ROOT/boutique/verify.py" --prom "$PROM_URL"
}

run=0
for st in $STAGES; do
  [ -n "$ONLY" ] && { [ "$st" = "$ONLY" ] && { say "=== stage: $st ==="; "stage_$st"; }; continue; }
  [ "$st" = "$FROM" ] && run=1
  [ $run = 1 ] && { say "=== stage: $st ==="; "stage_$st"; }
done
say "done. log: $LOG"
