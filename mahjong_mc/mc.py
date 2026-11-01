"""Monte Carlo runner and CLI (Japanese rules).

    python -m mahjong_mc --games 100000 --policies greedy,random,random,random

Plays N games (optionally across all CPU cores) and reports per-seat
win rate, tumo/ron split, deal-in rate, riichi rate, average points
(han/fu scoring, dealer rotates so every seat plays oya equally often)
and average rank.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

from .engine import Game, Rules
from .policies import Policy, available, make_policy, register


def load_policy_file(path: str) -> list[str]:
    """Import a .py file of user-defined policies and register them.

    Any `Policy` subclass with a `name` attribute in the file becomes
    available to --policies. Returns the names found in the file.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("mahjong_user_policies", path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"cannot load policy file: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # the file may register its policies itself (via @register) or just
    # define the classes; either way, make sure each is registered
    found = []
    for obj in vars(mod).values():
        if (isinstance(obj, type) and issubclass(obj, Policy)
                and obj is not Policy and getattr(obj, "name", None)):
            register(obj)
            if obj.name not in found:
                found.append(obj.name)
    return found


def load_policy_dir(directory: str) -> list[str]:
    """Load every .py file in a directory (skips __init__.py)."""
    loaded = []
    if not os.path.isdir(directory):
        return loaded
    for fn in sorted(os.listdir(directory)):
        if fn.endswith(".py") and not fn.startswith("_"):
            try:
                loaded.extend(load_policy_file(os.path.join(directory, fn)))
            except Exception as exc:  # keep going; report the bad file
                print(f"warning: failed to load {fn}: {exc}", file=sys.stderr)
    return loaded


def run_game(policies, seed, rules=None, dealer=0):
    """Play one game. `policies` is 4 policy names (str) or instances."""
    pols = [
        make_policy(p, seed * 1_000_003 + i) if isinstance(p, str) else p
        for i, p in enumerate(policies)
    ]
    game = Game(pols, rules=rules, seed=seed, dealer=dealer)
    game.run()
    res = game.result()
    # points delta from the 25000 start
    res["points"] = [p - game.rules.start_points for p in res["points"]]
    return res


def _rank(points):
    """Competition ranking: 1 = best. Ties share the rank."""
    return [1 + sum(1 for q in points if q > p) for p in points]


def _run_chunk(args):
    """Worker: play `count` games starting at `seed0`; return aggregate stats."""
    seed0, count, names, rules, policy_files, policy_dirs = args
    for pf in policy_files or ():
        load_policy_file(pf)
    for pd in policy_dirs or ():
        load_policy_dir(pd)
    # per seat: games, wins, tumo, ron, dealt_in, points, riichi, draws
    acc = [[0] * 8 for _ in range(4)]
    rank_sums = [0.0] * 4
    for k in range(count):
        res = run_game(names, seed0 + k, rules,
                       dealer=(seed0 + k) % 4)
        pts = res["points"]
        ranks = _rank(pts)
        for i in range(4):
            a = acc[i]
            a[0] += 1
            if res["winner"] == i:
                a[1] += 1
                a[2 if res["kind"] == "tumo" else 3] += 1
            if res["loser"] == i:
                a[4] += 1
            a[5] += pts[i]
            a[6] += 1 if (res["riichi"] and res["riichi"][i]) else 0
            a[7] += 1 if res["kind"] == "draw" else 0
            rank_sums[i] += ranks[i]
    return acc, rank_sums


def run_batch(games, policies, seed=0, workers=0, rules=None,
              policy_file=None, policy_dirs=()):
    """Play `games` games with the 4 named policies; return aggregate stats.

    `policy_file` / `policy_dirs` are user strategy sources; they are
    (re)loaded inside every worker process so custom names work in
    parallel runs. The dealer rotates one seat per game so every seat
    plays oya equally often.
    """
    if len(policies) != 4:
        raise ValueError("exactly 4 policies required")
    if workers is None or workers <= 0:
        workers = os.cpu_count() or 1
    policy_files = [policy_file] if policy_file else []
    chunk = max(1, games // (workers * 8) or 1)
    tasks = []
    start = 0
    while start < games:
        n = min(chunk, games - start)
        tasks.append((seed + start, n, list(policies), rules,
                      tuple(policy_files), tuple(policy_dirs or ())))
        start += n
    t0 = time.time()
    if workers == 1 or len(tasks) == 1:
        results = [_run_chunk(t) for t in tasks]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_run_chunk, tasks))
    elapsed = time.time() - t0

    acc = [[0] * 8 for _ in range(4)]
    rank_sums = [0.0] * 4
    for a, rs in results:
        for i in range(4):
            for j in range(8):
                acc[i][j] += a[i][j]
            rank_sums[i] += rs[i]

    rows = []
    for i, name in enumerate(policies):
        n, wins, tumo, ron, dealt, pts, riichi, draws = acc[i]
        rows.append({
            "seat": i,
            "policy": name,
            "games": n,
            "wins": wins,
            "win_rate": wins / n if n else 0.0,
            "tumo": tumo,
            "ron": ron,
            "dealt_in": dealt,
            "deal_in_rate": dealt / n if n else 0.0,
            "riichi": riichi,
            "riichi_rate": riichi / n if n else 0.0,
            "draws": draws,
            "draw_rate": draws / n if n else 0.0,
            "avg_points": pts / n if n else 0.0,
            "avg_rank": rank_sums[i] / n if n else 0.0,
        })
    return {
        "rows": rows,
        "games": games,
        "seed": seed,
        "elapsed_s": elapsed,
        "games_per_s": games / elapsed if elapsed > 0 else 0.0,
    }


