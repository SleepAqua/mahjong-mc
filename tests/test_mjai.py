"""Tests for the mjai bot adapter."""

import json
import os
import subprocess
import sys
import unittest

from mahjong_mc.mc import load_policy_dir
from mahjong_mc.mjai import MjaiBot, id_to_mjai, mjai_to_id
from mahjong_mc.policies import make_policy

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_policy_dir(os.path.join(_PROJECT_ROOT, "my_strategies"))


def start_kyoku(tehais):
    return {
        "type": "start_kyoku", "bakaze": "E", "dora_marker": "5m",
        "kyoku": 1, "honba": 0, "kyotaku": 0, "oya": 0,
        "scores": [25000] * 4, "tehais": tehais,
    }


class TestTileConversion(unittest.TestCase):
    def test_roundtrip(self):
        for t in range(34):
            self.assertEqual(mjai_to_id(id_to_mjai(t)), t)

    def test_known_tiles(self):
        self.assertEqual(id_to_mjai(0), "1m")
        self.assertEqual(id_to_mjai(4), "5m")
        self.assertEqual(id_to_mjai(26), "9s")
        self.assertEqual(id_to_mjai(27), "E")
        self.assertEqual(id_to_mjai(33), "C")
        self.assertEqual(mjai_to_id("1m"), 0)
        self.assertEqual(mjai_to_id("9s"), 26)
        self.assertEqual(mjai_to_id("E"), 27)
        self.assertEqual(mjai_to_id("C"), 33)


class TestMjaiBot(unittest.TestCase):
    def setUp(self):
        # 234m 456m 789p 22s 33s: tenpai on 2s/3s, tanyao
        self.my_hand = [1, 2, 3, 4, 5, 6, 15, 16, 17, 19, 19, 20, 20]
        others = {
            1: [0, 0, 0, 3, 4, 5, 12, 13, 14, 15, 16, 17, 22],
            2: [1, 1, 1, 6, 7, 8, 15, 16, 17, 18, 18, 20, 20],
            3: [2, 2, 2, 9, 10, 11, 19, 20, 21, 22, 22, 23, 23],
        }
        self.tehais = ([[id_to_mjai(t) for t in self.my_hand]]
                       + [[id_to_mjai(t) for t in others[s]]
                          for s in (1, 2, 3)])

    def _bot(self, name="gto", seed=1):
        bot = MjaiBot(make_policy(name, seed), 0)
        bot.on_event({"type": "start_game", "id": 0, "names": ["me"] * 4})
        bot.on_event(start_kyoku(self.tehais))
        return bot

    def test_tsumo_reach_then_discard(self):
        bot = self._bot()
        acts = bot.on_event({"type": "tsumo", "actor": 0, "pai": "1m"})
        self.assertEqual([a["type"] for a in acts], ["reach", "dahai"])
        self.assertEqual(acts[1]["pai"], "1m")       # tsumu-giri
        self.assertTrue(acts[1]["tsumogiri"])

    def test_ron_on_fed_tile(self):
        from mahjong_mc.policies import ShantenPolicy

        class NoRiichi(ShantenPolicy):
            def decide_riichi(self, view):
                return False

        bot = MjaiBot(NoRiichi(seed=1), 0)
        bot.on_event({"type": "start_game", "id": 0, "names": ["me"] * 4})
        bot.on_event(start_kyoku(self.tehais))
        bot.on_event({"type": "tsumo", "actor": 0, "pai": "1m"})
        acts = bot.on_event({"type": "dahai", "actor": 1, "pai": "2s"})
        self.assertEqual([a["type"] for a in acts], ["hora"])
        self.assertEqual(acts[0]["target"], 1)

    def test_furiten_blocks_ron(self):
        from mahjong_mc.policies import ShantenPolicy

        class NoRiichi(ShantenPolicy):
            def decide_riichi(self, view):
                return False

        bot = MjaiBot(NoRiichi(seed=1), 0)
        bot.on_event({"type": "start_game", "id": 0, "names": ["me"] * 4})
        bot.on_event(start_kyoku(self.tehais))
        bot.on_event({"type": "tsumo", "actor": 0, "pai": "1m"})
        bot.on_event({"type": "tsumo", "actor": 0, "pai": "2s"})  # discard 2s
        acts = bot.on_event({"type": "dahai", "actor": 1, "pai": "2s"})
        self.assertEqual([a["type"] for a in acts], ["none"])

    def test_unrelated_discard_none(self):
        bot = self._bot()
        bot.on_event({"type": "tsumo", "actor": 0, "pai": "1m"})
        acts = bot.on_event({"type": "dahai", "actor": 1, "pai": "9s"})
        self.assertEqual([a["type"] for a in acts], ["none"])

    def test_opponent_call_tracked(self):
        bot = self._bot()
        bot.on_event({"type": "tsumo", "actor": 0, "pai": "1m"})
        bot.on_event({"type": "tsumo", "actor": 1, "pai": "3m"})
        bot.on_event({"type": "dahai", "actor": 2, "pai": "3m"})
        bot.on_event({"type": "pon", "actor": 1, "target": 2, "pai": "3m",
                      "consumed": ["3m", "3m"]})
        # seat 1 pons 3m: meld tracked, and the tile leaves the discarder's
        # (seat 2's) discard pile
        self.assertEqual(len(bot.melds[1]), 1)
        self.assertEqual(bot.melds[1][0][0], (2, 2, 2))
        self.assertNotIn(2, bot.discards[2])
        self.assertNotIn(2, bot.discards[1])

    def test_dora_marker_tracked(self):
        bot = self._bot()
        bot.on_event({"type": "dora", "dora_marker": "6m"})
        self.assertEqual(len(bot.dora_indicators), 2)

    def test_reach_deducts_points(self):
        bot = self._bot()
        bot.on_event({"type": "reach", "actor": 1})
        self.assertTrue(bot.riichi[1])
        self.assertEqual(bot.points[1], 24000)


