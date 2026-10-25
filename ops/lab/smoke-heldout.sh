#!/usr/bin/env bash
# Smoke test of the four held-out faults (decision log 10g) before their campaign. One no-op episode per
# fault / level; each must show: fault verified, a visible effect before the action (but users not
# saturated, i.e. worst flow < 80 % bad), clean teardown, and the cluster healthy again afterwards.
#   ops/lab/smoke-heldout.sh                       all of them (about 8 x 9 min)
#   ops/lab/smoke-heldout.sh load-surge:2          just one fault[:level]
#   ops/lab/smoke-heldout.sh call-cut:ts-preserve-service>ts-assurance-service    a call-cut link (caller>callee)
# Run with the campaign's load generator already running (same rate and ARC_MIX as the campaign).
. "$(dirname "${BASH_SOURCE[0]}")/../../lib/env.sh"
T=${SMOKE_TARGET:-ts-seat-service}
CASES=${*:-"http-error call-cut shared-db-slow:5 shared-db-slow:15 load-surge:1.5 load-surge:2"}
for c in $CASES; do
  f=${c%%:*}; l=${c#*:}; [ "$l" = "$c" ] && l=""
  T=${SMOKE_TARGET:-ts-seat-service}
  if [ "${l#*>}" != "$l" ]; then T=${l%%>*}; l=${l#*>}; fi          # link: the caller is the fault target, the callee the level
  id="ep_smoke_${f//-/}_$(echo "${l//./p}" | sed 's/ts-//;s/-service//')_$(date +%H%M%S)"
  say "== $f ${l:+level $l} on $T ($id)"
  python3 "$ARC_ROOT/harness/run_episode.py" --id "$id" --fault "$f" ${l:+--fault-param "$l"} --fault-target "$T" \
      --action noop --target "$T" --delay 120 --seed 1 > "$ARC_DATA/logs/$id.smoke.log" 2>&1
  python3 - "$ARC_DATA/raw/$id" <<'EOF'
import json, os, sys
d = sys.argv[1]
if not os.path.exists(os.path.join(d, "meta.json")):
    print("   NOT SAVED: see the .smoke.log"); sys.exit()
m = json.load(open(os.path.join(d, "meta.json"))); L = json.load(open(os.path.join(d, "labels_v2.json")))
fl = {k: v.get("p_B1L") for k, v in L["client_flows"].items() if v.get("p_B1L") is not None}
sv = sorted(((v.get("p_B1L") or 0, s) for s, v in L["services"].items()), reverse=True)[:5]
print(f"   fault verified {m.get('fault_verified')}  info {json.dumps(m.get('fault_info'))[:160]}")
print(f"   worst user flow bad before the action {100 * max(fl.values() or [0]):.0f} %  (saturated: {L['saturated_before_action']})")
print("   most-bad services before the action: " + ", ".join(f"{s[3:-8]} {100 * p:.0f} %" for p, s in sv))
print(f"   teardown clean {m.get('fault_teardown_clean')}; healthy after {m.get('healthy_after')} ({m.get('recovery_after_s')} s); status {m['status']}")
EOF
done
