"""Starter strategy — copy this file, rename the class/name, edit, run.

    python3 -m mahjong_mc --games 50000 --policies mine,greedy,random,random

This starter is greedy shanten + ukeire (same as `greedy`), but the
tie-break prefers dumping honors and terminal tiles (1/9) early — a classic
real-world heuristic. Change `_tile_value` or the whole `choose_discard` to
test your own ideas.
"""

from __future__ import annotations

from mahjong_mc.policies import Policy, register
from mahjong_mc.rules import shanten, ukeire

# tiles we are happy to throw away early, all else equal
_EARLY_DISCARD = set(range(27, 34)) | {0, 8, 9, 17, 18, 26}


@register
class MinePolicy(Policy):
    name = "mine"

    def choose_discard(self, view):
        total = view.total_counts
        unseen = view.unseen_counts()
        # phase 1: shanten after each candidate discard
        scored = []
        best_s = 8
        for t in sorted(set(view.hand)):
            c = list(total)
            c[t] -= 1
            s = shanten(c)
            scored.append((s, t, c))
            if s < best_s:
                best_s = s
        # phase 2: among shanten-tied candidates, maximise ukeire, then
        # prefer discarding honors / terminals
        best_key = None
        best_tile = None
        for s, t, c in scored:
            if s != best_s:
                continue
            avail = list(unseen)
            avail[t] = max(0, avail[t] - 1)
            _, copies = ukeire(c, avail)
            early = 0 if t in _EARLY_DISCARD else 1
            key = (-copies, early, self.rng.random())
            if best_key is None or key < best_key:
                best_key, best_tile = key, t
        return best_tile

    def decide_call(self, view, tile, options):
        # call when it strictly lowers shanten (same rule as `greedy`)
        total = view.total_counts
        s0 = shanten(total)
        best, best_s = None, s0
        for act in options:
            kind, trio = act[0], act[1]
            if kind == "shouminkan":
                consumed = []  # the 4th copy joins the existing peng meld
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
        return view.can_riichi

    def decide_kan(self, view, tile, options):
        # take the kan for honor tiles or when not close to winning
        if tile >= 27 or shanten(view.total_counts) >= 2:
            return options[0]
        return None
