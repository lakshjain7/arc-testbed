#!/usr/bin/env bash
# Prove Chaos Mesh really injects faults (a wrong containerd socket makes it "succeed" silently),
# and that this kernel supports network delay/loss. Uses a throwaway pod; never touches Train Ticket.
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
KC="kubectl --context $KCTX"
$KC create namespace arc-canary --dry-run=client -o yaml | $KC apply -f - >/dev/null
$KC -n arc-canary apply -f - >/dev/null <<'YAML'
apiVersion: apps/v1
kind: Deployment
metadata: {name: canary}
spec:
  replicas: 1
  selector: {matchLabels: {app: canary}}
  template:
    metadata: {labels: {app: canary}}
    spec:
      containers: [{name: canary, image: registry.k8s.io/pause:3.10, imagePullPolicy: Never}]
YAML
$KC -n arc-canary rollout status deploy/canary --timeout=60s >/dev/null
before=$($KC -n arc-canary get pod -l app=canary -o jsonpath='{.items[0].metadata.uid}')
echo "1) pod-kill canary (before uid ${before:0:8})"
$KC -n arc-canary apply -f - >/dev/null <<'YAML'
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata: {name: canary-kill}
spec: {action: pod-kill, mode: one, selector: {namespaces: [arc-canary], labelSelectors: {app: canary}}}
YAML
now=$before
for i in $(seq 1 30); do
  now=$($KC -n arc-canary get pod -l app=canary -o jsonpath='{.items[?(@.status.phase=="Running")].metadata.uid}' 2>/dev/null)
  [ -n "$now" ] && [ "$now" != "$before" ] && { echo "   PASS: pod replaced (new uid ${now:0:8}) after ${i}s"; break; }
  sleep 1
done
[ "$now" = "$before" ] && echo "   FAIL: pod was not killed; check the chaos-daemon socket path"
$KC -n arc-canary delete podchaos canary-kill --wait=true --timeout=60s >/dev/null
echo "2) network delay support in this kernel (netem), tested inside a chaos-daemon"
D=$($KC -n chaos-mesh get pod -l app.kubernetes.io/component=chaos-daemon -o jsonpath='{.items[0].metadata.name}')
$KC -n chaos-mesh exec "$D" -- sh -c 'ip link add arcnetemtest type dummy 2>/dev/null; tc qdisc add dev arcnetemtest root netem delay 10ms && echo "   PASS: netem available" || echo "   FAIL: netem missing -> drop the network-delay and net-loss faults"; ip link del arcnetemtest 2>/dev/null'
$KC delete namespace arc-canary --wait=false >/dev/null && echo "3) canary namespace removed"
