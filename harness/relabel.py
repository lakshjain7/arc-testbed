#!/usr/bin/env python3
"""Recompute the labels of episodes already recorded (raw data is never changed).
Run it after calibrate_v2.py changed the thresholds, or after labels_v2.py itself changed.

  relabel.py                      every episode of every cluster under ARC_DATA_ROOT
  relabel.py ~/arc-data/arc/raw   every episode in that folder
"""
import glob, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import labels_v2 as L

roots = [os.path.expanduser(a) for a in sys.argv[1:]] or glob.glob(os.path.join(L.arcenv.DATA_ROOT, "*", "raw"))
done = failed = 0
for root in roots:
    for d in sorted(glob.glob(os.path.join(root, "*"))):
        if not os.path.exists(os.path.join(d, "op_counters.csv.gz")):
            continue
        try:
            L.label_episode(d)
            done += 1
        except Exception as e:           # one broken episode must not stop the rest
            failed += 1
            print(f"  could not label {os.path.basename(d)}: {e}")
print(f"relabelled {done} episodes, {failed} failed")
