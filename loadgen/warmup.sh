#!/usr/bin/env bash
# Gentle warm-up after any restart: ramp the load so cold JVMs can compile before full traffic.
# Jumping straight to 2 req/s on cold services piled up and gave 90% timeouts.
#   loadgen/warmup.sh            0.3 -> 0.6 -> 1.0 req/s, 120 s each   (RATES="..." SECS=... to change)
. "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
for r in ${RATES:-0.3 0.6 1.0}; do
  python3 "$ARC_ROOT/loadgen/loadgen.py" --rate "$r" --duration "${SECS:-120}" --print-every 1000 >/dev/null 2>&1
  RUN=$(ls -d "$ARC_DATA"/loadgen/run-* | sort | tail -1)
  python3 - "$RUN" "$r" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1] + "/requests.jsonl")]
last = [r for r in rows if r["t"] >= max(x["t"] for x in rows) - 60] if rows else []
ok = sum(r["ok"] for r in last); ms = sorted(r["ms"] for r in last if r["ok"])
print(f"  {sys.argv[2]} req/s: whole stage {sum(r['ok'] for r in rows)}/{len(rows)} ok | last 60 s {ok}/{len(last)} ok, median {ms[len(ms)//2] if ms else '-'} ms")
PY
done
echo WARMUP DONE
