"""Policy registry and baseline strategies (Japanese rules).

A policy is any object with:

    choose_discard(view) -> tile id             (must be in view.hand)
    decide_call(view, tile, options) -> option or None
        options: list of (kind, trio, meld_kind),
        kind in {"peng", "chi", "minkan", "shouminkan"}
    decide_riichi(view) -> bool                 (view.can_riichi must be True)
    decide_kan(view, tile, options) -> option or None
        options: [("ankan", ...), ("shouminkan", ...)] from your own draw

Register your own with @register to make it available to the CLI, or drop
a .py file into my_strategies/ and pass --policy-dir (auto-loaded).
"""

from __future__ import annotations

import random

from .rules import shanten, ukeire

_REGISTRY: dict[str, type] = {}


def register(cls):
    _REGISTRY[cls.name] = cls
    return cls


def available() -> list[str]:
    return sorted(_REGISTRY)


def make_policy(name: str, seed=None):
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown policy {name!r}; available: {', '.join(available())}"
        )
    return _REGISTRY[name](seed=seed)


class Policy:
    """Base class. Subclass and implement choose_discard."""

    name = "base"

    def __init__(self, seed=None):
        self.rng = random.Random(seed)

    def set_rng(self, rng: random.Random) -> None:
        self.rng = rng

    def choose_discard(self, view):
        raise NotImplementedError

    def decide_call(self, view, tile, options):
        return None

    def decide_riichi(self, view):
        return False

    def decide_kan(self, view, tile, options):
        return None


@register
class RandomPolicy(Policy):
    """Baseline: discard randomly, take calls half the time."""

    name = "random"

    def choose_discard(self, view):
        return self.rng.choice(view.hand)

    def decide_call(self, view, tile, options):
        if options and self.rng.random() < 0.5:
            return options[0]
        return None

    def decide_kan(self, view, tile, options):
        return options[0] if options and self.rng.random() < 0.5 else None


@register
class ShantenPolicy(Policy):
    """Greedy: discard the tile minimising shanten, then maximising ukeire.

    Declares riichi whenever it is available; calls and kans only when they
    strictly lower the shanten (kans also taken for honor tiles).
    """

    name = "greedy"

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
            avail[t] = max(0, avail[t] - 1)  # the discarded copy becomes visible
            _, copies = ukeire(c, avail)
            key = (-copies, self.rng.random())
            if best_key is None or key < best_key:
                best_key, best_tile = key, t
        return best_tile

    def decide_call(self, view, tile, options):
        total = view.total_counts
        s0 = shanten(total)
        best, best_s = None, s0
        for act in options:
            kind, trio = act[0], act[1]
            if kind == "shouminkan":
                consumed = []  # the 4th copy joins the existing peng meld
            else:
                consumed = list(trio)
                consumed.remove(tile)  # the discarded tile was not in hand
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
        total = view.total_counts
        s0 = shanten(total)
        # a kan trades 3-4 known tiles for a random replacement; take it
        # when it is an honor (dora value) or the hand is not close
        if tile >= 27 or s0 >= 2:
            return options[0]
        return None


@register
class DefensivePolicy(ShantenPolicy):
    """Greedy shanten + simple safety: avoid feeding tiles opponents want."""

    name = "defensive"

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
            key = (-copies, self._danger(view, t), self.rng.random())
            if best_key is None or key < best_key:
                best_key, best_tile = key, t
        return best_tile

    @staticmethod
    def _danger(view, t):
        """0 = safe (opponent already discarded it), 1 = unseen, 2+ = wanted."""
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
