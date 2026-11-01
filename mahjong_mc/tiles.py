"""Tile encoding and basic helpers.

Tiles are encoded as ints 0..33:

    0-8    man (万) 1-9
    9-17   pin (筒) 1-9
    18-26  sou (索) 1-9
    27-33  honors (字牌): 东南西北白发中

A hand is a 34-length list of counts; index = tile type, value = copies held.
"""

from __future__ import annotations

import random

NUM_TILE_TYPES = 34
COPIES_PER_TYPE = 4
TILES_PER_SUIT = 9
NUM_HONORS = 7
SUIT_CHARS = ("m", "p", "s")
HONOR_NAMES = "东南西北白发中"


def is_suited(t: int) -> bool:
    return 0 <= t < 27


def suit(t: int) -> int:
    return t // 9


def number(t: int) -> int:
    return t % 9 + 1


def tile_name(t: int) -> str:
    if t < 27:
        return f"{number(t)}{SUIT_CHARS[suit(t)]}"
    return HONOR_NAMES[t - 27]


def new_counts() -> list[int]:
    return [0] * NUM_TILE_TYPES


def tiles_from_counts(counts) -> list[int]:
    """Expand a count vector into a sorted list of tile ids (one per copy)."""
    out: list[int] = []
    for t, c in enumerate(counts):
        if c:
            out.extend([t] * c)
    return out


def shuffled_wall(rng: random.Random) -> list[int]:
    """A shuffled 136-tile wall."""
    wall: list[int] = []
    for t in range(NUM_TILE_TYPES):
        wall.extend([t] * COPIES_PER_TYPE)
    rng.shuffle(wall)
    return wall
