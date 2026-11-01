"""Four-player Mahjong engine — Japanese standard rules (riichi).

    - 136 tiles: 122-tile live wall + 14-tile dead wall (dora indicators)
    - win = 4 melds + pair, or seven pairs (a win needs at least one yaku)
    - riichi / ippatsu / permanent furiten / tsumu-giri after riichi
    - ankan / minkan / shoumankan (called and added), chankan ron
    - dora, ura dora, kan dora; rinshan kaihou, haitei, houtei
    - han/fu scoring (see scoring.py); dealer 1.5x; honba +300 ron / +100 each
    - exhaustive draw: noten-bappu (3000 total, split among tenpai)
    - dealer (oya) keeps the seat on win or draw

Each game is one independent kyoku: points reset to `start_points`, honba
starts at 0, riichi sticks start at 0 (see README "Known limitations").
Everything is deterministic given the seed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from . import tiles
from .rules import is_win, shanten
from .scoring import ANKAN, MINKAN, SHOUMINKAN, count_dora, score_hand

LIVE_WALL = 122  # 136 - 14 dead-wall tiles


@dataclass(frozen=True)
class Rules:
    allow_chi: bool = True
    allow_peng: bool = True
    allow_kan: bool = True
    seven_pairs: bool = True
    start_points: int = 25000
    max_turns: int = 600  # safety valve: pathological call loops end as a draw


class View:
    """Read-only snapshot of the game state handed to a policy."""

    __slots__ = (
        "seat", "turn", "hand", "counts", "melds", "discards",
        "melds_all", "wall_left", "last_discard", "rules",
        "dealer", "points", "riichi", "ippatsu", "honba",
        "riichi_sticks", "can_riichi", "dora_count", "last_drawn",
        "dora_indicators",
    )

    def __init__(self, seat, turn, hand, counts, melds, discards,
                 melds_all, wall_left, last_discard, rules, dealer, points,
                 riichi, ippatsu, honba, riichi_sticks, can_riichi,
                 dora_count, last_drawn, dora_indicators=()):
        self.seat = seat                    # 0..3
        self.turn = turn                    # number of discards so far
        self.hand = hand                    # tuple of concealed tile ids (sorted)
        self.counts = counts                # concealed hand counts (private list)
        self.melds = melds                  # own melds: tuple of (tiles, kind)
        self.discards = discards            # per-seat tuple of discard tuples
        self.melds_all = melds_all          # per-seat melds, all players
        self.wall_left = wall_left
        self.last_discard = last_discard    # (seat, tile) or None
        self.rules = rules
        self.dealer = dealer
        self.points = points
        self.riichi = riichi                # per-seat bool tuple
        self.ippatsu = ippatsu              # per-seat bool tuple
        self.honba = honba
        self.riichi_sticks = riichi_sticks
        self.can_riichi = can_riichi        # this seat may declare riichi now
        self.dora_count = dora_count        # visible dora in this holding
        self.dora_indicators = tuple(dora_indicators)  # dora marker tiles
        self.last_drawn = last_drawn        # tile id just drawn (or None)

    @property
    def total_counts(self):
        """Concealed hand + own melds: the player's 13/14-tile holding."""
        c = list(self.counts)
        for ts, _ in self.melds:
            for t in ts:
                c[t] += 1
        return c

    def visible_counts(self):
        """Copies of each tile already out of the wall (discards + all melds)."""
        v = [0] * tiles.NUM_TILE_TYPES
        for seat_discards in self.discards:
            for t in seat_discards:
                v[t] += 1
        for seat_melds in self.melds_all:
            for ts, _ in seat_melds:
                for t in ts:
                    v[t] += 1
        return v

    def unseen_counts(self):
        """Copies still possibly in the wall or opponents' concealed hands."""
        v = self.visible_counts()
        return [tiles.COPIES_PER_TYPE - v[t] - self.counts[t]
                for t in range(tiles.NUM_TILE_TYPES)]

    @property
    def is_dealer(self):
        return self.seat == self.dealer


