#!/usr/bin/env bash
# Rebuild the dataset spreadsheets and copy everything that matters to a second place.
# The cluster and Prometheus keep nothing permanently: the episode folders ARE the dataset.
#
#   ARC_BACKUP=/mnt/c/Users/<you>/OneDrive/ARC-data run/sync-data.sh     (Windows + WSL: a OneDrive folder)
#   ARC_BACKUP=/media/<you>/USB/ARC-data            run/sync-data.sh     (Ubuntu: a USB disk / second drive)
#   ARC_BACKUP=user@host:/path/ARC-data             run/sync-data.sh     (another machine, over ssh)
#   run/sync-data.sh --tar            also write one arc-data-<date>.tar.gz next to the data (easy to upload)
#
# Copied: raw/ (episodes + labels), plans/, calibration/, index/, logs/. Not copied: loadgen/ (the
# per-request logs are already cut into each episode's client.csv.gz).
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
python3 "$ARC_ROOT/harness/build_index.py"
if [ -n "${ARC_BACKUP:-}" ]; then
  case "$ARC_BACKUP" in *:*) ;; *) mkdir -p "$ARC_BACKUP" ;; esac
  # --no-perms/--no-owner/--no-group: Windows and USB file systems cannot store Linux permissions
  rsync -rt --no-perms --no-owner --no-group --exclude 'loadgen/' --exclude '*.tar.gz' "$ARC_DATA_ROOT/" "$ARC_BACKUP/" \
    && say "copied to $ARC_BACKUP ($(du -sh --exclude=loadgen "$ARC_DATA_ROOT" | cut -f1))" || say "COPY FAILED: $ARC_BACKUP"
else
  say "ARC_BACKUP is not set: spreadsheets rebuilt, nothing copied"
fi
if [ "${1:-}" = "--tar" ]; then
  T="$ARC_DATA_ROOT/arc-data-$(hostname)-$(date +%F).tar.gz"
  tar -czf "$T" -C "$ARC_DATA_ROOT" --exclude='loadgen' --exclude='*.tar.gz' . && say "wrote $T ($(du -h "$T" | cut -f1))"
fi
