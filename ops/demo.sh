#!/usr/bin/env bash
# One user journey through Train Ticket, with proof at every layer. Pauses at each step.
#   ops/demo.sh            (keep the live viewer open beside it)
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
U=$UI_URL
pause() { echo; read -rp "   [Enter] for next step " _; echo; }
SQL() { $K exec tsdb-mysql-0 -c mysql -- mysql -uroot "$@" 2>/dev/null; }

echo "STEP 1  Is the system healthy?  (cluster $ARC_CLUSTER)"
tot=$($K get pods --no-headers | grep -c '^ts-'); rdy=$($K get pods --no-headers | grep '^ts-' | grep -c ' 1/1 ')
echo "   $rdy of $tot Train Ticket services are running and ready"
pause

echo "STEP 2  Log in as the test user (fdse_microservice)"
L=$(curl -s -m 60 -X POST "$U/api/v1/users/login" -H 'Content-Type: application/json' -d '{"username":"fdse_microservice","password":"111111"}')
TOKEN=$(echo "$L" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['token'])" 2>/dev/null)
UID_=$(echo "$L" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['userId'])" 2>/dev/null)
[ -n "$TOKEN" ] && echo "   logged in, got a session token" || { echo "   login FAILED: $L"; exit 1; }
pause

D=$(date -d "+1 day" +%F)
echo "STEP 3  Search trains Shanghai -> Suzhou for $D"
curl -s -m 90 -X POST "$U/api/v1/travelservice/trips/left" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"startPlace\":\"shanghai\",\"endPlace\":\"suzhou\",\"departureTime\":\"$D\"}" -o /tmp/arc-s.json -w "   HTTP %{http_code} in %{time_total}s\n"
python3 - <<'PY'
import json
try:
    d = json.load(open('/tmp/arc-s.json')).get('data') or []
except Exception:
    d = []
print("   %d trains found:" % len(d))
for t in d[:4]:
    tid = t.get('tripId', {}); tid = tid.get('type', '') + tid.get('number', '') if isinstance(tid, dict) else tid
    print("     %-6s  1st class %s / 2nd class %s yuan" % (tid, t.get('priceForConfortClass'), t.get('priceForEconomyClass')))
PY
pause

before=$(SQL -N -e "select count(*) from ts.orders")
echo "STEP 4  Book a 1st-class seat (seatType 2, 50 yuan) on D1345   (orders in database right now: $before)"
CID=$(curl -s -m 60 "$U/api/v1/contactservice/contacts/account/$UID_" -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json; print(json.load(sys.stdin)['data'][0]['id'])")
curl -s -m 180 -X POST "$U/api/v1/preserveservice/preserve" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"accountId\":\"$UID_\",\"contactsId\":\"$CID\",\"tripId\":\"D1345\",\"seatType\":2,\"loginToken\":\"$TOKEN\",\"date\":\"$D\",\"from\":\"shanghai\",\"to\":\"suzhou\",\"assurance\":0,\"foodType\":0,\"isWithin\":false}" \
  -o /tmp/arc-b.json -w "   HTTP %{http_code} in %{time_total}s  "
python3 -c "import json; d=json.load(open('/tmp/arc-b.json')); print('->', d.get('msg'))" 2>/dev/null || echo "-> no JSON (timeout?)"
pause

sleep 2
after=$(SQL -N -e "select count(*) from ts.orders")
echo "STEP 5  Ground truth: did the database record it?   orders: $before -> $after"
SQL -t -e "select train_number, from_station, to_station, travel_date, seat_number, price, bought_date from ts.orders order by bought_date desc limit 1"
echo "   (The HTTP code alone can lie: a 504 can still save an order.)"
pause

echo "STEP 6  Now look at http://localhost:$VIEWER_PORT : in ~10-20 s the booking path turns green"
echo "   gateway -> preserve -> contacts, travel, seat, order, security, user, basic -> MySQL"
