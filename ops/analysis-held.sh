#!/usr/bin/env bash
# Held-out faults analysis (decision log 10g): ARC trained WITHOUT the held faults, tested on them.
#   ops/analysis-held.sh HELD_DATASET.jsonl [SEEDS=5]
# HELD_DATASET is built from the held archive (harness/build_dataset.py RAW --plans held --out ..., ARC_CALIB = calibration-wide-8c).
# Training set A = wide1 + wide1db; B = A + the first half of wide2 (before the cancel drift). Output goes to stdout.
HELD=${1:?held dataset}; S=${2:-5}
cd "$(dirname "${BASH_SOURCE[0]}")/.." ; PY=${PY:-python3}; D=${TRAIN_DIR:-$HOME/arc-wide2}
for T in A_wide1_wide1db B_A_plus_wide2first; do
  echo "################ trained on $T, tested on the held-out faults"
  echo "## baselines";           $PY harness/baselines.py $D/train_$T.jsonl --test $HELD | grep -E "B0 zero|B1 action|B3 role|B5 dep|B6 trees"
  echo "## ARC (graph model)";   $PY harness/train_gnn.py $D/train_$T.jsonl --test $HELD --seeds $S --drop latency --calls --by-fault --by-condition | grep -E "^GNN|yes/no|fault |condition "
  echo "## ARC + few examples of the new faults (first k blocks of held added to training)"
  for k in 2 4 6; do $PY harness/train_gnn.py $D/train_$T.jsonl --test $HELD --topup $k --seeds 3 --drop latency --calls | grep -E "top-up|^GNN"; done
  echo "## not-sure signal and 90/10 blend"; $PY harness/extras.py $D/train_$T.jsonl --test $HELD --seeds 5 | grep -E "ensemble|not-sure|novelty above|blend w=(0.90|1.00)|T13"
  echo "## three-way gate";      $PY harness/gate3.py $D/train_$T.jsonl --test $HELD --seeds 5 | grep -E "block >= 20|test actions"
done
