"""Evolutionary search for the best strategy parameters ("poor man's GTO").

True GTO for 4-player mahjong is computationally out of reach, but the
Monte Carlo runner lets us search the strategy space empirically: a
population of parameterized strategies (examples/evolved_strategy.py)
plays a fixed reference field, the best survive, and mutated copies
replace the rest. The winner is written to my_strategies/gto.py.

    python3 -m examples.evolve --population 8 --generations 8 --games 2000

Each generation evaluates every variant with the same paired seeds (variance
reduction) against [greedy, defensive, random]; fitness is the variant's
average points per game.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

from mahjong_mc.engine import Game
from mahjong_mc.policies import make_policy
from examples.evolved_strategy import DEFAULT_PARAMS

_HERE = os.path.dirname(os.path.abspath(__file__))
_STRATEGY_PATH = os.path.join(_HERE, "evolved_strategy.py")
FIELD = ["greedy", "defensive", "random"]

# knob ranges for mutation
RANGES = {
    "safety_weight": (0.0, 4.0, 1.0),    # min, max, mutation step
    "riichi_mode": (0, 3, 1),
    "call_mode": (0, 2, 1),
    "kan_mode": (0, 2, 1),
    "honor_pair_keep": None,             # bool: flip
}


def _load_strategy():
    spec = importlib.util.spec_from_file_location("evolved_strategy",
                                                  _STRATEGY_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.EvoStrategy


def _eval_variant(args):
    """Play `games` games with the variant in seat 0; return avg points."""
    params, games, seed = args
    EvoStrategy = _load_strategy()
    field = [make_policy(n, seed * 1000 + i) for i, n in enumerate(FIELD)]
    total = 0
    for k in range(games):
        game_seed = seed * 1_000_003 + k
        variant = EvoStrategy(params=params, seed=game_seed)
        game = Game([variant] + field, seed=game_seed,
                    dealer=game_seed % 4)
        game.run()
        total += game.points[0] - game.rules.start_points
    return total / games if games else 0.0


def _random_params(rng):
    return {
        "safety_weight": round(rng.uniform(0.0, 4.0), 2),
        "riichi_mode": rng.randint(0, 3),
        "call_mode": rng.randint(0, 2),
        "kan_mode": rng.randint(0, 2),
        "honor_pair_keep": rng.random() < 0.5,
    }


def _mutate(params, rng):
    p = dict(params)
    knobs = [k for k in RANGES if RANGES[k] is not None]
    bools = [k for k in RANGES if RANGES[k] is None]
    for _ in range(rng.randint(1, 2)):
        if rng.random() < 0.7 and knobs:
            k = rng.choice(knobs)
            lo, hi, step = RANGES[k]
            if isinstance(lo, float):
                p[k] = round(min(hi, max(lo, p[k] + rng.uniform(-step, step))), 2)
            else:
                p[k] = min(hi, max(lo, p[k] + rng.choice((-step, step))))
        elif bools:
            k = rng.choice(bools)
            p[k] = not p[k]
    return p


def _fmt(params):
    return (f"sw={params['safety_weight']:<4} ri={params['riichi_mode']} "
            f"cl={params['call_mode']} kn={params['kan_mode']} "
            f"hp={int(params['honor_pair_keep'])}")


def evolve(population=8, generations=8, games=2000, seed=0, workers=0,
           elite_frac=0.4, out_path=None):
    rng = __import__("random").Random(seed)
    # seed the population with known-good and random variants
    pop = [dict(DEFAULT_PARAMS, safety_weight=2.0)]
    while len(pop) < population:
        pop.append(_random_params(rng))

    history = []
    for gen in range(generations):
        gen_seed = seed * 7919 + gen
        t0 = time.time()
        tasks = [(p, games, gen_seed) for p in pop]
        if workers and workers > 1:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                fitness = list(ex.map(_eval_variant, tasks))
        else:
            fitness = [_eval_variant(t) for t in tasks]
        ranked = sorted(zip(fitness, pop), key=lambda x: -x[0])
        best_fit, best = ranked[0]
        history.append({"gen": gen, "best": best_fit, "params": best})
        print(f"gen {gen}: best {best_fit:>8.1f} pts/game  "
              f"[{_fmt(best)}]  ({time.time() - t0:.0f}s)", flush=True)
        # elites survive; the rest are mutated copies of random elites
        n_elite = max(1, int(population * elite_frac))
        elites = [p for _, p in ranked[:n_elite]]
        pop = list(elites)
        while len(pop) < population:
            parent = rng.choice(elites)
            pop.append(_mutate(parent, rng))

    best_fit, best = history[-1]["best"], history[-1]["params"]
    print(f"\nwinner: {best_fit:.1f} pts/game  {json.dumps(best)}")
    if out_path:
        _write_policy(best, out_path)
        print(f"written to {out_path}")
    return best, history


_GTO_TEMPLATE = '''"""GTO-ish strategy — evolved by examples/evolve.py.

