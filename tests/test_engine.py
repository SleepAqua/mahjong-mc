"""Tests for the game engine: determinism, invariants, win handling."""

import unittest

from mahjong_mc.engine import Game, Rules
from mahjong_mc.policies import ShantenPolicy
from mahjong_mc.tiles import NUM_TILE_TYPES, tiles_from_counts


class DummyPolicy:
    """Discards the first tile in hand; never calls."""

    def __init__(self, seed=None):
        pass

    def choose_discard(self, view):
        return view.hand[0]

    def decide_call(self, view, tile, options):
        return None

    def decide_riichi(self, view):
        return False

    def decide_kan(self, view, tile, options):
        return None


def GreedyForTest(seed):
    return ShantenPolicy(seed=seed)


def all_counts(game):
    """Every tile must be accounted for: wall + hands + melds + discards."""
    total = len(game.live_wall) + len(game.dead_wall)
    for seat in range(4):
        total += sum(game.counts[seat])
        total += sum(len(ts) for ts, _ in game.melds[seat])
        total += len(game.discards[seat])
    return total


class TestEngine(unittest.TestCase):
    def test_game_completes_with_winner_or_draw(self):
        game = Game([DummyPolicy() for _ in range(4)], seed=42)
        game.run()
        self.assertIn(game.win_kind, ("tumo", "ron", "draw"))
        if game.winner is not None:
            self.assertIn(game.winner, range(4))

    def test_tile_conservation(self):
        for seed in range(20):
            game = Game([DummyPolicy() for _ in range(4)], seed=seed)
            game.run()
            self.assertEqual(all_counts(game), 136,
                             f"seed {seed} lost tiles")

    def test_determinism(self):
        g1 = Game([DummyPolicy() for _ in range(4)], seed=7)
        g1.run()
        g2 = Game([DummyPolicy() for _ in range(4)], seed=7)
        g2.run()
        self.assertEqual(g1.result(), g2.result())
        self.assertEqual(g1.discards, g2.discards)

    def test_ron_credits_discarder(self):
        # greedy policies produce rons; check the loser is the discarder
        found = False
        for seed in range(200):
            game = Game([GreedyForTest(seed) for _ in range(4)], seed=seed)
            game.run()
            if game.win_kind == "ron":
                self.assertIsNotNone(game.loser)
                self.assertNotEqual(game.winner, game.loser)
                found = True
                break
        if not found:
            self.skipTest("no ron occurred in 200 seeds")

    def test_calls_change_seat(self):
        # with a peng-happy policy, melds must appear and seat must skip
        class PengPolicy:
            def __init__(self):
                self.calls = 0

            def choose_discard(self, view):
                # dump honors first so suits concentrate
                hand = view.hand
                honors = [t for t in hand if t >= 27]
                return honors[0] if honors else hand[0]

            def decide_call(self, view, tile, options):
                for act in options:
                    if act[0] == "peng":
                        self.calls += 1
                        return act
                return None

            def decide_riichi(self, view):
                return False

            def decide_kan(self, view, tile, options):
                return None

        pols = [PengPolicy() for _ in range(4)]
        game = Game(pols, seed=99)
        game.run()
        total_melds = sum(len(ms) for ms in game.melds)
        self.assertEqual(total_melds, sum(p.calls for p in pols))
        # at least some calls happened across 4 greedy pengers in a full game
        self.assertGreater(total_melds, 0)

    def test_illegal_discard_raises(self):
        class BadPolicy:
            def choose_discard(self, view):
                return 33  # rarely in hand

            def decide_call(self, view, tile, options):
                return None

        game = Game([BadPolicy() for _ in range(4)], seed=3)
        with self.assertRaises(RuntimeError):
            game.run()

    def test_no_calls_rules(self):
        rules = Rules(allow_chi=False, allow_peng=False)
        game = Game([DummyPolicy() for _ in range(4)], rules=rules, seed=5)
        game.run()
        self.assertEqual(sum(len(ms) for ms in game.melds), 0)

    def test_view_contents(self):
        game = Game([DummyPolicy() for _ in range(4)], seed=11)
        view = game._view(0)
        self.assertEqual(len(view.hand), 14)  # dealer holds 14 pre-discard
        self.assertEqual(sum(view.counts), 14)
        self.assertEqual(len(view.total_counts), NUM_TILE_TYPES)


if __name__ == "__main__":
    unittest.main()
