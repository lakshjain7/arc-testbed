#!/usr/bin/env python3
"""Recompute the labels of episodes already recorded (raw data is never changed).
Run it after calibrate_v2.py changed the thresholds, or after labels_v2.py itself changed.
The calibration used is the one in $ARC_CALIB (default <ARC_DATA_ROOT>/calibration): point it at the
right one for the episodes you relabel (one calibration per system and load mix).

  relabel.py                                   every episode of every cluster under ARC_DATA_ROOT
  relabel.py ~/arc-data/arc/raw                every episode in that folder
  relabel.py ~/arc-data/arc/raw/ep_wide1_*     only these episode folders (shell glob)
  ARC_CALIB=~/arc-data/calibration-wide relabel.py ~/arc-data/arc/raw/ep_wide1_* ~/arc-data/arc/raw/ep_cal_arc_02[1-9] ~/arc-data/arc/raw/ep_cal_arc_03? ~/arc-data/arc/raw/ep_cal_arc_040
"""
import glob, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import labels_v2 as L

args = [os.path.expanduser(a) for a in sys.argv[1:]] or glob.glob(os.path.join(L.arcenv.DATA_ROOT, "*", "raw"))
dirs = []
for a in args:
    if os.path.exists(os.path.join(a, "meta.json")):
        dirs.append(a)                                     # an episode folder
    else:
        dirs += sorted(glob.glob(os.path.join(a, "*")))    # a folder of episodes
print(f"calibration: {L.CAL_FILE}")
done = failed = 0
for d in dirs:
    if not os.path.exists(os.path.join(d, "op_counters.csv.gz")):
        continue
    try:
        L.label_episode(d)
        done += 1
    except Exception as e:           # one broken episode must not stop the rest
        failed += 1
        print(f"  could not label {os.path.basename(d)}: {e}")
print(f"relabelled {done} episodes, {failed} failed")
