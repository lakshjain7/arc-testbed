#!/usr/bin/env bash
# Start (or look at, or stop) unattended data collection for ONE cluster, inside tmux.
# tmux keeps it running after the terminal or the remote-desktop window is closed.
#
#   run/start-campaign.sh calibrate [N]          N no-fault episodes (default 20) -> thresholds
#   run/start-campaign.sh campaign [N] [NAME]    the dataset: N episodes (default 700), plan NAME (default main)
#                                                run it again after a reboot: it resumes where it stopped
#   run/start-campaign.sh attach                 watch it live (leave with Ctrl+B then D; NOT Ctrl+C)
#   run/start-campaign.sh stop                   stop cleanly (undoes the fault/action in progress)
#
# Second cluster:   ARC_CLUSTER=arc2 ARC_INDEX=1 run/start-campaign.sh campaign
# Settings (environment): ARC_RATE=2 load in requests/s | ARC_SYNC=1 copy data to $ARC_BACKUP every 25 episodes
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
MODE="${1:-}"; SESSION="arc-$ARC_CLUSTER"; LOG="$ARC_DATA/logs/campaign.log"
command -v tmux >/dev/null || { echo "tmux is missing: sudo apt-get install -y tmux"; exit 1; }
ENVS="ARC_CLUSTER=$ARC_CLUSTER ARC_INDEX=$ARC_INDEX ARC_DATA_ROOT=$ARC_DATA_ROOT ARC_RATE=${ARC_RATE:-2} ARC_SYNC=${ARC_SYNC:-0} ARC_BACKUP=${ARC_BACKUP:-}"

start() {   # $1 = command line to run inside tmux
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "a run is already going for $ARC_CLUSTER.  Watch: run/start-campaign.sh attach   Stop: run/start-campaign.sh stop"; exit 1
  fi
  bash "$ARC_ROOT/ops/cleanup.sh"
  tmux new-session -d -s "$SESSION" "cd $ARC_ROOT && env $ENVS $1 2>&1 | tee -ai $LOG; echo; echo '--- finished; press Enter to close ---'; read"
  echo "started in tmux session '$SESSION'"
  echo "  watch live : run/start-campaign.sh attach        (leave with Ctrl+B then D)"
  echo "  progress   : run/status.sh"
  echo "  log        : $LOG"
}

case "$MODE" in
  calibrate)
    start "python3 harness/run_campaign.py calibrate --episodes ${2:-20}" ;;
  campaign)
    N="${2:-700}"; NAME="${3:-main}"
    if [ ! -f "$ARC_DATA/plans/$NAME.json" ]; then
      [ -f "$ARC_CALIB/calibration_v2.json" ] || echo "WARNING: no calibration yet (run 'calibrate' first). Episodes are still recorded correctly; labels can be recomputed later with harness/relabel.py."
      python3 "$ARC_ROOT/harness/run_campaign.py" plan --episodes "$N" --name "$NAME" || exit 1
    else
      echo "resuming plan '$NAME'"
    fi
    start "python3 harness/run_campaign.py run --name $NAME" ;;
  attach)
    tmux attach -t "$SESSION" ;;
  stop)
    tmux has-session -t "$SESSION" 2>/dev/null || { echo "nothing is running for $ARC_CLUSTER"; exit 0; }
    echo "stopping: the episode in progress removes its fault and undoes its action first (up to ~2 min)"
    tmux send-keys -t "$SESSION" C-c
    PANE=$(tmux list-panes -t "$SESSION" -F '#{pane_pid}' | head -1)
    for _ in $(seq 160); do pgrep -P "$PANE" python3 >/dev/null || break; sleep 2; done
    tmux kill-session -t "$SESSION" 2>/dev/null
    bash "$ARC_ROOT/loadgen/stop-loadgen.sh"
    bash "$ARC_ROOT/ops/cleanup.sh"
    echo "stopped. 'run/start-campaign.sh campaign' resumes from the next unfinished episode." ;;
  *)
    sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
esac
