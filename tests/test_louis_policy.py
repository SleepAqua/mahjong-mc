"""Rule-compliance tests for the `louis` policy (see docs/strategy.md).

These do not test strength — they pin the decisions Louis asked for, so a
future refactor cannot quietly turn his rules back into tie-breakers.
"""

import os
import unittest

from mahjong_mc.mc import load_policy_dir
from mahjong_mc.mjai import mjai_to_id
from mahjong_mc.scoring import dora_next
from mahjong_mc.policies import make_policy

load_policy_dir(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "my_strategies"))


def tiles(names):
    out = []
    for n in names:
        if n == "?":
            continue
        out.append(mjai_to_id(n))
    return out


class FakeView:
    """Minimal duck-typed View for policy tests."""

    def __init__(self, hand, seat=0, dealer=0, melds=(), discards=None,
                 riichi=None, dora=None, turn=0, wall_left=60,
                 can_riichi=False):
        self.seat = seat
        self.dealer = dealer
        self.turn = turn
        self.wall_left = wall_left
        self.can_riichi = can_riichi
        self.last_drawn = None
        self.points = (25000,) * 4
        self.melds = tuple(melds)
        self.discards = tuple(tuple(d) for d in (discards or [[], [], [], []]))
        self.melds_all = tuple(() for _ in range(4))
        self.riichi = tuple(riichi or [False] * 4)
        self.ippatsu = (False,) * 4
        self.honba = 0
        self.riichi_sticks = 0
        self.dora_indicators = tuple(tiles(dora or []))
        self._dora = [dora_next(i) for i in self.dora_indicators]
        self.counts = [0] * 34
        for t in hand:
            self.counts[t] += 1
        self.hand = tuple(sorted(hand))

    @property
    def dora_count(self):
        return sum(self.counts[t] for t in self._dora)

    @property
    def total_counts(self):
        c = list(self.counts)
        for ts, _ in self.melds:
            for t in ts:
                c[t] += 1
        return c

    def visible_counts(self):
        v = [0] * 34
        for d in self.discards:
            for t in d:
                v[t] += 1
        for ms in self.melds_all:
            for ts, _ in ms:
                for t in ts:
                    v[t] += 1
        return v

    def unseen_counts(self):
        v = self.visible_counts()
        return [4 - v[t] - self.counts[t] for t in range(34)]


def policy():
    return make_policy("louis", seed=1)


class TestLoneOrder(unittest.TestCase):
    """Rule 1: the lone-tile order decides, it is not a tie-break."""

    def test_real_game_hand_plays_the_isolated_1m(self):
        # the hand the online bot actually faced on 2026-10-31 (seat 0):
        # 1m 4m 6m 888m 3p 5p 88p 3s 6s C, drawing P
        hand = tiles(["1m", "4m", "6m", "8m", "8m", "8m", "3p", "5pr",
                      "8p", "8p", "3s", "6s", "C", "P"])
        v = FakeView(hand, turn=0)
        self.assertEqual(policy().choose_discard(v), mjai_to_id("1m"))

    def test_guest_wind_before_dragon(self):
        # E is the round wind, S the seat wind -> W and N are guest winds
        hand = tiles(["C", "2m", "3m", "4m", "5p", "6p", "7p", "2s", "3s",
                      "4s", "5s", "5s", "6s", "W"])
        v = FakeView(hand, seat=1, dealer=1, turn=0)
        self.assertEqual(policy().choose_discard(v), mjai_to_id("W"))

    def test_guest_wind_before_terminal(self):
        hand = tiles(["1m", "4m", "5m", "6m", "2p", "3p", "4p", "2s", "3s",
                      "4s", "6s", "6s", "7s", "N"])
        v = FakeView(hand, seat=0, dealer=0, turn=0)   # N is a guest wind
        self.assertEqual(policy().choose_discard(v), mjai_to_id("N"))

    def test_lone_terminal_before_lone_dragon(self):
        # rule 1 puts lone 1/9 above lone dragons: 1m goes, C stays
        hand = tiles(["1m", "C", "2p", "3p", "4p", "5p", "6p", "7p",
                      "2s", "3s", "4s", "5s", "6s", "7s"])
        v = FakeView(hand, turn=0)
        self.assertEqual(policy().choose_discard(v), mjai_to_id("1m"))


