#!/usr/bin/env bash
# Put the cluster back to its normal state after an episode was killed half-way (power cut, closed
# terminal, "stop"). Safe to run at any time when no episode is running; it only undoes what
# faults and actions can leave behind:
#   1. Chaos Mesh objects (network delay / loss / pod-kill)        -> deleted
#   2. pods whose CPU limit is not 2 (cpu-squeeze, cpu-bump)       -> resized back to 2, in place
#   3. target services left at 2 copies (scale-up)                 -> back to 1
#   4. services hidden from Nacos although their pod runs (drain)  -> re-enabled
#   ops/cleanup.sh
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"

for kind in networkchaos podchaos stresschaos; do
  for o in $($K get "$kind" -o name 2>/dev/null); do
    say "deleting $o"
    $K delete "$o" --wait=true --timeout=60s >/dev/null 2>&1 || {
      $K annotate "$o" chaos-mesh.chaos-mesh.org/cleanFinalizer=forced --overwrite >/dev/null 2>&1
      $K delete "$o" --wait=true --timeout=60s >/dev/null 2>&1; }
  done
done
$K delete networkpolicy -l arc=quarantine --ignore-not-found >/dev/null 2>&1

for d in $($K get deploy --no-headers | awk '$2!="0/0"{print $1}' | grep -E '^ts-.*-service$'); do
  want=$($K get deploy "$d" -o jsonpath='{.spec.replicas}')
  if [ "$want" != "1" ]; then say "$d has $want copies -> 1"; $K scale deploy "$d" --replicas=1 >/dev/null; fi
  for p in $($K get pods -l app="$d" --field-selector=status.phase=Running -o jsonpath='{.items[*].metadata.name}'); do
    lim=$($K get pod "$p" -o jsonpath='{.spec.containers[0].resources.limits.cpu}')
    if [ "$lim" != "2" ]; then
      say "$p has cpu limit $lim -> 2"
      $K patch pod "$p" --subresource resize -p "{\"spec\":{\"containers\":[{\"name\":\"$d\",\"resources\":{\"limits\":{\"cpu\":\"2\"},\"requests\":{\"cpu\":\"100m\"}}}]}}" >/dev/null
    fi
  done
done

bad=$(bash "$ARC_ROOT/ops/nacos-health.sh" | tail -1 | cut -d: -f2)
for s in $bad; do
  ready=$($K get pods -l app="$s" -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2>/dev/null)
  if [ "$ready" = "true" ]; then
    say "$s runs but is not listed in Nacos -> re-enabling"
    bash "$ARC_ROOT/ops/nacos-set-enabled.sh" "$s" true | tail -1
  fi
done
say "cleanup done"
