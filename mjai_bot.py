#!/usr/bin/env python3
"""mjai bot entry point — run any mahjong-mc policy as a Tenhou/mjai bot.

    python3 mjai_bot.py <player_id> [policy_name] [policy_file]

Reads mjai JSONL events from stdin, writes actions to stdout. Strategies in
my_strategies/ are auto-loaded (same as the Monte Carlo CLI), and an extra
--policy-file-style path can be passed as the 3rd argument.

    python3 mjai_bot.py 0 gto
    python3 mjai_bot.py 1 mine my_strategies/mine.py

Available policy names: whatever `python3 -m mahjong_mc --policies ...`
accepts (random, greedy, defensive, mine, safety, gto, ...).
"""

import os
import sys

from mahjong_mc.mc import load_policy_dir, load_policy_file
from mahjong_mc.mjai import run_bot

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def _load_user_policies():
    default_dir = os.path.join(_PROJECT_ROOT, "my_strategies")
    if os.path.isdir(default_dir):
        loaded = load_policy_dir(default_dir)
        if loaded:
            print(f"loaded policies: {', '.join(sorted(set(loaded)))}",
                  file=sys.stderr)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    player_id = int(argv[0]) if len(argv) > 0 else 0
    policy_name = argv[1] if len(argv) > 1 else "gto"
    if len(argv) > 2:
        load_policy_file(argv[2])
    else:
        _load_user_policies()
    run_bot(policy_name=policy_name, player_id=player_id)


if __name__ == "__main__":
    main()