class Game:
    """One four-player game under Japanese rules. Deterministic given seed."""

    def __init__(self, policies, rules=None, seed=None, dealer=0):
        if len(policies) != 4:
            raise ValueError("a game needs exactly 4 policies")
        self.rules = rules or Rules()
        self.policies = list(policies)
        self.dealer = dealer % 4
        self.rng = random.Random(seed)
        wall = tiles.shuffled_wall(self.rng)
        self.live_wall = wall[:LIVE_WALL]
        self.dead_wall = wall[LIVE_WALL:]
        self.counts = [[0] * tiles.NUM_TILE_TYPES for _ in range(4)]
        self.melds: list[list[tuple]] = [[] for _ in range(4)]
        self.discards: list[list[int]] = [[] for _ in range(4)]
        self.turn = 0
        self.points = [self.rules.start_points] * 4
        self.honba = 0
        self.riichi_sticks = 0
        self.riichi = [False] * 4
        self.ippatsu = [False] * 4
        self.last_discard = None    # (seat, tile)
        self.last_drawn = None      # tile id just drawn by the current seat
        self.drawn_from_rinshan = False
        self.winner = None          # seat 0-3, or None for a drawn game
        self.win_kind = None        # "tumo" | "ron" | "draw"
        self.win_tile = None
        self.loser = None           # discarder who fed a ron
        self.score = None           # scoring dict for the winning hand
        self.tenpai = None          # per-seat bool at exhaustive draw

        for seat in range(4):
            for _ in range(13):
                self.counts[seat][self.live_wall.pop(0)] += 1
        # dealer (oya) draws the 14th tile to open the game
        self.last_drawn = self.live_wall.pop(0)
        self.counts[self.dealer][self.last_drawn] += 1

    # ------------------------------------------------------------- helpers

    @property
    def dora_indicators(self):
        n = 1 + self._kan_count
        return tuple(self.dead_wall[i] for i in (0, 2, 4, 6, 8)[:n])

    @property
    def ura_indicators(self):
        n = 1 + self._kan_count
        return tuple(self.dead_wall[i] for i in (1, 3, 5, 7, 9)[:n])

    @property
    def _kan_count(self):
        return sum(1 for ms in self.melds for _, k in ms
                   if k in (ANKAN, MINKAN, SHOUMINKAN))

    def total_counts_of(self, seat):
        c = list(self.counts[seat])
        for ts, _ in self.melds[seat]:
            for t in ts:
                c[t] += 1
        return c

    # ------------------------------------------------------------------ run

    def run(self) -> None:
        current, just_drew = self.dealer, True
        while True:
            seat = current
            # 1. win on the tile just drawn (needs a yaku)
            if just_drew:
                if self._try_win(seat, self.counts[seat], tsumo=True):
                    return
                # ippatsu expires once the player has drawn without winning
                if self.ippatsu[seat]:
                    self.ippatsu[seat] = False
            # 2. kan from the drawn tile (ankan / added shouminkan)
            if just_drew and self.rules.allow_kan and not self.riichi[seat]:
                if self._try_kan_on_draw(seat):
                    if self.win_kind is not None:
                        return
                    current = seat
                    just_drew = True
                    continue
            # 3. riichi declaration (hand freezes after this turn)
            if just_drew and not self.riichi[seat] and not self.melds[seat]:
                view = self._view(seat, just_drew=True)
                if view.can_riichi and \
                        self.policies[seat].decide_riichi(view):
                    self._declare_riichi(seat)
            # 4. discard (riichi players are forced to tsumu-giri)
            if self.riichi[seat] and self.last_drawn is not None \
                    and not just_drew:
                t = self.last_drawn
            else:
                t = self.policies[seat].choose_discard(
                    self._view(seat, just_drew=just_drew))
            if self.counts[seat][t] <= 0:
                raise RuntimeError(
                    f"seat {seat} policy discarded {tiles.tile_name(t)} "
                    "which is not in hand"
                )
            self.counts[seat][t] -= 1
            self.discards[seat].append(t)
            self.last_discard = (seat, t)
            self.turn += 1
            # 5. ron (furiten-aware; nearest seat first)
            for k in range(1, 4):
                other = (seat + k) % 4
                if t in self.discards[other]:
                    continue  # permanent furiten
                test = list(self.counts[other])
                test[t] += 1
                if is_win(test, self.melds[other],
                          seven_pairs=self.rules.seven_pairs) and \
                        self._try_win(other, test, tsumo=False, win_tile=t,
                                      loser=seat):
                    return
            # 6. calls (peng / chi / kan), nearest seat first
            call = self._resolve_calls(seat, t)
            if self.win_kind is not None:
                return  # chankan during call resolution
            if call is not None:
                current = call
                just_drew = False
                continue
            # 7. next player draws
            if not self.live_wall or self.turn >= self.rules.max_turns:
                self._exhaustive_draw()
                return
            current = (seat + 1) % 4
            self.last_drawn = self.live_wall.pop(0)
            self.counts[current][self.last_drawn] += 1
            self.drawn_from_rinshan = False
            just_drew = True

    def _declare_riichi(self, seat: int) -> None:
        self.riichi[seat] = True
        self.riichi_sticks += 1
        self.points[seat] -= 1000
        self.ippatsu[seat] = True

    def _try_win(self, seat, counts14, tsumo, win_tile=None, loser=None,
                 chankan=False) -> bool:
        """Score the hand; award the win and return True, else False."""
        rinshan = self.drawn_from_rinshan
        haitei = tsumo and not self.live_wall
        houtei = (not tsumo) and not self.live_wall
        tile = win_tile if win_tile is not None else self.last_drawn
        score = score_hand(
            counts14, self.melds[seat], tile,
            tsumo=tsumo, dealer=self.dealer, seat=seat,
            riichi=self.riichi[seat], ippatsu=self.ippatsu[seat],
            dora=count_dora(counts14, self.melds[seat],
                            self.dora_indicators),
            ura_dora=count_dora(counts14, self.melds[seat],
                                self.ura_indicators),
            rinshan=rinshan, chankan=chankan, haitei=haitei, houtei=houtei,
            prevalent_wind=0)
        if score is None:
            return False  # no yaku: not a valid win under Japanese rules
        self._pay(seat, score, tsumo, loser, honba=self.honba)
        self.winner, self.win_kind = seat, "tumo" if tsumo else "ron"
        self.win_tile = tile
        self.loser = loser
        self.score = score
        return True

    def _pay(self, winner, score, tsumo, loser, honba) -> None:
        dealer_win = winner == self.dealer
        if tsumo:
            if dealer_win:
                pay = score["tsumo_oya"]
                for i in range(4):
                    if i != winner:
                        self.points[i] -= pay + 100 * honba
                        self.points[winner] += pay + 100 * honba
            else:
                ko_pay = score["tsumo_ko"]
                oya_pay = 2 * ko_pay
                for i in range(4):
                    if i == winner:
                        continue
                    p = oya_pay if i == self.dealer else ko_pay
                    self.points[i] -= p + 100 * honba
                    self.points[winner] += p + 100 * honba
        else:
            pay = score["ron_oya"] if dealer_win else score["ron_ko"]
            self.points[loser] -= pay + 300 * honba
            self.points[winner] += pay + 300 * honba
        self.points[winner] += 1000 * self.riichi_sticks
        self.riichi_sticks = 0

    def _exhaustive_draw(self) -> None:
        self.win_kind = "draw"
        self.tenpai = [shanten(self.total_counts_of(s)) == 0
                       for s in range(4)]
        tenpai_seats = [s for s in range(4) if self.tenpai[s]]
        noten_seats = [s for s in range(4) if not self.tenpai[s]]
        if tenpai_seats and noten_seats:
            # 3000 total, split among the tenpai; each noten pays an equal cut
            per = 3000 // len(tenpai_seats)
            rem = 3000 - per * len(tenpai_seats)
            for i, s in enumerate(tenpai_seats):
                self.points[s] += (per + (rem if i == 0 else 0)) \
                    * len(noten_seats)
            each_noten = 3000 // len(noten_seats)
            for s in noten_seats:
                self.points[s] -= each_noten

    # ----------------------------------------------------------------- kans

    def _try_kan_on_draw(self, seat: int) -> bool:
        """ankan or added shoumankan on the drawn tile. Returns True if kan."""
        t = self.last_drawn
        if t is None:
            return False
        options = []
        if self.counts[seat][t] == 4:
            options.append(("ankan", (t, t, t, t), ANKAN))
        for ts, kind in self.melds[seat]:
            if kind == "peng" and ts[0] == t:
                options.append(("shouminkan", (t, t, t, t), SHOUMINKAN))
        if not options:
            return False
        view = self._view(seat, just_drew=True)
        act = self.policies[seat].decide_kan(view, t, options)
        if act is None:
            return False
        kind, trio, mkind = act
        if kind == "ankan":
            self.counts[seat][t] -= 4
        else:  # added shoumankan replaces the peng meld
            self.counts[seat][t] -= 1
            self.melds[seat] = [m for m in self.melds[seat] if m[1] != "peng"
                                or m[0][0] != t]
        self.melds[seat].append((trio, mkind))
        # chankan: others may ron on an added shoumankan tile
        if kind == "shouminkan":
            for k in range(1, 4):
                ronner = (seat + k) % 4
                if t in self.discards[ronner]:
                    continue
                test = list(self.counts[ronner])
                test[t] += 1
                if is_win(test, self.melds[ronner],
                          seven_pairs=self.rules.seven_pairs) and \
                        self._try_win(ronner, test, tsumo=False,
                                      win_tile=t, loser=seat,
                                      chankan=True):
                    return True
        # reveal kan dora; draw replacement from the back of the live wall
        if not self.live_wall:
            self._exhaustive_draw()
            return True
        self.last_drawn = self.live_wall.pop()
        self.counts[seat][self.last_drawn] += 1
        self.drawn_from_rinshan = True
        return True

    # --------------------------------------------------------------- calls

    def _call_options(self, seat: int, t: int, discarder: int):
        """Legal call options on the discard of tile t by `discarder`."""
        r = self.rules
        options = []
        if self.riichi[seat]:
            return options  # riichi players cannot call
        if r.allow_kan and self.counts[seat][t] >= 3:
            options.append(("minkan", (t, t, t, t), MINKAN))
        if r.allow_peng and self.counts[seat][t] >= 2:
            options.append(("peng", (t, t, t), "peng"))
        if r.allow_chi and seat == (discarder + 1) % 4 and t < 27:
            n = t % 9
            base = t - n
            for lo in (n - 2, n - 1, n):
                if lo < 0 or lo + 2 > 8:
                    continue
                trio = (base + lo, base + lo + 1, base + lo + 2)
                if all(self.counts[seat][x] >= 1 for x in trio if x != t):
                    options.append(("chi", trio, "chi"))
        if r.allow_kan:
            for ts, kind in self.melds[seat]:
                if kind == "peng" and ts[0] == t:
                    options.append(("shouminkan", (t, t, t, t), SHOUMINKAN))
        return options

    def _resolve_calls(self, seat: int, t: int):
        """Handle calls on the discard of tile `t` by `seat`.

        Returns the calling seat, or None if nobody calls.
        """
        r = self.rules
        for k in range(1, 4):
            other = (seat + k) % 4
            options = self._call_options(other, t, seat)
            if not options:
                continue
            act = self.policies[other].decide_call(self._view(other), t,
                                                   options)
            if act is None:
                continue
            kind, trio, mkind = act
            if kind == "peng":
                self.counts[other][t] -= 2
            elif kind == "chi":
                for x in trio:
                    if x != t:
                        self.counts[other][x] -= 1
            else:  # minkan: three from hand
                self.counts[other][t] -= 3
            self.melds[other].append((trio, mkind))
            self.ippatsu = [False] * 4  # any call cancels everyone's ippatsu
            if kind == "minkan" or kind == "shouminkan":
                if kind == "shouminkan":
                    # chankan: others may ron on the shouminkan tile
                    for k2 in range(1, 4):
                        ronner = (other + k2) % 4
                        if ronner == other:
                            continue
                        if t in self.discards[ronner]:
                            continue
                        test = list(self.counts[ronner])
                        test[t] += 1
                        if is_win(test, self.melds[ronner],
                                  seven_pairs=self.rules.seven_pairs) and \
                                self._try_win(ronner, test, tsumo=False,
                                              win_tile=t, loser=other,
                                              chankan=True):
                            return None
                if not self.live_wall:
                    self._exhaustive_draw()
                    return None
                self.last_drawn = self.live_wall.pop()
                self.counts[other][self.last_drawn] += 1
                self.drawn_from_rinshan = True
            return other
        return None

    # ---------------------------------------------------------------- views

    def _view(self, seat: int, just_drew: bool = False) -> View:
        can_riichi = (
            just_drew and not self.riichi[seat] and not self.melds[seat]
            and self.points[seat] >= 1000 and len(self.live_wall) >= 4
            and shanten(self.total_counts_of(seat)) == 0
        )
        return View(
            seat=seat,
            turn=self.turn,
            hand=tuple(tiles.tiles_from_counts(self.counts[seat])),
            counts=list(self.counts[seat]),
            melds=tuple(self.melds[seat]),
            discards=tuple(tuple(d) for d in self.discards),
            melds_all=tuple(tuple(m) for m in self.melds),
            wall_left=len(self.live_wall),
            last_discard=self.last_discard,
            rules=self.rules,
            dealer=self.dealer,
            points=tuple(self.points),
            riichi=tuple(self.riichi),
            ippatsu=tuple(self.ippatsu),
            honba=self.honba,
            riichi_sticks=self.riichi_sticks,
            can_riichi=can_riichi,
            dora_count=count_dora(self.counts[seat], self.melds[seat],
                                  self.dora_indicators),
            last_drawn=self.last_drawn if just_drew else None,
            dora_indicators=tuple(self.dora_indicators),
        )

    def result(self) -> dict:
        return {
            "winner": self.winner,
            "kind": self.win_kind,
            "win_tile": self.win_tile,
            "loser": self.loser,
            "turns": self.turn,
            "wall_left": len(self.live_wall),
            "dealer": self.dealer,
            "points": list(self.points),
            "score": self.score,
            "tenpai": self.tenpai,
            "riichi": list(self.riichi),
            "riichi_sticks": self.riichi_sticks,
            "melds": [len(ms) for ms in self.melds],
        }
