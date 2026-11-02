#!/usr/bin/env python3
"""Paired A/B test between two policies, with a confidence interval.

Why paired: in a 4-seat field both policies play the *same deals*, so the
per-game score difference cancels the deal luck that makes unpaired per-seat
averages so noisy. The variance of the difference is what decides how many
games are needed.

    python3 tools/ab_test.py --pilot 2000          # measure variance, tell N
    python3 tools/ab_test.py --games 20000         # run the real test

Seats rotate per game (A and B sit in every seat pair equally often) and the
dealer is chosen independently of where A sits, so neither policy gets a
positional edge. Fixed seats matter: seat 0 used to beat itself by +72 points.
"""
from __future__ import annotations

import argparse
import math
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _worker(args):
    seed0, count, a, b, field, extra = args
    from mahjong_mc.mc import load_policy_dir, load_policy_file, run_game
    load_policy_dir(os.path.join(ROOT, "my_strategies"))
    for path in extra:
        load_policy_file(path)
    deltas, ranks_a, ranks_b, wins_a, wins_b, dealt_a, dealt_b = \
        [], [], [], 0, 0, 0, 0
    for k in range(count):
        seed = seed0 + k
        # Rotate the seats. Fixed seats 0/1 gave seat 0 a free +72 points and
        # 0.14 places (v_base vs v_base "won" +72 ±105), which is larger than
        # most real effects and would have masked them.
        seat_a = seed % 4
        seat_b = (seat_a + 1) % 4
        dealer = (seed // 4) % 4          # independent of where A sits
        names = [None] * 4
        names[seat_a] = a
        names[seat_b] = b
        rest = iter(field)
        for s in range(4):
            if names[s] is None:
                names[s] = next(rest)
        res = run_game(names, seed, dealer=dealer)
        pts = res["points"]
        deltas.append(pts[seat_a] - pts[seat_b])
        ranks_a.append(1 + sum(1 for q in pts if q > pts[seat_a]))
        ranks_b.append(1 + sum(1 for q in pts if q > pts[seat_b]))
        if res["winner"] == seat_a:
            wins_a += 1
        elif res["winner"] == seat_b:
            wins_b += 1
        dealt_a += res["deal_ins"][seat_a] if "deal_ins" in res else 0
        dealt_b += res["deal_ins"][seat_b] if "deal_ins" in res else 0
    return (deltas, ranks_a, ranks_b, wins_a, wins_b,
            dealt_a, dealt_b)


def summary(deltas, label_a, label_b):
    n = len(deltas)
    mean = statistics.fmean(deltas)
    sd = statistics.stdev(deltas) if n > 1 else 0.0
    se = sd / math.sqrt(n)
    return n, mean, sd, se


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="louis")
    ap.add_argument("--b", default="gto")
    ap.add_argument("--field", default="defensive,greedy")
    ap.add_argument("--games", type=int, default=0)
    ap.add_argument("--pilot", type=int, default=2000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--policy-file", action="append", default=None,
                    help="extra policy .py file to register (repeatable)")
    ap.add_argument("--target-se", type=float, default=25.0,
                    help="wanted standard error on the paired difference")
    args = ap.parse_args()

    field = tuple(args.field.split(","))
    games = args.games or args.pilot
    chunk = 200
    extra = tuple(args.policy_file or ())
    tasks = [(args.seed + i * chunk, min(chunk, games - i * chunk),
              args.a, args.b, field, extra)
             for i in range(0, math.ceil(games / chunk))]

    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        out = list(ex.map(_worker, tasks))
    deltas = [d for r in out for d in r[0]]
    ranks_a = [d for r in out for d in r[1]]
    ranks_b = [d for r in out for d in r[2]]
    wins_a = sum(r[3] for r in out)
    wins_b = sum(r[4] for r in out)

    n, mean, sd, se = summary(deltas, args.a, args.b)
    ci = 1.96 * se
    print(f"{args.a} (seat 0) vs {args.b} (seat 1), field {'/'.join(field)}")
    print(f"games {n}  ·  mean paired score diff {mean:+.1f}  ±{ci:.1f} (95% CI)"
          f"  ·  sd {sd:.0f}  ·  SE {se:.1f}")
    fourth_a = 100 * sum(1 for r in ranks_a if r == 4) / n
    fourth_b = 100 * sum(1 for r in ranks_b if r == 4) / n
    print(f"win% {100*wins_a/n:.1f} vs {100*wins_b/n:.1f}"
          f"  ·  avg rank {statistics.fmean(ranks_a):.3f} vs "
          f"{statistics.fmean(ranks_b):.3f}"
          f"  ·  4th {fourth_a:.1f}% vs {fourth_b:.1f}%")
    verdict = ("A is better" if mean - ci > 0 else
               "B is better" if mean + ci < 0 else "no difference proven")
    print(f"verdict: {verdict}")

    if args.games == 0:
        need = math.ceil((1.96 * sd / args.target_se) ** 2)
        print(f"\npilot only. for SE {args.target_se:.0f} you need "
              f"~{need} games (sd {sd:.0f}); that is the paired-test sample size.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
