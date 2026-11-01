"""Tests for policies and the Monte Carlo runner."""

import os
import unittest

from mahjong_mc.mc import load_policy_file, run_batch, run_game
from mahjong_mc.policies import available, make_policy

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MY_POLICY = os.path.join(_PROJECT_ROOT, "my_strategies", "mine.py")


class TestPolicies(unittest.TestCase):
    def test_registry(self):
        self.assertIn("random", available())
        self.assertIn("greedy", available())
        pol = make_policy("greedy", seed=1)
        self.assertIsNotNone(pol)

    def test_unknown_policy(self):
        with self.assertRaises(KeyError):
            make_policy("does-not-exist")

    def test_greedy_beats_random_over_many_games(self):
        stats = run_batch(400, ["greedy", "random", "random", "random"],
                          seed=5, workers=1)
        rows = stats["rows"]
        greedy = rows[0]
        randoms = rows[1:]
        # greedy should win more than each random seat on average
        avg_random_wr = sum(r["win_rate"] for r in randoms) / 3
        self.assertGreater(greedy["win_rate"], avg_random_wr)
        # every seat played all games
        for r in rows:
            self.assertEqual(r["games"], 400)
        # rates are in range
        for r in rows:
            self.assertGreaterEqual(r["win_rate"], 0.0)
            self.assertLessEqual(r["win_rate"], 1.0)
            self.assertGreaterEqual(r["avg_rank"], 1.0)
            self.assertLessEqual(r["avg_rank"], 4.0)

    def test_single_game_result_shape(self):
        res = run_game(["greedy"] * 4, seed=1)
        self.assertIn("winner", res)
        self.assertIn("kind", res)
        self.assertIn("points", res)
        self.assertEqual(len(res["points"]), 4)
        # zero-sum except for riichi sticks left on the table at a draw
        self.assertEqual(sum(res["points"]),
                         -1000 * res.get("riichi_sticks", 0))

    def test_parallel_matches_serial(self):
        names = ["greedy", "random", "random", "random"]
        a = run_batch(64, names, seed=3, workers=1)
        b = run_batch(64, names, seed=3, workers=4)
        for ra, rb in zip(a["rows"], b["rows"]):
            self.assertEqual(ra["wins"], rb["wins"])
            self.assertEqual(ra["tumo"], rb["tumo"])
            self.assertEqual(ra["ron"], rb["ron"])


class TestCustomPolicyFile(unittest.TestCase):
    def tearDown(self):
        # keep the shared registry clean between tests
        from mahjong_mc.policies import _REGISTRY
        _REGISTRY.pop("mine", None)

    def test_load_policy_file(self):
        loaded = load_policy_file(MY_POLICY)
        self.assertIn("mine", loaded)
        self.assertIn("mine", available())

    def test_run_with_custom_policy(self):
        stats = run_batch(40, ["mine", "greedy", "random", "random"],
                          seed=2, workers=2, policy_file=MY_POLICY)
        for r in stats["rows"]:
            self.assertEqual(r["games"], 40)

    def test_parallel_with_custom_policy_matches_serial(self):
        names = ["mine", "greedy", "random", "random"]
        a = run_batch(64, names, seed=11, workers=1, policy_file=MY_POLICY)
        b = run_batch(64, names, seed=11, workers=4, policy_file=MY_POLICY)
        for ra, rb in zip(a["rows"], b["rows"]):
            self.assertEqual(ra["wins"], rb["wins"])
            self.assertEqual(ra["ron"], rb["ron"])
            self.assertEqual(ra["dealt_in"], rb["dealt_in"])

    def test_missing_policy_file(self):
        with self.assertRaises((FileNotFoundError, ImportError)):
            load_policy_file(os.path.join(_PROJECT_ROOT, "no_such_file.py"))


if __name__ == "__main__":
    unittest.main()
