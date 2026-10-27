#!/usr/bin/env bash
# Between episodes: put Online Boutique's business state back to the same size, so the healthy baseline cannot drift
# (the Train Ticket counterpart is ops/reset-data.sh, which trims the order tables). Boutique keeps one thing: the
# shopping carts in Redis. Run between episodes, never inside a measurement window.     reset-state.sh [ignored]
export ARC_APP=boutique
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
before=$($K exec deploy/redis-cart -- redis-cli dbsize 2>/dev/null | awk '{print $NF}')
$K exec deploy/redis-cart -- redis-cli flushall >/dev/null 2>&1 || { echo "reset-state: could not reach redis-cart"; exit 1; }
echo "reset-state: carts ${before:-?} -> 0"
