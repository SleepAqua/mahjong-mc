"""Tests for tile encoding and the rules engine (win/shanten/ukeire)."""

import unittest

from mahjong_mc.rules import is_win, shanten, ukeire
from mahjong_mc.tiles import (
    shuffled_wall,
    tile_name,
    tiles_from_counts,
)


def counts_from_tiles(tile_ids):
    from mahjong_mc.tiles import new_counts
    c = new_counts()
    for t in tile_ids:
        c[t] += 1
    return c


# tile id helpers: man=0-8, pin=9-17, sou=18-26, honors=27-33
def m(n):
    return n - 1


def p(n):
    return 8 + n


def s(n):
    return 17 + n


class TestTiles(unittest.TestCase):
    def test_names(self):
        self.assertEqual(tile_name(0), "1m")
        self.assertEqual(tile_name(8), "9m")
        self.assertEqual(tile_name(9), "1p")
        self.assertEqual(tile_name(26), "9s")
        self.assertEqual(tile_name(27), "东")

    def test_wall_size(self):
        import random
        wall = shuffled_wall(random.Random(1))
        self.assertEqual(len(wall), 136)
        self.assertEqual(sorted(wall), sorted(list(range(34)) * 4))

    def test_counts_roundtrip(self):
        c = counts_from_tiles([0, 0, 0, 9, 9])
        self.assertEqual(tiles_from_counts(c), [0, 0, 0, 9, 9])


class TestWin(unittest.TestCase):
    def test_pinfu_like(self):
        # 123m 456m 789m 123p + pair 11s
        tiles_ = [m(i) for i in (1, 2, 3, 4, 5, 6, 7, 8, 9, 1, 2, 3)] + \
                 [s(1), s(1)]
        self.assertEqual(len(tiles_), 14)
        self.assertTrue(is_win(counts_from_tiles(tiles_)))

    def test_triplets(self):
        hand = [m(1)] * 3 + [m(5)] * 3 + [p(1)] * 3 + [p(9)] * 3 + [s(5)] * 2
        self.assertEqual(len(hand), 14)
        self.assertTrue(is_win(counts_from_tiles(hand)))

    def test_seven_pairs(self):
        hand = [m(1)] * 2 + [m(9)] * 2 + [p(2)] * 2 + [p(8)] * 2 + \
               [s(3)] * 2 + [s(7)] * 2 + [27] * 2
        self.assertTrue(is_win(counts_from_tiles(hand)))

    def test_not_win(self):
        hand = [m(i) for i in (1, 2, 4, 5, 7, 8, 9)] + [p(1)] * 3 + \
               [p(5)] * 3 + [s(5)]
        self.assertFalse(is_win(counts_from_tiles(hand)))

    def test_win_with_melds(self):
        # concealed 123m 456m 789m + pair 11s (11 tiles), meld (peng 7p): 14
        concealed = [m(1), m(2), m(3), m(4), m(5), m(6), m(7), m(8), m(9),
                     s(1), s(1)]
        meld = (p(7), p(7), p(7))
        self.assertTrue(is_win(counts_from_tiles(concealed), melds=[meld]))
        # 9 concealed + 3-tile meld = 12 total -> not a valid 14
        bad = [m(1), m(2), m(3), m(4), m(5), m(6), m(7), m(8), m(9)]
        self.assertFalse(is_win(counts_from_tiles(bad), melds=[meld]))


class TestShanten(unittest.TestCase):
    def test_complete_is_minus_one(self):
        # 123m 456m 789m 123p + pair 11s (14 tiles, complete)
        hand = [m(i) for i in (1, 2, 3, 4, 5, 6, 7, 8, 9, 1, 2, 3)] + \
               [s(1), s(1)]
        self.assertEqual(len(hand), 14)
        self.assertEqual(shanten(counts_from_tiles(hand)), -1)

    def test_tenpai_is_zero(self):
        # 123m 456m 789m 11p 22p: 13 tiles, waiting on 2p
        hand = [m(i) for i in (1, 2, 3, 4, 5, 6, 7, 8, 9)] + [p(1), p(1), p(2), p(2)]
        self.assertEqual(len(hand), 13)
        self.assertEqual(shanten(counts_from_tiles(hand)), 0)

    def test_isolated_hand_is_kokushi_tenpai(self):
        # every terminal + honour, all distinct: thirteen orphans tenpai
        hand = [27, 28, 29, 30, 31, 32, 33, m(1), m(9), p(1), p(9), s(1), s(9)]
        self.assertEqual(shanten(counts_from_tiles(hand)), 0)

    def test_monotonic_draw_improves(self):
        # from a shanten-1 hand, a completing draw should lower shanten
        hand = [m(1), m(2), m(3), m(4), m(5), m(6), p(1), p(1), p(2), p(2),
                s(3), s(3), s(4)]
        self.assertEqual(len(hand), 13)
        self.assertEqual(shanten(counts_from_tiles(hand)), 1)
        hand2 = hand + [s(3)]  # makes 333s: 3 melds + 2 pairs -> 0 shanten
        self.assertEqual(shanten(counts_from_tiles(hand2)), 0)


class TestUkeire(unittest.TestCase):
    def test_ukeire_finds_winning_tile(self):
        hand = [m(i) for i in (1, 2, 3, 4, 5, 6, 7, 8, 9)] + [p(1), p(1), p(2)]
        self.assertEqual(len(hand), 12)
        c = counts_from_tiles(hand)
        remaining = [4] * 34
        for t, n in enumerate(c):
            remaining[t] -= n
        types, copies = ukeire(c, remaining)
        # drawing p2 completes the hand; drawing p1 also works (pair 11p stays)
        self.assertIn(p(2), types)
        self.assertGreater(copies, 0)


if __name__ == "__main__":
    unittest.main()
