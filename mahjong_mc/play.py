"""Interactive play mode: one human seat against AI policies.

    python3 -m mahjong_mc.play                                  # human vs greedy/defensive/random
    python3 -m mahjong_mc.play --policies greedy,human,random,random
    python3 -m mahjong_mc.play --no-hints                       # hide shanten hints

Controls at the discard prompt: type a tile ("5m", "东"), its number
("[3]"), "h" for help, "q" to quit. When you can call peng/chi you get a
numbered menu; "0" passes.
"""

from __future__ import annotations

import argparse
import io
import sys

from . import tiles
from .engine import Game, Rules
from .policies import available, make_policy
from .rules import shanten

SEAT_NAMES = ("East", "South", "West", "North")  # seat 0 is the dealer


class QuitGame(Exception):
    """Raised when the human types quit."""


# ------------------------------------------------------------------ parsing

def parse_tile(text: str):
    """'5m' / '1p' / '9s' / '东' -> tile id, or None if unrecognised."""
    ans = (text or "").strip().lower()
    if len(ans) == 2 and ans[1] in "mps" and ans[0].isdigit():
        n = int(ans[0])
        if 1 <= n <= 9:
            return {"m": 0, "p": 9, "s": 18}[ans[1]] + n - 1
        return None
    if len(ans) == 1 and ans in _HONOR_IDS:
        return _HONOR_IDS[ans]
    return None


_HONOR_IDS = {tiles.tile_name(t): t for t in range(27, 34)}


def _label(seat: int, human_seat: int) -> str:
    return "You" if seat == human_seat else SEAT_NAMES[seat]


def _tile_str(t: int) -> str:
    return tiles.tile_name(t)


def _meld_str(meld) -> str:
    return "".join(_tile_str(x) for x in meld)


def _minus(counts, t):
    c = list(counts)
    c[t] -= 1
    return c


# ------------------------------------------------------------------ render

_HELP = """\
Commands:
  5m / 1p / 9s / 东   discard that tile (also accepts its [number])
  [3]                discard the 3rd tile in your hand
  h                  this help
  q                  quit the game\
"""


def _print_help(out):
    print(_HELP, file=out)


def render(view, human_seat: int, hints: bool, out) -> None:
    """Print the human player's view of the table."""
    hand = list(view.hand)
    print(f"\nYour hand ({len(hand)} tiles):", file=out)
    print("  " + " ".join(f"[{i + 1}]{_tile_str(t)}" for i, t in enumerate(hand)),
          file=out)
    if hints and hand:
        total = view.total_counts
        parts = [f"{_tile_str(t)}→{shanten(_minus(total, t))}"
                 for t in sorted(set(hand))]
        print("  discard→shanten:  " + "  ".join(parts), file=out)
    print("Table:", file=out)
    for seat in range(4):
        label = _label(seat, human_seat)
        melds = "  ".join(_meld_str(m) for m, _ in view.melds_all[seat]) or "-"
        disc = " ".join(_tile_str(t) for t in view.discards[seat]) or "-"
        mark = " [riichi]" if view.riichi[seat] else ""
        dealer_mark = " (oya)" if seat == view.dealer else ""
        print(f"  {label:<6} {dealer_mark:<6} melds: {melds:<14} "
              f"discards: {disc}{mark}", file=out)
    print(f"  wall: {view.wall_left} tiles left   "
          f"dora in hand: {view.dora_count}   points: {view.points[human_seat]}",
          file=out)


# ------------------------------------------------------------------ policies

def _default_prompt(prompt: str, view) -> str:
    return input(prompt)


