"""Compare baseline strategies head-to-head.

    python3 -m examples.compare_strategies --games 20000
    # or: cd ~/coding/mahjong-mc && python3 examples/compare_strategies.py

Runs the greedy shanten policy against the random and defensive baselines
and prints a win-rate table.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mahjong_mc.mc import run_batch, print_table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=0)
    args = ap.parse_args()

    matchups = [
        ("greedy vs random x3", ["greedy", "random", "random", "random"]),
        ("greedy vs defensive x3", ["greedy", "defensive"] * 2),
        ("all defensive", ["defensive"] * 4),
    ]
    for label, policies in matchups:
        print(f"\n=== {label} ===")
        stats = run_batch(args.games, policies, seed=args.seed,
                          workers=args.workers)
        print_table(stats)


if __name__ == "__main__":
    main()
