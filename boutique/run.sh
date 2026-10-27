#!/usr/bin/env bash
# Run the Online Boutique testbed with the same launcher as Train Ticket:
#   bash boutique/run.sh calibrate 20 | campaign 300 NAME | attach | stop | smoke
# It only sets the three variables that select the second application and forwards everything else.
export ARC_APP=boutique ARC_CLUSTER=boutique ARC_INDEX=1 ARC_MIX=boutique
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec bash run/start-campaign.sh "$@"
