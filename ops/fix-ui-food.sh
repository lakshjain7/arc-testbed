#!/usr/bin/env bash
# OPTIONAL, only for demos through the website. Train Ticket's booking page ALWAYS sends foodType=1:
#  (1) client_ticket_book.html pre-fills <p id="sub_foodType">Station Food Stores</p>, so the
#      "is food chosen?" text check is never empty, and
#  (2) it tests text.indexOf("Train") as a boolean; -1 (not found) is truthy in JavaScript.
# With ts-food-service switched off, every website booking saves the order and THEN fails (HTTP 500).
# This patches the running nginx pod so food is sent only when "Need Food" is ticked.
# Lost when the ui-dashboard pod restarts: re-run it. The load generator never uses the page.
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
F=/usr/share/nginx/html/assets/js/client_ticket_book.js
POD=$($K get pods -l app=ts-ui-dashboard --no-headers | awk '{print $1}' | head -1)
$K exec "$POD" -- cat $F > "$ARC_DATA/logs/client_ticket_book.js.orig"
$K exec "$POD" -- sh -c "
  sed -i \"s|if (null != \\\$('#sub_foodType').text() \&\& \\\"\\\" != \\\$('#sub_foodType').text()) {|if (\\\$('#need-food-or-not').is(':checked')) {|\" $F
  sed -i 's|.indexOf(\"Train\")) {|.indexOf(\"Train\") >= 0) {|; s|.indexOf(\"Station\")) {|.indexOf(\"Station\") >= 0) {|' $F
"
$K exec "$POD" -- grep -n "need-food-or-not').is(':checked')) {\|indexOf(\"Train\") >= 0" $F
echo "patched. Press Ctrl+F5 on the booking page."