class HumanPolicy:
    """A policy driven by terminal input. `prompt_fn(prompt, view) -> str`."""

    name = "human"

    def __init__(self, prompt_fn=None, seat=0, hints=True, out=None):
        self.prompt_fn = prompt_fn or _default_prompt
        self.seat = seat
        self.hints = hints
        self.out = out or sys.stdout

    def choose_discard(self, view):
        render(view, self.seat, self.hints, self.out)
        while True:
            try:
                ans = self.prompt_fn("Discard> ", view)
            except (EOFError, KeyboardInterrupt):
                raise QuitGame
            ans = (ans or "").strip().lower()
            if ans in ("q", "quit", "exit"):
                raise QuitGame
            if ans in ("h", "help", "?"):
                _print_help(self.out)
                continue
            tile = None
            if ans.isdigit():
                i = int(ans) - 1
                if 0 <= i < len(view.hand):
                    tile = view.hand[i]
                else:
                    print(f"  no tile number {int(ans)}; "
                          f"you hold {len(view.hand)} tiles", file=self.out)
                    continue
            else:
                tile = parse_tile(ans)
                if tile is None:
                    print(f"  can't parse {ans!r} — try '5m', '东', "
                          "or a number", file=self.out)
                    continue
                if view.counts[tile] <= 0:
                    print(f"  you don't hold {_tile_str(tile)}", file=self.out)
                    continue
            return tile

    def decide_call(self, view, tile, options):
        if not options:
            return None
        print(f"\n{_tile_str(tile)} discarded — you can call:", file=self.out)
        for i, act in enumerate(options, 1):
            kind, trio = act[0], act[1]
            print(f"  [{i}] {kind:<11} {_meld_str(trio)}", file=self.out)
        print("  [0] pass", file=self.out)
        while True:
            try:
                ans = self.prompt_fn("Call> ", view)
            except (EOFError, KeyboardInterrupt):
                raise QuitGame
            ans = (ans or "").strip().lower()
            if ans in ("q", "quit", "exit"):
                raise QuitGame
            if ans in ("0", "n", "no", "pass"):
                return None
            if ans.isdigit() and 1 <= int(ans) <= len(options):
                return options[int(ans) - 1]
            for act in options:
                if ans == act[0]:
                    return act
            print("  type a number, the call name, or 0 to pass",
                  file=self.out)

    def decide_riichi(self, view):
        if not view.can_riichi:
            return False
        print(f"\nYou are tenpai — riichi? (costs 1000; "
              f"{view.riichi_sticks} sticks on table)", file=self.out)
        while True:
            try:
                ans = self.prompt_fn("Riichi? [y/N] ", view)
            except (EOFError, KeyboardInterrupt):
                raise QuitGame
            ans = (ans or "").strip().lower()
            if ans in ("q", "quit", "exit"):
                raise QuitGame
            if ans in ("", "n", "no"):
                return False
            if ans in ("y", "yes"):
                return True
            print("  y or n", file=self.out)

    def decide_kan(self, view, tile, options):
        if not options:
            return None
        print(f"\nDrew {_tile_str(tile)} — you can kan:", file=self.out)
        for i, act in enumerate(options, 1):
            kind, trio = act[0], act[1]
            print(f"  [{i}] {kind:<11} {_meld_str(trio)}", file=self.out)
        print("  [0] no kan", file=self.out)
        while True:
            try:
                ans = self.prompt_fn("Kan> ", view)
            except (EOFError, KeyboardInterrupt):
                raise QuitGame
            ans = (ans or "").strip().lower()
            if ans in ("q", "quit", "exit"):
                raise QuitGame
            if ans in ("0", "n", "no", "pass"):
                return None
            if ans.isdigit() and 1 <= int(ans) <= len(options):
                return options[int(ans) - 1]
            for act in options:
                if ans == act[0]:
                    return act
            print("  type a number, the kan name, or 0", file=self.out)


class Announcer:
    """Wraps an AI policy so its moves are narrated to the human."""

    def __init__(self, inner, human_seat: int, out=None):
        self.inner = inner
        self.human_seat = human_seat
        self.out = out or sys.stdout

    def choose_discard(self, view):
        t = self.inner.choose_discard(view)
        print(f"  {_label(view.seat, self.human_seat)} discards "
              f"{_tile_str(t)}", file=self.out)
        return t

    def decide_call(self, view, tile, options):
        act = self.inner.decide_call(view, tile, options)
        if act is not None:
            print(f"  {_label(view.seat, self.human_seat)} calls {act[0]} on "
                  f"{_tile_str(tile)}", file=self.out)
        return act

    def decide_riichi(self, view):
        act = self.inner.decide_riichi(view)
        if act:
            print(f"  {_label(view.seat, self.human_seat)} declares RIICHI!",
                  file=self.out)
        return act

    def decide_kan(self, view, tile, options):
        act = self.inner.decide_kan(view, tile, options)
        if act is not None:
            print(f"  {_label(view.seat, self.human_seat)} calls {act[0]} "
                  f"({_meld_str(act[1])})", file=self.out)
        return act


# ------------------------------------------------------------------ driver

