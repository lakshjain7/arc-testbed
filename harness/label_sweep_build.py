#!/usr/bin/env python3
"""Label-sensitivity sweep, step 2: one dataset per bar, in the format the evaluation scripts already read.

  label_sweep_build.py DATASET.jsonl SWEEP.jsonl OUT_PREFIX

For each bar T writes OUT_PREFIX_T<T>.jsonl: the same episodes, graphs and splits, with
  y_mean, y_peak   replaced by the damage under bar T,
  bad_before       replaced by the smoothed bad share before the action under bar T (an INPUT: it must use the same
                   bar as the target, otherwise the input would describe a different definition of "bad"),
  n_before, n_after unchanged (they count requests, not bad requests).
All other inputs (rates, errors, CPU, memory, readiness) are untouched; latency ratios are not used by ARC anyway.
"""
import json, sys


def main(ds, sweep, prefix):
    sw = {}
    for l in open(sweep):
        r = json.loads(l); sw[r["episode_id"]] = r["bars"]
    bars = sorted({T for b in sw.values() for T in b}, key=int)
    outs = {T: open(f"{prefix}_T{T}.jsonl", "w") for T in bars}
    kept = 0
    for l in open(ds):
        e = json.loads(l)
        if e["episode_id"] not in sw:
            continue
        kept += 1
        for T in bars:
            b = sw[e["episode_id"]][T]
            nodes = []
            for n in e["nodes"]:
                v = b.get(n["service"])
                x, y = dict(n["x"]), dict(n["y"])
                if v:
                    nb = v["n_B1L"] or 0
                    x["bad_before"] = (v["p_B1L"] * nb + 0.5) / (nb + 1)
                    y["y_mean"], y["y_peak"] = v["y_mean"], v["y_peak"]
                else:
                    y["y_mean"] = y["y_peak"] = None
                nodes.append({"service": n["service"], "x": x, "y": y})
            outs[T].write(json.dumps(dict(e, nodes=nodes)) + "\n")
    for f in outs.values():
        f.close()
    print(f"{kept} episodes, bars {bars}: wrote {prefix}_T<bar>.jsonl")


if __name__ == "__main__":
    main(*sys.argv[1:4])
