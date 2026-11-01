"""Thirteen orphans (kokushi musou) support in rules and scoring."""

import unittest

from mahjong_mc.rules import is_kokushi, is_win, kokushi_shanten, shanten
from mahjong_mc.scoring import score_hand


class TestKokushi(unittest.TestCase):
    """All 13 terminal/honour types + one duplicate is a yakuman."""

    @staticmethod
    def counts(tiles):
        c = [0] * 34
        for t in tiles:
            c[t] += 1
        return c

    YAO13 = [0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33]

    def test_complete_hand_is_win(self):
        c = self.counts(self.YAO13 + [0])
        self.assertTrue(is_kokushi(c))
        self.assertTrue(is_win(c))
        self.assertEqual(shanten(c), -1)
        self.assertEqual(kokushi_shanten(c), -1)

    def test_tenpai(self):
        c = self.counts(self.YAO13)
        self.assertFalse(is_kokushi(c))
        self.assertEqual(kokushi_shanten(c), 0)
        self.assertEqual(shanten(c), 0)

    def test_twelve_kinds_and_a_pair_is_tenpai(self):
        # waiting on the one missing type completes the hand
        c = self.counts(self.YAO13[:-1] + [self.YAO13[0]])
        self.assertEqual(kokushi_shanten(c), 0)

    def test_ten_kinds_is_two_away(self):
        c = self.counts([0, 8, 9, 17, 18, 26, 27, 28, 29, 30] + [0, 8, 9])
        self.assertEqual(kokushi_shanten(c), 2)

    def test_triplet_kills_it(self):
        # a triplet means the hand can never be kokushi
        c = self.counts([0, 0, 0] + self.YAO13[1:12])
        self.assertEqual(kokushi_shanten(c), 13)

    def test_not_a_kokushi_win_with_extra_suit_tile(self):
        c = self.counts(self.YAO13 + [4])       # 5m instead of a duplicate
        self.assertFalse(is_kokushi(c))
        self.assertFalse(is_win(c))

    def test_scoring_is_yakuman(self):
        c = self.counts(self.YAO13 + [0])
        res = score_hand(c, [], 0, tsumo=False, dealer=0, seat=1)
        self.assertIsNotNone(res)
        self.assertEqual(res["yakuman"], 1)
        self.assertEqual(res["yaku"], ["kokushi musou"])
        self.assertEqual(res["ron_ko"], 32000)

    def test_dealer_kokushi_pays_more(self):
        c = self.counts(self.YAO13 + [27])
        res = score_hand(c, [], 27, tsumo=True, dealer=0, seat=0)
        self.assertEqual(res["yakuman"], 1)
        self.assertEqual(res["tsumo_oya"], 16000)


if __name__ == "__main__":
    unittest.main()