def print_table(stats, out=sys.stdout):
    rows = stats["rows"]
    hdr = (f"{'seat':>4} {'policy':<12} {'win%':>7} {'tumo%':>7} {'ron%':>7} "
           f"{'deal-in%':>9} {'riichi%':>8} {'pts/game':>9} {'avg rank':>9}")
    print(hdr, file=out)
    print("-" * len(hdr), file=out)
    for r in rows:
        print(f"{r['seat']:>4} {r['policy']:<12} "
              f"{100 * r['win_rate']:>6.2f}% "
              f"{100 * r['tumo'] / r['games']:>6.2f}% "
              f"{100 * r['ron'] / r['games']:>6.2f}% "
              f"{100 * r['deal_in_rate']:>8.2f}% "
              f"{100 * r['riichi_rate']:>7.2f}% "
              f"{r['avg_points']:>9.1f} "
              f"{r['avg_rank']:>9.3f}", file=out)
    gps = stats["games_per_s"]
    print(f"\ngames: {stats['games']}  seed: {stats['seed']}  "
          f"elapsed: {stats['elapsed_s']:.1f}s  ({gps:,.0f} games/s)", file=out)
    if gps > 0:
        print(f"1,000,000 games ≈ {1_000_000 / gps / 60:.1f} min on this machine",
              file=out)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="mahjong-mc",
        description="Monte Carlo Mahjong (Japanese rules): test strategies "
                    "over many games",
    )
    p.add_argument("--games", type=int, default=1000,
                   help="number of games to simulate (default 1000)")
    p.add_argument("--policies", required=True,
                   help="comma-separated list of exactly 4 policy names "
                        f"(built-in: {', '.join(available())})")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--workers", type=int, default=0,
                   help="process count; 0 = all cores")
    p.add_argument("--no-chi", action="store_true")
    p.add_argument("--no-peng", action="store_true")
    p.add_argument("--no-kan", action="store_true")
    p.add_argument("--json", metavar="PATH",
                   help="also write the full stats as JSON")
    p.add_argument("--policy-file", metavar="PATH",
                   help="python file defining extra policies; its policies "
                        "become available to --policies")
    p.add_argument("--policy-dir", metavar="DIR",
                   help="directory of .py policy files (default: "
                        "my_strategies/ next to the package if it exists)")
    args = p.parse_args(argv)

    # custom strategies: explicit file, then the conventional directory
    loaded = []
    if args.policy_file:
        loaded.extend(load_policy_file(args.policy_file))
    if args.policy_dir is None:
        default_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "my_strategies")
        if os.path.isdir(default_dir):
            args.policy_dir = default_dir
    policy_dirs = []
    if args.policy_dir:
        policy_dirs.append(os.path.abspath(args.policy_dir))
        loaded.extend(load_policy_dir(args.policy_dir))
    if loaded:
        print(f"loaded policies: {', '.join(sorted(set(loaded)))}")

    names = [s.strip() for s in args.policies.split(",") if s.strip()]
    if len(names) != 4:
        p.error("--policies needs exactly 4 comma-separated names")
    for n in names:
        if n not in available():
            hint = ("; put your strategy in my_strategies/ (auto-loaded) "
                    "or pass --policy-file PATH"
                    if not args.policy_file and not args.policy_dir else "")
            p.error(f"unknown policy {n!r}; available: "
                    f"{', '.join(available())}{hint}")

    rules = Rules(allow_chi=not args.no_chi, allow_peng=not args.no_peng,
                  allow_kan=not args.no_kan)
    stats = run_batch(args.games, names, seed=args.seed,
                      workers=args.workers, rules=rules,
                      policy_file=args.policy_file,
                      policy_dirs=tuple(policy_dirs))
    print_table(stats)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(stats, f, indent=2)
        print(f"stats written to {args.json}")


if __name__ == "__main__":
    main()