class TestRuleRefinements(unittest.TestCase):
    """The refinements from docs/strategy.md §11."""

    def test_round_wind_is_not_cut_before_a_terminal(self):
        # E is the round wind and yakuhai: 1m must go first now
        hand = tiles(["E", "1m", "2p", "3p", "4p", "5p", "6p", "7p",
                      "2s", "3s", "4s", "5s", "6s", "7s"])
        v = FakeView(hand, seat=1, dealer=2, turn=0)
        self.assertEqual(policy().choose_discard(v), mjai_to_id("1m"))

    def test_pair_scores_above_a_kanchan(self):
        from my_strategies.louis import _shape_score

        def counts(names):
            c = [0] * 34
            for n in tiles(names):
                c[n] += 1
            return c

        pair = counts(["1m", "1m", "1m", "2p", "3p", "4p", "2s", "3s", "4s",
                       "6s", "7s", "8s", "2p", "2p"])
        kanchan = counts(["1m", "1m", "1m", "2p", "3p", "4p", "2s", "3s",
                          "4s", "6s", "7s", "8s", "2p", "4p"])
        self.assertGreater(_shape_score(pair), _shape_score(kanchan))

    def test_two_shanten_folds_against_riichi(self):
        # standard ladder: tenpai pushes, 1-shanten fights one tile, 2+ folds
        hand = tiles(["1m", "4m", "7m", "2p", "5p", "8p", "3s", "5s", "9s",
                      "E", "S", "C", "P", "2m"])
        v = FakeView(hand, seat=0, turn=8,
                     discards=[tiles(["5m"]), tiles(["1p"]), [], []],
                     riichi=[False, True, False, False])
        self.assertTrue(policy()._should_fold(v, v.total_counts, [1], 2))

    def test_live_narrow_tenpai_still_pushes(self):
        # folding costs ~1500 points, so a live tanki is worth the risk
        hand = tiles(["1m", "2m", "3m", "4p", "5p", "6p", "7m", "8m", "9m",
                      "2s", "3s", "4s", "9s"])
        opp = tiles(["1m", "4p", "9s", "9s", "E"])
        v = FakeView(hand, seat=0, turn=8,
                     discards=[tiles(["5m"]), opp, [], []],
                     riichi=[False, True, False, False])
        pol = policy()
        self.assertFalse(pol._should_fold(v, v.total_counts, [1], 0))

    def test_valuable_tenpai_keeps_attacking(self):
        # tanyao + two dora + riichi is worth a push even on a narrow wait
        hand = tiles(["2m", "3m", "4m", "5p", "6p", "7p", "6s", "7s", "8s",
                      "2s", "3s", "4s", "5s"])
        v = FakeView(hand, seat=0, turn=8, dora=["4s"],        # dora 5s x2
                     discards=[tiles(["9m"]), tiles(["1m"]), [], []],
                     riichi=[False, True, False, False])
        pol = policy()
        self.assertFalse(pol._should_fold(v, v.total_counts, [1], 0))

    def test_pond_reading_raises_danger_on_a_cut_suit(self):
        from my_strategies.louis import LouisPolicy
        hand = tiles(["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "9s",
                      "3m", "3m", "6p", "6p"])
        quiet = FakeView(hand, seat=0, turn=9,
                         discards=[[], tiles(["E", "S", "W"]), [], []],
                         riichi=[False, True, False, False])
        busy = FakeView(hand, seat=0, turn=9,
                        discards=[[], tiles(["E", "S", "W", "1p", "2p",
                                             "3p", "4p", "5p"]), [], []],
                        riichi=[False, True, False, False])
        t = mjai_to_id("8p")
        self.assertLess(LouisPolicy._danger(busy, t, [1]),
                        LouisPolicy._danger(quiet, t, [1]))


class TestDora(unittest.TestCase):
    """Rule 3: dora is kept when another lone tile can go instead."""

    def test_dora_dragon_is_kept_behind_plain_terminal(self):
        # indicator 3s -> dora 4s; C is a plain lone dragon, 1m a lone terminal
        hand = tiles(["1m", "C", "2p", "3p", "4p", "6p", "7p", "8p", "2s",
                      "3s", "5s", "5s", "6s", "C"])
        v = FakeView(hand, turn=0, dora=["3s"])
        self.assertEqual(policy().choose_discard(v), mjai_to_id("1m"));

    def test_kept_dora_is_not_thrown_when_only_loners_are_dora(self):
        # both lone candidates are dora: still has to pick one, must be legal
        hand = tiles(["1m", "2m", "3m", "4m", "5m", "6m", "7p", "8p", "9p",
                      "2s", "3s", "4s", "5s", "1p"])
        v = FakeView(hand, turn=0, dora=["9m"])       # 1m is dora
        pick = policy().choose_discard(v)
        self.assertIn(pick, v.hand)


class TestFolding(unittest.TestCase):
    """Rule 6: an opponent riichi + we are not tenpai -> pure defence."""

    def test_only_genbutsu_is_discarded(self):
        opp_discards = tiles(["1m", "2m", "3m", "7p", "8p", "9p", "E", "E"])
        hand = tiles(["1m", "5p", "5p", "2s", "3s", "4s", "6s", "7s", "8s",
                      "9s", "9s", "C", "C", "5m"])
        v = FakeView(hand, seat=0, turn=6,
                     discards=[tiles(["9m"]), opp_discards, tiles(["4p"]),
                               tiles(["6p"])],
                     riichi=[False, True, False, False])
        pick = policy().choose_discard(v)
        self.assertIn(pick, opp_discards,
                      "in betaori the bot must only throw the riichi player's "
                      "own discards (genbutsu)")


class TestKokushi(unittest.TestCase):
    """Rule 8: 10+ distinct terminals/honours -> thirteen orphans."""

    def test_sheds_suit_tiles_for_kokushi(self):
        hand = tiles(["1m", "9m", "1p", "9p", "1s", "9s", "E", "S", "W", "N",
                      "C", "5m", "5p", "5s"])
        v = FakeView(hand, turn=0)
        pick = policy().choose_discard(v)
        self.assertIn(pick, tiles(["5m", "5p", "5s"]))


if __name__ == "__main__":
    unittest.main()