class TestLocalDemo(unittest.TestCase):
    """The engine-vs-bot demo must run clean games through the adapter."""

    def test_demo_games_complete(self):
        import sys
        sys.path.insert(0, os.path.join(_PROJECT_ROOT, "examples"))
        from mjai_demo import BridgePolicy
        from mahjong_mc.engine import Game, Rules

        opponents = [make_policy(n, 1) for n in
                     ("greedy", "defensive", "random")]
        for k in range(20):
            gseed = 42000167 + k  # seed that previously exposed the
                                  # missed-tsumo divergence
            bridge = BridgePolicy("gto", gseed)
            game = Game([bridge] + opponents, rules=Rules(),
                        seed=gseed, dealer=gseed % 4)
            game.run()  # must not raise "discarded X which is not in hand"


class TestBotEntryPoint(unittest.TestCase):
    def test_subprocess_roundtrip(self):
        """mjai_bot.py reads events on stdin and writes actions on stdout."""
        script = [
            {"type": "start_game", "id": 0, "names": ["me"] * 4},
            {"type": "start_kyoku", "bakaze": "E", "dora_marker": "5m",
             "kyoku": 1, "honba": 0, "kyotaku": 0, "oya": 0,
             "scores": [25000] * 4,
             "tehais": [[id_to_mjai(t) for t in
                         (1, 2, 3, 4, 5, 6, 15, 16, 17, 19, 19, 20, 20)],
                        [id_to_mjai(t) for t in
                         (0, 0, 0, 3, 4, 5, 12, 13, 14, 15, 16, 17, 22)],
                        [id_to_mjai(t) for t in
                         (1, 1, 1, 6, 7, 8, 15, 16, 17, 18, 18, 20, 20)],
                        [id_to_mjai(t) for t in
                         (2, 2, 2, 9, 10, 11, 19, 20, 21, 22, 22, 23, 23)]]},
            {"type": "tsumo", "actor": 0, "pai": "1m"},
        ]
        proc = subprocess.run(
            [sys.executable, "mjai_bot.py", "0", "gto"],
            input="\n".join(json.dumps(e) for e in script) + "\n",
            capture_output=True, text=True, timeout=60,
            cwd=_PROJECT_ROOT,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        actions = [json.loads(line) for line in proc.stdout.splitlines()
                   if line.strip()]
        self.assertEqual([a["type"] for a in actions], ["reach", "dahai"])


class TestRedFiveDiscard(unittest.TestCase):
    """The server lists '5pr' before '5p' — never throw the aka dora away."""

    def test_prefers_plain_copy(self):
        acts = [{"type": "dahai", "pai": "5pr"},
                {"type": "dahai", "pai": "6p"},
                {"type": "dahai", "pai": "5p"}]
        out = MjaiBot._legalize({"type": "dahai", "pai": "5p"}, acts)
        self.assertEqual(out["pai"], "5p")

    def test_keeps_red_when_that_is_the_only_copy(self):
        acts = [{"type": "dahai", "pai": "5pr"},
                {"type": "dahai", "pai": "6p"}]
        out = MjaiBot._legalize({"type": "dahai", "pai": "5p"}, acts)
        self.assertEqual(out["pai"], "5pr")

    def test_other_discards_untouched(self):
        acts = [{"type": "dahai", "pai": "5pr"},
                {"type": "dahai", "pai": "9s"}]
        out = MjaiBot._legalize({"type": "dahai", "pai": "9s"}, acts)
        self.assertEqual(out["pai"], "9s")

    def test_pon_uses_the_server_consumed_spelling(self):
        # the chombo in logs/games: pon 5p with ["5p","5p"] while the server
        # wanted the red copy named explicitly
        acts = [{"type": "pon", "pai": "5p", "actor": 0,
                 "consumed": ["5pr", "5p"]}]
        out = MjaiBot._legalize(
            {"type": "pon", "pai": "5p", "consumed": ["5p", "5p"]}, acts)
        self.assertEqual(sorted(out["consumed"]), ["5p", "5pr"])

    def test_chi_picks_the_requested_sequence(self):
        acts = [{"type": "chi", "pai": "3s", "actor": 0,
                 "consumed": ["4s", "5sr"]},
                {"type": "chi", "pai": "3s", "actor": 0,
                 "consumed": ["1s", "2s"]}]
        out = MjaiBot._legalize(
            {"type": "chi", "pai": "3s", "consumed": ["4s", "5s"]}, acts)
        self.assertEqual(sorted(out["consumed"]), ["4s", "5sr"])
        out = MjaiBot._legalize(
            {"type": "chi", "pai": "3s", "consumed": ["2s", "1s"]}, acts)
        self.assertEqual(sorted(out["consumed"]), ["1s", "2s"])


if __name__ == "__main__":
    unittest.main()
