"""A tunable safety-vs-efficiency strategy.

Discard choice = shanten first, then ukeire minus SAFETY_WEIGHT * danger,
where danger is 2 if an opponent wants the tile (it is in their melds),
1 if unseen, 0 if an opponent already discarded it (genbutsu).

SAFETY_WEIGHT = 0   -> pure greedy (same as the `greedy` baseline)
SAFETY_WEIGHT = 1+  -> folds earlier, feeds less

Sweep it without touching code:

    for w in 0 1 2 4; do
      MJ_SAFETY=$w python3 -m mahjong_mc --games 20000 \
          --policies safety,greedy,random,random --workers 8 --seed 7
    done

Everything else (riichi / call / kan rules) is inherited from a simple
greedy base so the only thing changing between runs is the safety weight.
"""

from __future__ import annotations

import os

from mahjong_mc.policies import Policy, register
from mahjong_mc.rules import shanten, ukeire

SAFETY_WEIGHT = float(os.environ.get("MJ_SAFETY", "1.0"))


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
            return 0  # genbutsu
    return danger or 1


@register
class SafetyPolicy(Policy):
    name = "safety"

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
            score = copies - SAFETY_WEIGHT * _danger(view, t)
            key = (-score, self.rng.random())
            if best_key is None or key < best_key:
                best_key, best_tile = key, t
        return best_tile

    def decide_call(self, view, tile, options):
        # call when it strictly lowers shanten
        total = view.total_counts
        s0 = shanten(total)
        best, best_s = None, s0
        for act in options:
            kind, trio = act[0], act[1]
            if kind == "shouminkan":
                consumed = []
            else:
                consumed = list(trio)
                consumed.remove(tile)
            held = {}
            for x in view.hand:
                held[x] = held.get(x, 0) + 1
            for x in consumed:
                held[x] -= 1
            c = list(total)
            c[tile] += 1
            s1 = None
            for x, n in held.items():
                if n <= 0:
                    continue
                c[x] -= 1
                s = shanten(c)
                c[x] += 1
                if s1 is None or s < s1:
                    s1 = s
            if s1 is not None and s1 < best_s:
                best_s, best = s1, act
        return best if best_s < s0 else None

    def decide_riichi(self, view):
        # damaten when the hand is already tenpai and safe enough
        return view.can_riichi

    def decide_kan(self, view, tile, options):
        if tile >= 27 or shanten(view.total_counts) >= 2:
            return options[0]
        return None
