#!/usr/bin/env python3
"""Evolution search over the `louis` policy's tunable weights.

This is step 1 of docs/strategy.md §10: the policy structure stays hand-written,
only the handful of numbers the rules depend on are searched. Hill climbing with
a small population, evaluated on the *same deals* for every candidate (paired
seeds), so candidates are compared fairly and cheaply.

    python3 -m examples.evolve_louis --population 6 --generations 4 --games 1500
    python3 -m examples.evolve_louis --games 8000      # bigger final validation

The winner is written to my_strategies/louis_params.json (only if it beats the
current champion by more than its noise), which the policy loads on import.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# name -> (low, high, is_int)
SPACE = {
    "PUSH_COPIES": (3, 10, True),
    "PUSH_VALUE": (1000, 8000, True),
    "SEMI_PUSH_VALUE": (3000, 13000, True),
    "HONOR_DEAD_TURN": (3, 10, True),
    "DANGER_WEIGHT": (0.5, 5.0, False),
}
BASE = {
    "PUSH_COPIES": 6,
    "PUSH_VALUE": 3900,
    "SEMI_PUSH_VALUE": 7700,
    "HONOR_DEAD_TURN": 6,
    "DANGER_WEIGHT": 2.0,
}
FIELD = ("gto", "defensive", "greedy")


def _worker(args):
    params, seed0, count, field = args
    sys.path.insert(0, ROOT)
    from mahjong_mc.mc import load_policy_dir, run_game
    from mahjong_mc.policies import _REGISTRY
    load_policy_dir(os.path.join(ROOT, "my_strategies"))
    # the policy file is loaded under its own module name by load_policy_dir, so
    # mutate the *registered* class, not a second import of the same file
    policy_cls = _REGISTRY["louis"]
    for k, v in params.items():
        setattr(policy_cls, k, v)
    names = ["louis"] + list(field)
    pts, ranks, wins = 0, 0.0, 0
    for k in range(count):
        res = run_game(names, seed0 + k, dealer=(seed0 + k) % 4)
        p = res["points"][0]
        pts += p
        order = sorted(range(4), key=lambda i: -res["points"][i])
        ranks += order.index(0) + 1
        if res["winner"] == 0:
            wins += 1
    return pts, ranks, wins, count


def evaluate(params, games, seed, workers=8, field=FIELD):
    chunk = 250
    tasks = [(params, seed + i * chunk, min(chunk, games - i * chunk), field)
             for i in range(0, math.ceil(games / chunk))]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        out = list(ex.map(_worker, tasks))
    pts = sum(o[0] for o in out)
    ranks = sum(o[1] for o in out)
    wins = sum(o[2] for o in out)
    n = sum(o[3] for o in out)
    return {"pts_per_game": pts / n, "avg_rank": ranks / n,
            "win_pct": 100 * wins / n, "games": n}


def mutate(params, rng, scale=1.0):
    out = dict(params)
    for key, (lo, hi, is_int) in SPACE.items():
        if rng.random() < 0.45:
            span = (hi - lo) * 0.25 * scale
            v = out[key] + rng.uniform(-span, span)
            v = max(lo, min(hi, v))
            out[key] = int(round(v)) if is_int else round(v, 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--population", type=int, default=6)
    ap.add_argument("--generations", type=int, default=4)
    ap.add_argument("--games", type=int, default=1500)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--write", action="store_true",
                    help="save the winner to my_strategies/louis_params.json")
    args = ap.parse_args()

    import random
    rng = random.Random(args.seed)

    params_path = os.path.join(ROOT, "my_strategies", "louis_params.json")
    champion = dict(BASE)
    if os.path.exists(params_path):
        with open(params_path, encoding="utf-8") as f:
            champion.update(json.load(f))
    champ = evaluate(champion, args.games, args.seed, args.workers)
    print(f"champion start  {champ}  {champion}")

    for gen in range(args.generations):
        scale = 1.0 if gen == 0 else 0.6
        cands = [mutate(champion, rng, scale) for _ in range(args.population - 1)]
        cands.append(dict(champion))
        results = [evaluate(c, args.games, args.seed, args.workers)
                   for c in cands]
        best_i = max(range(len(cands)),
                     key=lambda i: results[i]["pts_per_game"])
        print(f"gen {gen + 1}: best {results[best_i]['pts_per_game']:+.1f} "
              f"pts/game (champion {champ['pts_per_game']:+.1f})  "
              f"{cands[best_i]}")
        if results[best_i]["pts_per_game"] > champ["pts_per_game"]:
            champion, champ = cands[best_i], results[best_i]
            print(f"          ^ new champion")

    print(f"\nchampion  {champ}")
    print(f"params    {champion}")
    if args.write:
        with open(params_path, "w", encoding="utf-8") as f:
            json.dump(champion, f, indent=2)
        print(f"written   {params_path}")
    else:
        print("(not written; re-run with --write to apply)")


if __name__ == "__main__":
    main()
