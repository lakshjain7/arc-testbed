#!/bin/bash
# After a Windows or Docker restart: the repo's recovery path, then resume the current batch-2 plan.
# Runs in tmux session "recover". Resumes the campaign only if every step came back clean.
# Batch 2 (wide1): the 25-service wide mix, audit log re-disabled (laptop chat 17 Oct, item 5).
cd "$HOME/arc-testbed" || exit 1
export PATH="$HOME/.local/bin:$PATH"
LOG="$HOME/arc-data/arc/logs/recover-$(date -u +%Y%m%d-%H%M).log"
ln -sf "$LOG" "$HOME/arc-data/arc/logs/recover-latest.log"
K="kubectl --context kind-arc -n train-ticket"
{
echo "$(date -u +%T) start"
for n in arc-control-plane arc-worker arc-worker2; do
  echo "  $n open-files cap file: $(docker exec $n sh -c 'cat /etc/systemd/system/containerd.service.d/10-nofile.conf 2>/dev/null | tail -1 || echo MISSING')"
done
bash ops/recover-after-restart.sh
echo "$(date -u +%T) recovery exit $?"
for p in $($K get pods --no-headers | awk '/^(tsdb|nacosdb)-mysql-[0-9]+/{print $1}'); do
  $K exec "$p" -c mysql -- mysql -uroot -e "SET GLOBAL audit_log_policy='NONE';" 2>&1 | grep -v 'Using a password'
  $K exec "$p" -c mysql -- sh -c ': > /var/log/mysql/mysql-audit.log'
  echo "  $p audit_log_policy=$($K exec "$p" -c mysql -- mysql -uroot -N -e 'SELECT @@global.audit_log_policy;' 2>/dev/null)"
done
ARC_MIX=wide bash loadgen/warmup.sh
bash ops/cleanup.sh
NOTREADY=$($K get pods --no-headers | awk '{split($2,a,"/"); if (!(a[1]==a[2] && $3=="Running") && $3!="Completed") print $1, $2, $3}')
echo "pods not ready: ${NOTREADY:-none}"
NACOS=$(bash ops/nacos-health.sh 2>&1 | tail -1); echo "$NACOS"
if grep -q 'NOT READY' "$LOG" || [ -n "$NOTREADY" ] || ! echo "$NACOS" | grep -qE 'MISSING_OR_UNHEALTHY: *$'; then
  echo "$(date -u +%T) NOT resuming the campaign: something is not ready (see above)"
else
  ARC_MIX=wide ARC_RATE=4 ARC_SYNC=1 ARC_BACKUP=/mnt/c/Major_Project_ARC/arc-backup bash run/start-campaign.sh campaign 504 wide1
  echo "$(date -u +%T) campaign wide1 resumed"
fi
} 2>&1 | tee -a "$LOG"
touch "$HOME/arc-data/arc/logs/recover.DONE"
