"""Parameterized strategy family used by the evolution search (examples/evolve.py).

One strategy, five knobs. The evolution finds the best setting of the knobs
by playing variants against a fixed reference field; the winner is written
out as a concrete policy (my_strategies/gto.py).

Knobs:
    safety_weight    float 0-4    discard: ukeire minus this * danger
    riichi_mode      int 0-3      0 never / 1 always / 2 never vs a riichi /
                                  3 damaten when waits are few
    call_mode        int 0-2      0 never / 1 shanten-improving / 2 also
                                  shanten-equal with more ukeire
    kan_mode         int 0-2      0 never / 1 honor or far from win / 2 any
    honor_pair_keep  bool         keep wind/dragon pairs (yakuhai potential)
"""

from __future__ import annotations

import random

from mahjong_mc.rules import shanten, ukeire

DEFAULT_PARAMS = {
    "safety_weight": 1.0,
    "riichi_mode": 1,
    "call_mode": 1,
    "kan_mode": 1,
    "honor_pair_keep": True,
}


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


class EvoStrategy:
    name = "evo"

    def __init__(self, params=None, seed=None):
        p = dict(DEFAULT_PARAMS)
        if params:
            p.update(params)
        self.params = p
        self.rng = random.Random(seed)

    # ---------------------------------------------------------- discard

    def choose_discard(self, view):
        p = self.params
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
            score = copies - p["safety_weight"] * _danger(view, t)
            if p["honor_pair_keep"] and t >= 27 and total[t] >= 2:
                score -= 2  # a wind/dragon pair has yakuhai potential
            key = (-score, self.rng.random())
            if best_key is None or key < best_key:
                best_key, best_tile = key, t
        return best_tile

    # ------------------------------------------------------------ call

    def _call_value(self, view, tile, act):
        """(shanten_after, ukeire_after) of taking this call."""
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
        u1 = None
        for x, n in held.items():
            if n <= 0:
                continue
            c[x] -= 1
            s = shanten(c)
            if s1 is None or s < s1:
                s1 = s
                unseen = view.unseen_counts()
                avail = list(unseen)
                avail[tile] = max(0, avail[tile] - 1)
                _, u1 = ukeire(c, avail)
            c[x] += 1
        return s1, u1

    def decide_call(self, view, tile, options):
        mode = self.params["call_mode"]
        if mode == 0 or not options:
            return None
        s0 = shanten(view.total_counts)
        best, best_key = None, None
        for act in options:
            s1, u1 = self._call_value(view, tile, act)
            if s1 is None:
                continue
            if mode == 1:
                ok = s1 < s0
            else:  # mode 2: also take shanten-equal calls that raise ukeire
                ok = s1 < s0 or (s1 == s0 and (u1 or 0) > 0)
            if ok:
                key = (s1, -(u1 or 0))
                if best_key is None or key < best_key:
                    best_key, best = key, act
        return best

    # ---------------------------------------------------------- riichi

    def decide_riichi(self, view):
        if not view.can_riichi:
            return False
        mode = self.params["riichi_mode"]
        if mode == 0:
            return False
        if mode == 2 and any(view.riichi[s] for s in range(4)
                             if s != view.seat):
            return False  # an opponent already riichi'd: damaten is safer
        if mode == 3:
            # damaten when the winning tiles are few
            types, _ = ukeire(view.total_counts, view.unseen_counts())
            if len(types) < 4:
                return False
        return True

    # ------------------------------------------------------------- kan

    def decide_kan(self, view, tile, options):
        mode = self.params["kan_mode"]
        if mode == 0 or not options:
            return None
        if mode == 1 and not (tile >= 27 or shanten(view.total_counts) >= 2):
            return None
        return options[0]
