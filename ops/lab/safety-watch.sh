#!/bin/bash
# One-shot safety check for plan wide1 (laptop chat, 17 Oct, item 4). Runs in tmux "safety".
# Waits for the first 3 blocks (21 episodes). Counts saturation among DELAY and LOSS episodes only
# (pod-kill and pod-hang saturate by nature). If more than 1 in 4 of those are saturated, stops the
# campaign with the repo's stop command. Writes the result either way, then exits. Never starts anything.
OUT="$HOME/arc-data/arc/logs/safety-check-wide1.txt"
check() {
python3 - <<'EOF'
import json, os
root = os.path.expanduser("~/arc-data/arc")
plan = json.load(open(f"{root}/plans/wide1.json"))
rows = []
for e in plan["episodes"]:
    if e["block"] > 3: break
    d = f"{root}/raw/{e['id']}"
    try: m = json.load(open(f"{d}/meta.json")); l = json.load(open(f"{d}/labels_v2.json"))
    except (OSError, ValueError): continue
    rows.append((e, m, l))
dl = [(e, l) for e, m, l in rows if e["fault"] in ("network-delay", "net-loss")]
sat = [x for x in dl if x[1].get("saturated_before_action")]
share = len(sat) / max(len(dl), 1)
other = [(e, l) for e, m, l in rows if e["fault"] in ("pod-kill", "pod-hang")]
print(f"RESULT recorded={len(rows)} delay_loss_episodes={len(dl)} saturated={len(sat)} share={share:.2f} "
      f"verdict={'STOP' if share > 0.25 else 'CONTINUE'} | pod-kill/pod-hang saturated {sum(bool(l.get('saturated_before_action')) for _, l in other)}/{len(other)}")
for e, m, l in rows:
    s = l.get("summary") or {}
    print(f"  {e['id'][-9:]} {e['fault']:14s} {str(e['level']):5s} {(e['fault_target'] or '-')[3:-8]:14s} {e['action']:16s} status={m.get('status')} saturated={l.get('saturated_before_action')} stalled={l.get('stalled')} user_damage={s.get('user_damage')}")
EOF
}
while :; do
  R=$(check); N=$(echo "$R" | sed -n 's/^RESULT recorded=\([0-9]*\).*/\1/p')
  [ "${N:-0}" -ge 21 ] && break
  pgrep -f 'run_campaign.py run --name wide1' >/dev/null || { { echo "$(date -u '+%F %T') UTC campaign wide1 not running; only $N of 21 recorded"; echo "$R"; } > "$OUT"; exit 0; }
  sleep 300
done
{ echo "$(date -u '+%F %T') UTC safety check of wide1, first 3 blocks"; echo "$R"; } > "$OUT"
if echo "$R" | grep -q 'verdict=STOP'; then
  cd "$HOME/arc-testbed" && bash run/start-campaign.sh stop >> "$OUT" 2>&1
  echo "$(date -u '+%F %T') UTC campaign STOPPED by the safety check" >> "$OUT"
else echo "campaign left running" >> "$OUT"; fi
