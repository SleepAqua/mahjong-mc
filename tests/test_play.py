"""Tests for the interactive play mode."""

import io
import unittest

from mahjong_mc import tiles
from mahjong_mc.engine import Game
from mahjong_mc.play import (
    Announcer,
    HumanPolicy,
    QuitGame,
    _label,
    main,
    parse_tile,
    play_game,
)


class FirstTile:
    """Discards the first tile; never calls."""

    def choose_discard(self, view):
        return view.hand[0]

    def decide_call(self, view, tile, options):
        return None


def auto_prompt(prompt, view):
    """Always discards the first hand tile and passes on calls."""
    if prompt.startswith("Discard"):
        return tiles.tile_name(view.hand[0])
    if prompt.startswith("Call"):
        return "0"
    return "n"


class TestParseTile(unittest.TestCase):
    def test_suited(self):
        self.assertEqual(parse_tile("1m"), 0)
        self.assertEqual(parse_tile("5m"), 4)
        self.assertEqual(parse_tile("9s"), 26)
        self.assertEqual(parse_tile("1p"), 9)

    def test_honors(self):
        self.assertEqual(parse_tile("东"), 27)
        self.assertEqual(parse_tile("中"), 33)

    def test_case_and_whitespace(self):
        self.assertEqual(parse_tile(" 5M "), 4)

    def test_invalid(self):
        for bad in ("", "0m", "10m", "x", "5z", "mm"):
            self.assertIsNone(parse_tile(bad), bad)


class TestLabels(unittest.TestCase):
    def test_seat_labels(self):
        self.assertEqual(_label(0, 0), "You")
        self.assertEqual(_label(1, 0), "South")
        self.assertEqual(_label(3, 2), "North")
        self.assertEqual(_label(0, 2), "East")


class TestHumanPolicy(unittest.TestCase):
    def setUp(self):
        self.game = Game([FirstTile() for _ in range(4)], seed=1)
        self.view = self.game._view(0)

    def test_discard_by_number(self):
        pol = HumanPolicy(prompt_fn=lambda p, v: "1", out=io.StringIO())
        self.assertEqual(pol.choose_discard(self.view), self.view.hand[0])

    def test_discard_invalid_then_valid(self):
        answers = iter(["zz", "0", "99", "1"])
        pol = HumanPolicy(prompt_fn=lambda p, v: next(answers),
                          out=io.StringIO())
        self.assertEqual(pol.choose_discard(self.view), self.view.hand[0])

    def test_discard_not_held_reprompts(self):
        # find a tile the dealer does not hold
        held = set(self.view.hand)
        missing = next(t for t in range(34) if t not in held)
        answers = iter([tiles.tile_name(missing), "1"])
        pol = HumanPolicy(prompt_fn=lambda p, v: next(answers),
                          out=io.StringIO())
        self.assertEqual(pol.choose_discard(self.view), self.view.hand[0])

    def test_quit_raises(self):
        pol = HumanPolicy(prompt_fn=lambda p, v: "q", out=io.StringIO())
        with self.assertRaises(QuitGame):
            pol.choose_discard(self.view)

    def test_help_then_quit(self):
        answers = iter(["h", "?", "q"])
        pol = HumanPolicy(prompt_fn=lambda p, v: next(answers),
                          out=io.StringIO())
        with self.assertRaises(QuitGame):
            pol.choose_discard(self.view)
        with self.assertRaises(StopIteration):
            next(answers)  # all three answers consumed

    def test_call_pass(self):
        pol = HumanPolicy(prompt_fn=lambda p, v: "0", out=io.StringIO())
        options = [("peng", (4, 4, 4), "peng")]
        self.assertIsNone(pol.decide_call(self.view, 4, options))

    def test_call_take_first(self):
        pol = HumanPolicy(prompt_fn=lambda p, v: "1", out=io.StringIO())
        options = [("peng", (4, 4, 4), "peng")]
        self.assertEqual(pol.decide_call(self.view, 4, options), options[0])

    def test_call_by_name(self):
        pol = HumanPolicy(prompt_fn=lambda p, v: "chi", out=io.StringIO())
        options = [("chi", (0, 1, 2), "chi"), ("peng", (4, 4, 4), "peng")]
        self.assertEqual(pol.decide_call(self.view, 4, options), options[0])

    def test_no_options_no_prompt(self):
        called = []

        def fn(prompt, view):
            called.append(prompt)
            return "q"

        pol = HumanPolicy(prompt_fn=fn, out=io.StringIO())
        self.assertIsNone(pol.decide_call(self.view, 4, []))
        self.assertEqual(called, [])

    def test_riichi_prompt(self):
        # can_riichi must be True for the prompt to appear
        self.view.can_riichi = True
        pol = HumanPolicy(prompt_fn=lambda p, v: "y", out=io.StringIO())
        self.assertTrue(pol.decide_riichi(self.view))
        pol = HumanPolicy(prompt_fn=lambda p, v: "", out=io.StringIO())
        self.assertFalse(pol.decide_riichi(self.view))
        # without can_riichi, no prompt and no riichi
        self.view.can_riichi = False
        pol = HumanPolicy(prompt_fn=lambda p, v: "y", out=io.StringIO())
        self.assertFalse(pol.decide_riichi(self.view))

    def test_riichi_quit(self):
        self.view.can_riichi = True
        pol = HumanPolicy(prompt_fn=lambda p, v: "q", out=io.StringIO())
        with self.assertRaises(QuitGame):
            pol.decide_riichi(self.view)

    def test_kan_prompt(self):
        options = [("ankan", (4, 4, 4, 4), "ankan")]
        pol = HumanPolicy(prompt_fn=lambda p, v: "1", out=io.StringIO())
        self.assertEqual(pol.decide_kan(self.view, 4, options), options[0])
        pol = HumanPolicy(prompt_fn=lambda p, v: "0", out=io.StringIO())
        self.assertIsNone(pol.decide_kan(self.view, 4, options))
        self.assertIsNone(pol.decide_kan(self.view, 4, []))


