"""Mahjong Monte Carlo — simulate millions of four-player games to test strategies.

Japanese standard rules (riichi): riichi/ippatsu, dora/ura/kan-dora, all
three kans, chankan, rinshan, haitei/houtei, han/fu scoring, noten-bappu.

Core idea: instead of playing round by round yourself, plug in a strategy
(a `Policy` object) and let the engine play it against baselines millions of
times, then read off win rates, deal-in rates and scores.
"""

from .engine import Game, Rules, View
from .mc import load_policy_dir, load_policy_file, main, print_table, run_batch, run_game
from .play import HumanPolicy, play_game
from .scoring import score_hand
from . import policies

__version__ = "0.2.0"

__all__ = [
    "Game",
    "Rules",
    "View",
    "policies",
    "run_batch",
    "run_game",
    "print_table",
    "main",
    "HumanPolicy",
    "play_game",
    "score_hand",
    "load_policy_file",
    "load_policy_dir",
]
