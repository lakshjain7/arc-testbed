#!/usr/bin/env bash
# Keep the database at a steady size so the healthy baseline doesn't drift.
# Measured: 18 h of 2 req/s load grew orders to 14,372 rows; order-list p95 went from ~100 ms to
# ~1,500 ms and bookings from ~250 ms to ~1,800 ms, because the order list returns EVERY order of
# the test account and seat availability counts sold tickets.
# Deletes the load account's orders older than KEEP_MIN minutes (the load generator only pays
# orders seen in the last 5 min) plus orphaned payment rows. Writes go to the MySQL LEADER.
# Run between episodes, never inside a measurement window.     reset-data.sh [KEEP_MIN=10]
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
KEEP=${1:-10}
ACC=4d2a46c7-71cb-4cf1-b5bb-b68406d9da6f     # fdse_microservice, the only account the load uses
LEADER=$(bash "$ARC_ROOT/ops/mysql-leader.sh") || { echo "reset-data: no writable MySQL leader found"; exit 1; }
SQL() { $K exec "$LEADER" -c mysql -- mysql -uroot -N ts -e "$1" 2>&1 | grep -v "Using a password"; }
before=$(SQL "select count(*) from orders")
out=$(SQL "delete from orders where account_id='$ACC' and bought_date < now() - interval $KEEP minute;
           delete p from payment p left join orders o on o.id = p.order_id where o.id is null;
           delete i from inside_payment i left join orders o on o.id = i.order_id where o.id is null;")
[ -n "$out" ] && echo "reset-data: MySQL said: $out"
after=$(SQL "select count(*) from orders")
echo "reset-data ($LEADER): orders $before -> $after (kept last ${KEEP} min)"