class TestPlayGame(unittest.TestCase):
    def test_full_game_completes(self):
        out = io.StringIO()
        game = play_game(["human", "random", "random", "random"], seed=5,
                         hints=False, prompt_fn=auto_prompt, out=out)
        self.assertIsNotNone(game)
        self.assertIn(game.win_kind, ("tumo", "ron", "draw"))
        self.assertIn("Points (start", out.getvalue())

    def test_human_can_sit_anywhere(self):
        out = io.StringIO()
        game = play_game(["greedy", "human", "random", "random"], seed=9,
                         hints=True, prompt_fn=auto_prompt, out=out)
        self.assertIsNotNone(game)
        self.assertIn("You", out.getvalue())

    def test_quit_returns_none(self):
        out = io.StringIO()
        game = play_game(["human", "random", "random", "random"], seed=5,
                         prompt_fn=lambda p, v: "q", out=out)
        self.assertIsNone(game)
        self.assertIn("aborted", out.getvalue())

    def test_bad_policy_list(self):
        with self.assertRaises(ValueError):
            play_game(["greedy", "random", "random"], prompt_fn=auto_prompt)
        with self.assertRaises(ValueError):
            play_game(["greedy"] * 4, prompt_fn=auto_prompt)


class TestAnnouncer(unittest.TestCase):
    def test_narrates_moves(self):
        out = io.StringIO()
        game = Game([FirstTile() for _ in range(4)], seed=1)
        view = game._view(0)
        ann = Announcer(FirstTile(), human_seat=1, out=out)
        t = ann.choose_discard(view)
        self.assertEqual(t, view.hand[0])
        self.assertIn("discards", out.getvalue())


class TestCliValidation(unittest.TestCase):
    def test_wrong_count(self):
        with self.assertRaises(SystemExit):
            main(["--policies", "greedy,random,random"])

    def test_no_human(self):
        with self.assertRaises(SystemExit):
            main(["--policies", "greedy,random,random,random"])

    def test_two_humans(self):
        with self.assertRaises(SystemExit):
            main(["--policies", "human,human,random,random"])

    def test_unknown_policy(self):
        with self.assertRaises(SystemExit):
            main(["--policies", "human,bogus,random,random"])


if __name__ == "__main__":
    unittest.main()