Evolved parameters (fitness {fitness:.0f} pts/game vs the reference field):

    safety_weight    = {safety_weight}
    riichi_mode      = {riichi_mode}   # 0 never / 1 always / 2 never vs riichi /
                                 # 3 damaten when waits are few
    call_mode        = {call_mode}     # 0 never / 1 shanten-improving /
                                 # 2 also shanten-equal with more ukeire
    kan_mode         = {kan_mode}      # 0 never / 1 honor or far / 2 any
    honor_pair_keep  = {honor_pair_keep}  # keep wind/dragon pairs

Re-run the search any time:

    python3 -m examples.evolve --population 8 --generations 8 --games 2000
"""

from __future__ import annotations

import random

from mahjong_mc.policies import Policy, register
from mahjong_mc.rules import shanten, ukeire


def _danger(view, t):
    """0 = safe (opponent discarded it), 1 = unseen, 2+ = wanted."""
    danger = 0
    for seat in range(4):
        if seat == view.seat:
            continue
        for ts, _ in view.melds_all[seat]:
            if t in ts:
                danger += 2
        if t in view.discards[seat]:
            return 0
    return danger or 1


@register
class GtoPolicy(Policy):
    name = "gto"

    def choose_discard(self, view):
        total = view.total_counts
        unseen = view.unseen_counts()
        scored = []
        best_s = 8
        for t in sorted(set(view.hand)):
            c = list(total)
            c[t] -= 1
            s = shanten(c)
            scored.append((s, t, c))
            if s < best_s:
                best_s = s
        best_key = None
        best_tile = None
        for s, t, c in scored:
            if s != best_s:
                continue
            avail = list(unseen)
            avail[t] = max(0, avail[t] - 1)
            _, copies = ukeire(c, avail)
            score = copies - {safety_weight} * _danger(view, t)
            if {honor_pair_keep} and t >= 27 and total[t] >= 2:
                score -= 2
            key = (-score, self.rng.random())
            if best_key is None or key < best_key:
                best_key, best_tile = key, t
        return best_tile

    def decide_call(self, view, tile, options):
        mode = {call_mode}
        if mode == 0 or not options:
            return None
        s0 = shanten(view.total_counts)
        best, best_key = None, None
        for act in options:
            kind, trio = act[0], act[1]
            if kind == "shouminkan":
                consumed = []
            else:
                consumed = list(trio)
                consumed.remove(tile)
            held = {{}}
            for x in view.hand:
                held[x] = held.get(x, 0) + 1
            for x in consumed:
                held[x] -= 1
            c = list(view.total_counts)
            c[tile] += 1
            s1 = None
            for x, n in held.items():
                if n <= 0:
                    continue
                c[x] -= 1
                s = shanten(c)
                if s1 is None or s < s1:
                    s1 = s
                c[x] += 1
            if s1 is None:
                continue
            if mode == 1:
                ok = s1 < s0
            else:
                ok = s1 < s0 or s1 == s0
            if ok:
                key = (s1,)
                if best_key is None or key < best_key:
                    best_key, best = key, act
        return best

    def decide_riichi(self, view):
        if not view.can_riichi:
            return False
        mode = {riichi_mode}
        if mode == 0:
            return False
        if mode == 2 and any(view.riichi[s] for s in range(4)
                             if s != view.seat):
            return False
        if mode == 3:
            types, _ = ukeire(view.total_counts, view.unseen_counts())
            if len(types) < 4:
                return False
        return True

    def decide_kan(self, view, tile, options):
        mode = {kan_mode}
        if mode == 0 or not options:
            return None
        if mode == 1 and not (tile >= 27 or shanten(view.total_counts) >= 2):
            return None
        return options[0]
'''


def _write_policy(params, path):
    body = _GTO_TEMPLATE.format(
        fitness=0.0,
        safety_weight=params["safety_weight"],
        riichi_mode=params["riichi_mode"],
        call_mode=params["call_mode"],
        kan_mode=params["kan_mode"],
        honor_pair_keep=repr(params["honor_pair_keep"]),
    )
    with open(path, "w") as f:
        f.write(body)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="mahjong-evolve",
        description="Evolve the best strategy parameters (approximate GTO)",
    )
    ap.add_argument("--population", type=int, default=8)
    ap.add_argument("--generations", type=int, default=8)
    ap.add_argument("--games", type=int, default=2000,
                    help="games per variant per generation")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "my_strategies", "gto.py"))
    args = ap.parse_args(argv)
    evolve(population=args.population, generations=args.generations,
           games=args.games, seed=args.seed, workers=args.workers,
           out_path=args.out)


if __name__ == "__main__":
    main()
