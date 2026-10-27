#!/usr/bin/env bash
# Run the Online Boutique testbed with the same launcher as Train Ticket:
#   bash boutique/run.sh calibrate 20 | campaign 300 NAME | attach | stop
# It sets the variables that select the second application, its own calibration folder (thresholds fitted on
# Train Ticket must never label Boutique episodes) and the load (8 req/s), and forwards everything else.
export ARC_APP=boutique ARC_CLUSTER=boutique ARC_INDEX=1 ARC_MIX=boutique
export ARC_RATE="${ARC_RATE:-8}"
export ARC_CALIB="${ARC_CALIB:-${ARC_DATA_ROOT:-$HOME/arc-data}/calibration-boutique}"
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec bash run/start-campaign.sh "$@"
