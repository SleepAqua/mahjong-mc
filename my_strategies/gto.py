"""GTO-ish strategy — evolved by examples/evolve.py.

Evolved parameters (fitness 939 pts/game vs the reference field):

    safety_weight    = 2.94
    riichi_mode      = 2   # 0 never / 1 always / 2 never vs riichi /
                                 # 3 damaten when waits are few
    call_mode        = 0     # 0 never / 1 shanten-improving /
                                 # 2 also shanten-equal with more ukeire
    kan_mode         = 1      # 0 never / 1 honor or far / 2 any
    honor_pair_keep  = True  # keep wind/dragon pairs

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
            score = copies - 2.94 * _danger(view, t)
            if True and t >= 27 and total[t] >= 2:
                score -= 2
            key = (-score, self.rng.random())
            if best_key is None or key < best_key:
                best_key, best_tile = key, t
        return best_tile

    def decide_call(self, view, tile, options):
        mode = 0
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
            held = {}
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
        mode = 2
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
        mode = 1
        if mode == 0 or not options:
            return None
        if mode == 1 and not (tile >= 27 or shanten(view.total_counts) >= 2):
            return None
        return options[0]
