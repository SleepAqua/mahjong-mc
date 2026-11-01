"""Tests for Japanese-standard scoring (yaku / han / fu / points)."""

import unittest

from mahjong_mc.scoring import (
    count_dora,
    dora_next,
    score_hand,
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


class TestDora(unittest.TestCase):
    def test_dora_next(self):
        self.assertEqual(dora_next(0), 1)    # 1m -> 2m
        self.assertEqual(dora_next(8), 0)    # 9m -> 1m (wraps in suit)
        self.assertEqual(dora_next(26), 18)  # 9s -> 1s (wraps in suit)
        self.assertEqual(dora_next(30), 27)  # 北 -> 东
        self.assertEqual(dora_next(33), 31)  # 中 -> 白

    def test_count_dora(self):
        c = counts_from_tiles([m(2), m(2), m(5)])
        # indicator 1m -> dora 2m: two copies held
        self.assertEqual(count_dora(c, [], [m(1)]), 2)
        # indicator 4m -> dora 5m: one copy held
        self.assertEqual(count_dora(c, [], [m(4)]), 1)


class TestScoreHand(unittest.TestCase):
    """counts always include the winning tile (14 tiles)."""

    def test_chiitoitsu(self):
        # 1m 9m 2p 8p 3s 7s 白  (seven pairs)
        tiles_ = ([m(1)] * 2 + [m(9)] * 2 + [p(2)] * 2 + [p(8)] * 2
                  + [s(3)] * 2 + [s(7)] * 2 + [31] * 2)
        self.assertEqual(len(tiles_), 14)
        c = counts_from_tiles(tiles_)
        sc = score_hand(c, [], 31, tsumo=False, dealer=0, seat=1)
        self.assertIsNotNone(sc)
        self.assertEqual(sc["han"], 2)
        self.assertEqual(sc["fu"], 25)
        self.assertEqual(sc["ron_ko"], 1600)   # 25 * 2^4 = 400 x4
        self.assertEqual(sc["ron_oya"], 2400)
        self.assertEqual(sc["tsumo_ko"], 400)  # ko pays 1x base
        self.assertEqual(sc["tsumo_oya"], 800)  # oya pays 2x base

    def test_tanyao_riichi_ron(self):
        # 234m 456m 234p 456p + pair 66s (win tile is one 6s), riichi ron
        tiles_ = ([m(2), m(3), m(4), m(4), m(5), m(6)]
                  + [p(2), p(3), p(4), p(4), p(5), p(6)]
                  + [s(6), s(6)])
        self.assertEqual(len(tiles_), 14)
        c = counts_from_tiles(tiles_)
        sc = score_hand(c, [], s(6), tsumo=False, dealer=0, seat=1,
                        riichi=True)
        self.assertIsNotNone(sc)
        self.assertEqual(sc["han"], 2)   # tanyao + riichi
        # 20 + menzen ron 10 + tanki 2 = 32 -> rounds up to 40
        self.assertEqual(sc["fu"], 40)
        self.assertEqual(sc["ron_ko"], 2600)  # 40*2^4=640 x4=2560 -> 2600

    def test_one_han_thirty_fu(self):
        # same hand without riichi: tanyao only, 1 han 40 fu
        tiles_ = ([m(2), m(3), m(4), m(4), m(5), m(6)]
                  + [p(2), p(3), p(4), p(4), p(5), p(6)]
                  + [s(6), s(6)])
        c = counts_from_tiles(tiles_)
        sc = score_hand(c, [], s(6), tsumo=False, dealer=0, seat=1)
        self.assertIsNotNone(sc)
        self.assertEqual(sc["han"], 1)
        self.assertEqual(sc["ron_ko"], 1300)  # 40*2^3=320 x4=1280 -> 1300

    def test_chinitsu(self):
        # 123456789m + 111m + 11m (win on 1m): all man
        tiles_ = [m(i) for i in range(1, 10)] + [m(1)] * 3 + [m(1)] * 2
        self.assertEqual(len(tiles_), 14)
        c = counts_from_tiles(tiles_)
        sc = score_hand(c, [], m(1), tsumo=True, dealer=0, seat=0)
        self.assertIsNotNone(sc)
        self.assertIn("chinitsu", sc["yaku"])
        self.assertGreaterEqual(sc["han"], 5)  # 6 menzen

    def test_yakuman_chiiniisou(self):
        # 东东东 南南南 西西西 北北北 中中: 字一色 + 四暗刻 = double yakuman
        tiles_ = [27] * 3 + [28] * 3 + [29] * 3 + [30] * 3 + [33] * 2
        self.assertEqual(len(tiles_), 14)
        c = counts_from_tiles(tiles_)
        sc = score_hand(c, [], 33, tsumo=False, dealer=0, seat=1)
        self.assertIsNotNone(sc)
        self.assertEqual(sc["yakuman"], 2)
        self.assertEqual(sc["ron_ko"], 64000)
        self.assertEqual(sc["ron_oya"], 96000)

    def test_mangan_with_dora(self):
        # 234m 456m 234p 222s 55s (win on 2s): tanyao + riichi + menzen
        # tsumo + 2 dora = 5 han -> mangan
        tiles_ = ([m(2), m(3), m(4), m(4), m(5), m(6)]
                  + [p(2), p(3), p(4)]
                  + [s(2), s(2), s(2), s(5), s(5)])
        self.assertEqual(len(tiles_), 14)
        c = counts_from_tiles(tiles_)
        sc = score_hand(c, [], s(2), tsumo=True, dealer=0, seat=1,
                        riichi=True, dora=2)
        self.assertIsNotNone(sc)
        self.assertEqual(sc["han"], 5)
        self.assertEqual(sc["limit"], "mangan")
        self.assertEqual(sc["ron_ko"], 8000)

    def test_dealer_tsumo_split(self):
        # oya tsumo mangan: each ko pays 4000
        tiles_ = ([m(2), m(3), m(4), m(4), m(5), m(6)]
                  + [p(2), p(3), p(4)]
                  + [s(2), s(2), s(2), s(5), s(5)])
        c = counts_from_tiles(tiles_)
        sc = score_hand(c, [], s(2), tsumo=True, dealer=0, seat=0,
                        riichi=True, dora=2)
        self.assertEqual(sc["limit"], "mangan")
        self.assertEqual(sc["tsumo_oya"], 4000)  # oya tsumo: 4000 each

    def test_no_yaku_is_not_a_win(self):
        # 123m 456m 789p 789s + pair 11m (win on 1m): no yaku
        # (1m is terminal: no tanyao; runs all distinct: no iipeikou)
        tiles_ = ([m(1), m(2), m(3), m(4), m(5), m(6)]
                  + [p(7), p(8), p(9)]
                  + [s(7), s(8), s(9)]
                  + [m(1), m(1)])
        self.assertEqual(len(tiles_), 14)
        c = counts_from_tiles(tiles_)
        sc = score_hand(c, [], m(1), tsumo=False, dealer=0, seat=1)
        self.assertIsNone(sc)

    def test_kan_fu(self):
        # 234m 678m 234p 55s + ankan 5555m (win on 5s): tanyao + ankan fu
        tiles_ = ([m(2), m(3), m(4), m(6), m(7), m(8)]
                  + [p(2), p(3), p(4)]
                  + [s(5), s(5)])
        self.assertEqual(len(tiles_), 11)
        c = counts_from_tiles(tiles_)
        melds = [((m(5),) * 4, "ankan")]
        sc = score_hand(c, melds, s(5), tsumo=False, dealer=0, seat=1)
        self.assertIsNotNone(sc)
        self.assertIn("tanyao", sc["yaku"])
        # 20 + menzen ron 10 + ankan 16 = 46 -> 50
        self.assertEqual(sc["fu"], 50)

    def test_seven_pairs_not_chosen_when_better_exists(self):
        # a normal hand that happens to have 7 pairs is scored as pairs
        # only when that is the best option (chiitoitsu 2 han vs e.g. 3)
        tiles_ = ([m(1)] * 2 + [m(2)] * 2 + [m(3)] * 2 + [p(4)] * 2
                  + [p(5)] * 2 + [s(6)] * 2 + [s(7)] * 2)
        c = counts_from_tiles(tiles_)
        sc = score_hand(c, [], s(7), tsumo=False, dealer=0, seat=1)
        self.assertIsNotNone(sc)
        self.assertEqual(sc["han"], 2)  # chiitoitsu only (no tanyao: 1m terminal)


if __name__ == "__main__":
    unittest.main()