def play_game(policies, seed=None, hints=True, rules=None, prompt_fn=None,
              out=None, dealer=0):
    """Play one game. `policies` = 4 names, exactly one 'human'.

    Returns the finished Game, or None if the human quit.
    """
    out = out or sys.stdout
    if len(policies) != 4:
        raise ValueError("exactly 4 policies required")
    if policies.count("human") != 1:
        raise ValueError("exactly one seat must be 'human'")
    human_seat = policies.index("human")
    pols = []
    for i, name in enumerate(policies):
        if name == "human":
            pols.append(HumanPolicy(prompt_fn=prompt_fn, seat=i,
                                    hints=hints, out=out))
        else:
            pols.append(Announcer(make_policy(name, seed), human_seat,
                                  out=out))
    game = Game(pols, rules=rules or Rules(), seed=seed, dealer=dealer)
    try:
        game.run()
    except QuitGame:
        print("\nGame aborted. Bye!", file=out)
        return None
    _print_result(game, human_seat, out)
    return game


def _print_result(game, human_seat: int, out) -> None:
    print("\n" + "=" * 52, file=out)
    if game.winner is None:
        print("Exhaustive draw (nagashi mangan not implemented).", file=out)
        tp = game.tenpai or [False] * 4
        for s in range(4):
            print(f"  {_label(s, human_seat):<6} "
                  f"{'tenpai' if tp[s] else 'noten'}", file=out)
    else:
        who = _label(game.winner, human_seat)
        sc = game.score or {}
        yaku = ", ".join(sc.get("yaku", [])) or "-"
        limit = sc.get("limit") or ""
        if game.win_kind == "tumo":
            how = "tumo"
        else:
            how = f"ron on {_tile_str(game.win_tile)}"
        if game.win_kind == "ron":
            by = ("you dealt in!" if game.loser == human_seat
                  else f"{_label(game.loser, human_seat)} dealt in")
            how += f" ({by})"
        print(f"{who} won by {how}.", file=out)
        print(f"  {sc.get('han', 0)} han {sc.get('fu', 0)} fu "
              f"{('— ' + limit) if limit else ''}  [{yaku}]", file=out)
        if sc.get("yakuman"):
            print(f"  YAKUMAN x{sc['yakuman']}!", file=out)
        w = game.winner
        concealed = tiles.tiles_from_counts(game.counts[w])
        if game.win_kind == "ron":
            concealed = concealed + [game.win_tile]
        melds = "  ".join(_meld_str(m) for m, _ in game.melds[w])
        print(f"  winning hand: {melds or '-'}  +  "
              f"{' '.join(_tile_str(t) for t in concealed)}", file=out)
    print(f"Points (start {game.rules.start_points}): "
          + "  ".join(f"{_label(s, human_seat)} {p}"
                      for s, p in enumerate(game.points)), file=out)
    if game.riichi_sticks:
        print(f"  {game.riichi_sticks} riichi stick(s) remain on the table",
              file=out)


# ------------------------------------------------------------------ CLI

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="mahjong-mc-play",
        description="Play a hand of Mahjong against AI strategies",
    )
    ap.add_argument("--policies", default="human,greedy,defensive,random",
                    help="comma-separated 4 names, exactly one 'human'; "
                         "AI names: " + ", ".join(available()))
    ap.add_argument("--seed", type=int, default=None,
                    help="seed for the AI players (omit for a random game)")
    ap.add_argument("--no-hints", action="store_true",
                    help="hide the discard→shanten hint line")
    args = ap.parse_args(argv)

    names = [s.strip() for s in args.policies.split(",") if s.strip()]
    if len(names) != 4:
        ap.error("--policies needs exactly 4 comma-separated names")
    if names.count("human") != 1:
        ap.error("exactly one seat must be 'human'")
    for n in names:
        if n != "human" and n not in available():
            ap.error(f"unknown policy {n!r}; available: human, "
                     + ", ".join(available()))

    hints = not args.no_hints
    print("Type 'h' at any prompt for help, 'q' to quit.")
    dealer = 0
    while True:
        game = play_game(names, seed=args.seed, hints=hints, dealer=dealer)
        dealer = (dealer + 1) % 4
        if game is None:
            break
        try:
            ans = input("\nPlay again? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if ans not in ("y", "yes"):
            break


if __name__ == "__main__":
    main()
