#!/usr/bin/env python3
"""B8: a large language model as the damage predictor (what "just ask an LLM agent" would give).

  llm_baseline.py DATASET.jsonl [--test OTHER.jsonl] [--limit 10] [--shots 3] [--model gpt-5] [--price 1.25,10]

For each test episode the model gets the same information ARC gets (each service's state before the action,
its role relative to the action target, the call graph, the action) plus --shots solved training episodes
with the same action type, and returns the predicted damage (y_peak, in points) of every service.
Scored exactly like baselines.py. Prints tokens, cost and seconds per episode.
The key is read from OPENAI_API_KEY (source ~/.arc-secrets first); it is never written anywhere.
Answers are cached in ~/arc-llm-cache.jsonl so a rerun does not pay twice.
"""
import json, os, random, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from baselines import load, roles, scored, spearman

from openai import OpenAI
FE = ["rps_ratio", "err_share", "p95_ratio", "cpu_use_frac", "throttled", "not_ready", "bad_before"]
SYSTEM = """You predict the side effects of a remediation action in a microservice system (Train Ticket).
You get the state of every service just before the action, the call graph (caller -> callee) and the action.
For every service, predict its damage: the worst 30-second rise in its share of bad requests (errors or slow
replies) during the 3 minutes after the action, in percentage points (0 = not hurt, 100 = everything fails).
Answer with one JSON object mapping each service name to a number, and nothing else."""


def describe(ep, with_answer=False):
    r = roles(ep)
    lines = [f"Action: {ep['action']['type']} on {ep['action']['target'] or '(nothing)'}",
             "Calls: " + ", ".join(f"{e['src']}->{e['dst']}" for e in ep["edges"]),
             "Services (role relative to the action target; state before the action):"]
    for n in ep["nodes"]:
        x = ", ".join(f"{k}={n['x'][k]:.2f}" for k in FE if n["x"].get(k) is not None)
        lines.append(f"  {n['service']} [{r[n['service']]}] {x}")
    if with_answer:
        lines.append("Answer: " + json.dumps({n["service"]: round(100 * y, 1) for n, y in scored(ep, "y_peak")}))
    return "\n".join(lines)


def main(args):
    eps = load(args[0]); g = lambda k, d: args[args.index(k) + 1] if k in args else d
    model = g("--model", "gpt-5"); shots = int(g("--shots", 3)); limit = int(g("--limit", 10))
    train = [e for e in eps if e["split"] == "train"]
    test = load(g("--test", None)) if "--test" in args else [e for e in eps if e["split"] == "test"]
    test = [e for e in test if any(True for _ in scored(e, "y_peak"))]
    random.Random(0).shuffle(test); test = test[:limit]
    cache_path = os.path.expanduser("~/arc-llm-cache.jsonl")
    cache = {}
    if os.path.exists(cache_path):
        for l in open(cache_path):
            c = json.loads(l); cache[(c["model"], c["shots"], c["episode"])] = c
    client = OpenAI()
    rng = random.Random(1); tin = tout = 0; secs = []; err = cnt = 0; rhos = []; hits = n_hit = 0; bad = 0
    for i, ep in enumerate(test):
        key = (model, shots, ep["episode_id"])
        if key not in cache:
            same = [e for e in train if e["action"]["type"] == ep["action"]["type"]]
            ex = rng.sample(same, min(shots, len(same)))
            prompt = "".join(f"Solved example {k + 1}:\n{describe(e, True)}\n\n" for k, e in enumerate(ex)) + "Now predict:\n" + describe(ep)
            t = time.perf_counter()
            resp = client.chat.completions.create(model=model, response_format={"type": "json_object"},
                                                  messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}])
            dt = time.perf_counter() - t
            text = resp.choices[0].message.content or ""
            cache[key] = c = {"model": model, "shots": shots, "episode": ep["episode_id"], "answer": text, "seconds": dt,
                              "in": resp.usage.prompt_tokens, "out": resp.usage.completion_tokens, "stop": resp.choices[0].finish_reason}
            with open(cache_path, "a") as f:
                f.write(json.dumps(c) + "\n")
        c = cache[key]; tin += c["in"]; tout += c["out"]; secs.append(c["seconds"])
        try:
            t = c["answer"]; pred = json.loads(t[t.index("{"): t.rindex("}") + 1])
        except Exception:
            pred = {}; bad += 1
        ys, ps = [], []
        for n, y in scored(ep, "y_peak"):
            p = float(pred.get(n["service"], 0.0)) / 100
            err += abs(p - y); cnt += 1; ys.append(y); ps.append(p)
        if len(ys) >= 3:
            rho = spearman(ps, ys)
            if rho is not None:
                rhos.append(rho)
            if max(ys) > 0.05:
                n_hit += 1; hits += ys.index(max(ys)) == ps.index(max(ps))
        print(f"  {i + 1}/{len(test)} {ep['episode_id']}: {c['seconds']:.1f} s", flush=True)
    pi, po = (float(v) for v in g("--price", "0,0").split(","));   # $ per 1M input / output tokens, from the provider's price page
    cost = (tin * pi + tout * po) / 1e6
    print(f"B8 {model}, {shots} examples, {len(test)} episodes ({bad} unreadable answers): MAE {100 * err / max(cnt, 1):.2f}, "
          f"Spearman {sum(rhos) / max(len(rhos), 1):.3f}, top-1 {hits / max(n_hit, 1):.2f}")
    print(f"  cost ${cost:.2f} (${cost / max(len(test), 1):.3f} per episode, {tin} in / {tout} out tokens); "
          f"{sum(secs) / max(len(secs), 1):.1f} s per episode on average (ARC: about 0.004 s)")


if __name__ == "__main__":
    main(sys.argv[1:])
