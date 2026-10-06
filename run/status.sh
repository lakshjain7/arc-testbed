#!/usr/bin/env bash
# Where is data collection right now? One screen, for every cluster on this machine.
#   run/status.sh [PLAN_NAME]
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
NAME="${1:-main}"
echo "=== $(hostname)  $(date '+%F %T')   memory available: $(avail_mb) MB   load: $(cut -d' ' -f1-3 /proc/loadavg) ==="
df -h "$ARC_DATA_ROOT" | awk 'NR==2{print "    disk: " $4 " free of " $2 " (" $5 " used)"}'
i=0
for c in $(kind get clusters 2>/dev/null); do
  dir="$ARC_DATA_ROOT/$c"
  [ -d "$dir" ] || continue
  echo; echo "--- cluster $c ---"
  tmux has-session -t "arc-$c" 2>/dev/null && echo "  runner: RUNNING in tmux session arc-$c" || echo "  runner: not running"
  python3 - "$dir" <<'PY'
import json, os, sys, time
d = sys.argv[1]
try:
    s = json.load(open(os.path.join(d, "loadgen", "status.json")))
    age = time.time() - s.get("updated", 0)
    print(f"  load:   {s.get('state')} at {s.get('rate_target')} req/s, last minute failed {s.get('failed_pct')}%, p95 {s.get('p95_ms')} ms"
          + ("" if age < 15 else f"   (status is {age/60:.0f} min old: generator NOT running)"))
except (OSError, ValueError):
    print("  load:   never started")
raw = os.path.join(d, "raw")
n = len([x for x in os.listdir(raw) if os.path.exists(os.path.join(raw, x, "meta.json"))]) if os.path.isdir(raw) else 0
print(f"  episodes recorded in total: {n}")
PY
  if [ -f "$dir/plans/$NAME.json" ]; then
    ARC_CLUSTER="$c" python3 "$ARC_ROOT/harness/run_campaign.py" status --name "$NAME" | sed 's/^/  /'
  fi
  [ -f "$dir/logs/campaign.log" ] && { echo "  last log lines:"; tail -4 "$dir/logs/campaign.log" | sed 's/^/    /'; }
done
[ -f "$ARC_CALIB/calibration_v2.json" ] && echo && python3 -c "
import json; c = json.load(open('$ARC_CALIB/calibration_v2.json'))
print('calibration: z =', c['z'], '| fitted on', len(c['train']), 'episodes, checked on', len(c['holdout']))" || { echo; echo "calibration: NOT DONE YET (run/start-campaign.sh calibrate)"; }
