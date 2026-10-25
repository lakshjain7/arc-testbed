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
# orders_other holds bookings on the other train types (K/Z/T); it is empty unless that flow is in the mix
before=$(SQL "select (select count(*) from orders) + (select count(*) from orders_other)")
out=$(SQL "delete from orders where account_id='$ACC' and bought_date < now() - interval $KEEP minute;
           delete from orders_other where account_id='$ACC' and bought_date < now() - interval $KEEP minute;
           delete p from payment p left join orders o on o.id = p.order_id left join orders_other x on x.id = p.order_id where o.id is null and x.id is null;
           delete i from inside_payment i left join orders o on o.id = i.order_id left join orders_other x on x.id = i.order_id where o.id is null and x.id is null;
           delete a from assurance a left join orders o on o.id = a.order_id left join orders_other x on x.id = a.order_id where o.id is null and x.id is null;
           delete from inside_money where user_id='$ACC' and type='D';")
# assurance (insurance bought with a booking, linked by order_id) and inside_money (refund rows 'D' written by
# every cancel; no order link, no timestamp) were never cleaned: in wide2 they reached 170k and 61k rows and the
# cancel flow slowed from 77 to 131 ms over two days (findings F21). The load account's single 'A' row in
# inside_money is not a refund and is kept.
[ -n "$out" ] && echo "reset-data: MySQL said: $out"
after=$(SQL "select (select count(*) from orders) + (select count(*) from orders_other)")
# MySQL writes every query to an audit log with no size limit (lab machine: 9.2 GB in 49 h at 4 req/s,
# enough to fill the disk mid-campaign). Empty it in place on every MySQL pod. The audit setting itself is
# left alone so the database behaves the same in every episode. Tested with MySQL running: the file
# restarts from 0 and grows normally, no failed request, no restart.
for p in $($K get pods --no-headers 2>/dev/null | awk '/^(tsdb|nacosdb)-mysql-[0-9]+/{print $1}'); do
  $K exec "$p" -c mysql -- sh -c ': > /var/log/mysql/mysql-audit.log' >/dev/null 2>&1
done
echo "reset-data ($LEADER): orders $before -> $after (kept last ${KEEP} min)"
