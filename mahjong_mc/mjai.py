"""mjai protocol adapter — run any mahjong-mc policy as a Tenhou/mjai bot.

The mjai spec (Gimite) is a JSONL stream: events in on stdin, actions out
on stdout. `MjaiView` deliberately mimics the engine's `View` API (hand,
counts, total_counts, melds, discards, melds_all, unseen_counts(),
wall_left, dealer, points, riichi, can_riichi, dora_count, last_drawn)
so every registered policy works unchanged.

Usage:  python3 mjai_bot.py <player_id> [policy_name]   (default gto)

Tile encoding: 0-8=1-9m, 9-17=1-9p, 18-26=1-9s, 27-30=东南西北,
31-33=白發中; mjai uses "1m".."9m", "E","S","W","N","P","F","C".
"""

from __future__ import annotations

import json

from . import tiles
from .policies import make_policy
from .rules import is_win, shanten
from .scoring import ANKAN, MINKAN, SHOUMINKAN, count_dora, score_hand

LIVE_WALL_START = 70  # 136 - 52 dealt - 14 dead wall


# ------------------------------------------------------------------ tiles

def mjai_to_id(pai: str) -> int:
    """'5m' -> 4; 'E' -> 27; 'P' -> 31."""
    if len(pai) >= 2 and pai[1] in "mps":
        return "mps".index(pai[1]) * 9 + int(pai[0]) - 1
    return "ESWN PFC".replace(" ", "").index(pai) + 27


def id_to_mjai(t: int) -> str:
    if t < 27:
        return f"{t % 9 + 1}{'mps'[t // 9]}"
    return ("ESWN PFC".replace(" ", ""))[t - 27]


# ------------------------------------------------------------------- view

class MjaiView:
    """View-compatible snapshot of the game as reconstructed from mjai."""

    __slots__ = (
        "seat", "turn", "hand", "counts", "melds", "discards",
        "melds_all", "wall_left", "last_discard", "rules",
        "dealer", "points", "riichi", "ippatsu", "honba",
        "riichi_sticks", "can_riichi", "dora_count", "last_drawn",
        "dora_indicators",
    )

    def __init__(self, seat, turn, counts, melds, discards, melds_all,
                 wall_left, last_discard, dealer, points, riichi,
                 can_riichi, dora_indicators, last_drawn, aka=0):
        self.seat = seat
        self.turn = turn
        self.counts = counts                     # private list
        self.hand = tuple(tiles.tiles_from_counts(counts))
        self.melds = tuple(melds)                # own melds: (tiles, kind)
        self.discards = tuple(tuple(d) for d in discards)
        self.melds_all = tuple(tuple(m) for m in melds_all)
        self.wall_left = wall_left
        self.last_discard = last_discard         # (seat, tile) or None
        self.rules = None
        self.dealer = dealer
        self.points = tuple(points)
        self.riichi = tuple(riichi)
        self.ippatsu = tuple(False for _ in range(4))
        self.honba = 0
        self.riichi_sticks = 0
        self.can_riichi = can_riichi
        self.dora_indicators = tuple(dora_indicators)
        # A red five is a dora of its own; the 34-type encoding loses that,
        # so the driver passes the count of red fives we actually hold.
        self.dora_count = (count_dora(counts, list(melds), dora_indicators)
                           + aka)
        self.last_drawn = last_drawn

    @property
    def total_counts(self):
        c = list(self.counts)
        for ts, _ in self.melds:
            for t in ts:
                c[t] += 1
        return c

    def visible_counts(self):
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
        v = self.visible_counts()
        return [tiles.COPIES_PER_TYPE - v[t] - self.counts[t]
                for t in range(tiles.NUM_TILE_TYPES)]

    @property
    def is_dealer(self):
        return self.seat == self.dealer


# -------------------------------------------------------------------- bot

class MjaiBot:
    """Turns an mjai event stream into actions from a Policy."""

    def __init__(self, policy, player_id: int):
        self.policy = policy
        self.me = player_id
        # RiichiLab mode: state comes only from echoed server events; the
        # bot answers request_action prompts instead of reacting per event.
        self.reactive = False
        self._reset()

    def _reset(self):
        self.counts = [[0] * tiles.NUM_TILE_TYPES for _ in range(4)]
        self.melds = [[] for _ in range(4)]
        self.discards = [[] for _ in range(4)]
        self.riichi = [False] * 4
        self.aka = [0] * 4          # red fives held (ours is the one we know)
        self.dora_indicators = []
        self.points = [25000] * 4
        self.dealer = 0
        self.wall_left = LIVE_WALL_START
        self.last_discard = None
        self.last_drawn = None
        self.turn = 0
        # per-kyoku reactive state (reactive itself is bot-level config,
        # set once in __init__ and never reset)
        self._trigger = None        # "draw" | "claim" | "discard"
        self._await_discard = False  # reach sent; ignore the re-sent tsumo

    # ------------------------------------------------------------ helpers

    def _view(self, just_drew=False):
        me = self.me
        can_riichi = (
            just_drew and not self.riichi[me] and not self.melds[me]
            and self.points[me] >= 1000 and self.wall_left >= 4
            and shanten(self._total(me)) == 0
        )
        return MjaiView(
            seat=me,
            turn=self.turn,
            counts=list(self.counts[me]),
            melds=list(self.melds[me]),
            discards=[list(d) for d in self.discards],
            melds_all=[list(m) for m in self.melds],
            wall_left=self.wall_left,
            last_discard=self.last_discard,
            dealer=self.dealer,
            points=list(self.points),
            riichi=list(self.riichi),
            can_riichi=can_riichi,
            dora_indicators=list(self.dora_indicators),
            last_drawn=self.last_drawn if just_drew else None,
            aka=self.aka[me],
        )

    def _total(self, seat):
        c = list(self.counts[seat])
        for ts, _ in self.melds[seat]:
            for t in ts:
                c[t] += 1
        return c

    def _can_win(self, seat, counts14, win_tile, tsumo):
        if win_tile in self.discards[seat]:
            return False  # permanent furiten (ron only)
        if not is_win(counts14, self.melds[seat]):
            return False
        sc = score_hand(
            counts14, self.melds[seat], win_tile,
            tsumo=tsumo, dealer=self.dealer, seat=seat,
            riichi=self.riichi[seat],
            dora=count_dora(counts14, self.melds[seat], self.dora_indicators),
            ura_dora=count_dora(counts14, self.melds[seat], []),
            prevalent_wind=0)
        return sc is not None  # a win needs at least one yaku

    def _call_options(self, seat, t, discarder):
        options = []
        if self.riichi[seat]:
            return options  # riichi players cannot call
        if self.counts[seat][t] >= 3:
            options.append(("minkan", (t, t, t, t), MINKAN))
        if self.counts[seat][t] >= 2:
            options.append(("peng", (t, t, t), "peng"))
        if seat == (discarder + 1) % 4 and t < 27:
            n = t % 9
            base = t - n
            for lo in (n - 2, n - 1, n):
                if lo < 0 or lo + 2 > 8:
                    continue
                trio = (base + lo, base + lo + 1, base + lo + 2)
                if all(self.counts[seat][x] >= 1 for x in trio if x != t):
                    options.append(("chi", trio, "chi"))
        for ts, kind in self.melds[seat]:
            if kind == "peng" and ts[0] == t:
                options.append(("shouminkan", (t, t, t, t), SHOUMINKAN))
        return options

    # ------------------------------------------------------------- events

    def on_event(self, ev: dict, decide=None):
        """Feed one mjai event. Returns actions (stdin mode) or [] (reactive)."""
        if decide is None:
            decide = not self.reactive
        t = ev.get("type")
        if t == "start_game":
            return []
        if t == "start_kyoku":
            self._on_start_kyoku(ev)
            return []
        if t == "tsumo":
            return self._on_tsumo(ev, decide)
        if t == "dahai":
            return self._on_dahai(ev, decide)
        if t == "reach":
            actor = ev.get("actor")
            if actor is not None and not self.riichi[actor]:
                self.riichi[actor] = True
                self.points[actor] -= 1000
                if actor == self.me:
                    self._trigger = "discard"
                    self._await_discard = True
            return []
        if t in ("chi", "pon", "kan", "ankan", "daiminkan", "kakan",
                 "shouminkan"):
            return self._on_call(ev)
        if t == "dora":
            self.dora_indicators.append(mjai_to_id(ev["dora_marker"]))
            return []
        if t == "hora":
            self._apply_scores(ev)
            return []
        if t == "ryukyoku":
            self._apply_scores(ev)
            return []
        if t == "end_kyoku":
            self._apply_scores(ev)
            return []
        return []

    def _apply_scores(self, ev):
        scores = ev.get("scores") or ev.get("deltas")
        if isinstance(scores, list) and len(scores) == 4:
            if ev.get("deltas"):
                self.points = [p + d for p, d in zip(self.points, scores)]
            else:
                self.points = list(scores)

    def _on_start_kyoku(self, ev):
        self._reset()
        self.dealer = ev.get("oya", 0)
        self.dora_indicators = [mjai_to_id(ev["dora_marker"])]
        scores = ev.get("scores")
        if isinstance(scores, list) and len(scores) == 4:
            self.points = list(scores)
        tehais = ev.get("tehais") or []
        self.aka = [0] * 4
        for seat, tiles_ in enumerate(tehais):
            for pai in tiles_:
                if pai == "?":
                    continue  # masked (other players' hands)
                self.counts[seat][mjai_to_id(pai)] += 1
                if pai.endswith("r") and seat == self.me:
                    self.aka[seat] += 1
        return []

    def _on_tsumo(self, ev, decide=True):
        actor = ev.get("actor")
        pai = ev["pai"]
        if pai == "?":
            # masked tile (other players' draws are hidden on RiichiLab)
            self.wall_left = max(0, self.wall_left - 1)
            return []
        t = mjai_to_id(pai)
        if actor == self.me and self._await_discard:
            # the server re-sends our tsumo after reach; do not double count
            self.last_drawn = t
            self._trigger = "discard"
            return []
        self.counts[actor][t] += 1
        if actor == self.me and pai.endswith("r"):
            self.aka[actor] += 1
        self.wall_left = max(0, self.wall_left - 1)
        if actor != self.me:
            return []
        self.last_drawn = t
        if not decide:
            self._trigger = "draw"
            return []
        view = self._view(just_drew=True)
        counts14 = list(self.counts[actor])
        # 1. tsumo win?
        if self._can_win(actor, counts14, t, tsumo=True):
            return [{"type": "hora", "actor": actor}]
        # 2. kan from the drawn tile?
        options = []
        if self.counts[actor][t] == 4:
            options.append(("ankan", (t, t, t, t), ANKAN))
        for ts, kind in self.melds[actor]:
            if kind == "peng" and ts[0] == t:
                options.append(("shouminkan", (t, t, t, t), SHOUMINKAN))
        if options:
            act = self.policy.decide_kan(view, t, options)
            if act is not None:
                kind = act[0]
                if kind == "ankan":
                    self.counts[actor][t] -= 4
                else:
                    self.counts[actor][t] -= 1
                    self.melds[actor] = [m for m in self.melds[actor]
                                         if not (m[1] == "peng" and m[0][0] == t)]
                self.melds[actor].append((act[1], act[2]))
                act_json = {"type": "kan", "actor": actor,
                            "pai": id_to_mjai(t),
                            "consumed": [id_to_mjai(t)] * 3}
                return [act_json]
        # 3. riichi (reach then tsumu-giri the drawn tile)?
        if view.can_riichi and self.policy.decide_riichi(view):
            self.riichi[actor] = True
            self.points[actor] -= 1000
            self.counts[actor][t] -= 1
            self.last_discard = (actor, t)
            self.discards[actor].append(t)
            self.turn += 1
            return [{"type": "reach"},
                    {"type": "dahai", "pai": id_to_mjai(t),
                     "tsumogiri": True}]
        # 4. plain discard
        tile = self.policy.choose_discard(view)
        return self._emit_discard(actor, tile)

    def _emit_discard(self, actor, tile):
        self.counts[actor][tile] -= 1
        self.discards[actor].append(tile)
        self.last_discard = (actor, tile)
        self.turn += 1
        return [{"type": "dahai", "pai": id_to_mjai(tile)}]

    def _on_dahai(self, ev, decide=True):
        actor = ev.get("actor")
        if actor == self.me and isinstance(ev.get("pai"), str) \
                and ev["pai"].endswith("r"):
            self.aka[actor] = max(0, self.aka[actor] - 1)
        t = mjai_to_id(ev["pai"])
        self.discards[actor].append(t)
        self.last_discard = (actor, t)
        self.turn += 1
        if actor == self.me:
            if self.counts[actor][t] > 0:
                self.counts[actor][t] -= 1
            self._await_discard = False
            self._trigger = None
            return []
        if not decide:
            self._trigger = "claim"
            return []
        # 1. ron?
        counts14 = list(self.counts[self.me])
        counts14[t] += 1
        if self._can_win(self.me, counts14, t, tsumo=False):
            return [{"type": "hora", "actor": self.me,
                     "target": actor, "pai": id_to_mjai(t)}]
        # 2. call?
        options = self._call_options(self.me, t, actor)
        if not options:
            return [{"type": "none"}]
        act = self.policy.decide_call(self._view(), t, options)
        if act is None:
            return [{"type": "none"}]
        kind, trio, _ = act
        if kind == "peng":
            self.counts[self.me][t] -= 2
            consumed = [t, t]
        elif kind == "chi":
            for x in trio:
                if x != t:
                    self.counts[self.me][x] -= 1
            consumed = [x for x in trio if x != t]
        elif kind == "minkan":
            self.counts[self.me][t] -= 3
            consumed = [t, t, t]
        else:  # shouminkan
            consumed = [t]
            self.melds[self.me] = [m for m in self.melds[self.me]
                                   if not (m[1] == "peng" and m[0][0] == t)]
        self.melds[self.me].append((trio, act[2]))
        self.last_drawn = None
        call_json = {
            "type": kind if kind in ("peng", "chi") else "kan",
            "actor": self.me,
            "target": actor,
            "pai": id_to_mjai(t),
            "consumed": [id_to_mjai(x) for x in consumed],
        }
        if kind in ("peng", "chi"):
            # must discard right after the call
            view = self._view()
            tile = self.policy.choose_discard(view)
            self.counts[self.me][tile] -= 1
            self.discards[self.me].append(tile)
            self.last_discard = (self.me, tile)
            self.turn += 1
            return [call_json,
                    {"type": "dahai", "pai": id_to_mjai(tile)}]
        return [call_json]  # minkan/shouminkan: wait for the replacement draw

    def _on_call(self, ev):
        """Bookkeeping for a meld event (any actor, including our own echo).

        Idempotent: in stdin mode the state was already applied when the
        bot emitted the call; in reactive mode this echo is the only
        application, so the presence check keeps both paths safe.
        """
        actor = ev.get("actor")
        pai = ev.get("pai")
        kind = ev["type"]
        consumed = [mjai_to_id(x) for x in ev.get("consumed", [])]
        if kind == "ankan":
            t = consumed[0] if consumed else mjai_to_id(pai)
            trio = (t, t, t, t)
            meld_kind = ANKAN
        elif kind in ("kan", "daiminkan"):
            t = mjai_to_id(pai)
            trio = (t, t, t, t)
            meld_kind = MINKAN
        elif kind in ("kakan", "shouminkan"):
            t = mjai_to_id(pai)
            trio = (t, t, t, t)
            meld_kind = SHOUMINKAN
        elif kind == "pon":
            t = mjai_to_id(pai)
            trio = (t, t, t)
            meld_kind = "peng"
        else:  # chi
            t = mjai_to_id(pai)
            trio = tuple(sorted([t] + consumed))
            meld_kind = "chi"
        if actor == self.me:
            for c in ev.get("consumed") or []:
                if isinstance(c, str) and c.endswith("r"):
                    self.aka[actor] = max(0, self.aka[actor] - 1)
        already = any(m[0] == trio or
                      (meld_kind == SHOUMINKAN and m[1] == SHOUMINKAN
                       and m[0][0] == t)
                      for m in self.melds[actor])
        if not already:
            if meld_kind == "chi":
                for x in consumed:
                    self.counts[actor][x] -= 1
            elif meld_kind == "peng":
                self.counts[actor][t] -= 2
            elif meld_kind == MINKAN:
                self.counts[actor][t] -= 3
            elif meld_kind == ANKAN:
                self.counts[actor][t] -= 4
            else:  # shouminkan
                self.counts[actor][t] -= 1
                self.melds[actor] = [m for m in self.melds[actor]
                                     if not (m[1] == "peng" and m[0][0] == t)]
            self.melds[actor].append((trio, meld_kind))
        # the called tile came from a discard: remove it from the
        # discarder's pile (it is now part of a meld)
        target = ev.get("target")
        if target is not None and self.discards[target] \
                and self.discards[target][-1] == t:
            self.discards[target].pop()
        if actor == self.me:
            # After our own pon/chi the server prompts for the follow-up
            # discard. Without this the stale "claim" trigger re-used the
            # called tile as a ron target and the discard came from the
            # legalizer's fallback (a random tile).
            self._trigger = "discard" if meld_kind in ("peng", "chi") else None
            self.last_drawn = None
        return []


    # --------------------------------------------------- RiichiLab reactive

    def respond(self, possible_actions, request_id=None):
        """Produce ONE action for a RiichiLab request_action prompt.

        Validates against possible_actions and falls back to a legal
        default so the bot can never send a chombo-worthy action.
        """
        me = self.me
        trigger = self._trigger
        if trigger == "draw":
            action = self._respond_draw()
        elif trigger == "claim":
            action = self._respond_claim()
        elif trigger == "discard":
            action = self._respond_discard()
        else:
            action = self._respond_default(possible_actions)
        action = self._legalize(action, possible_actions)
        action["actor"] = me
        if request_id is not None:
            action["request_id"] = request_id
        self._trigger = None
        return action

    def _respond_draw(self):
        me = self.me
        t = self.last_drawn
        view = self._view(just_drew=True)
        # 1. tsumo win?
        if t is not None and self._can_win(me, list(self.counts[me]), t,
                                           tsumo=True):
            return {"type": "hora"}
        # 2. kan from the drawn tile?
        options = []
        if t is not None and self.counts[me][t] == 4:
            options.append(("ankan", (t, t, t, t), ANKAN))
        for ts, kind in self.melds[me]:
            if kind == "peng" and ts[0] == t:
                options.append(("shouminkan", (t, t, t, t), SHOUMINKAN))
        if options:
            act = self.policy.decide_kan(view, t, options)
            if act is not None:
                kind = act[0]
                if kind == "ankan":
                    return {"type": "ankan",
                            "consumed": [id_to_mjai(t)] * 4}
                if kind == "minkan":
                    return {"type": "daiminkan", "pai": id_to_mjai(t),
                            "consumed": [id_to_mjai(t)] * 3}
                return {"type": "kakan", "pai": id_to_mjai(t),
                        "consumed": [id_to_mjai(t)]}
        # 3. riichi?
        if view.can_riichi and self.policy.decide_riichi(view):
            self.riichi[me] = True
            self.points[me] -= 1000
            self._await_discard = True
            self._trigger = "discard"
            return {"type": "reach"}
        # 4. discard
        tile = self.policy.choose_discard(view)
        if tile is None:
            return {"type": "none"}
        return {"type": "dahai", "pai": id_to_mjai(tile)}

    def _respond_claim(self):
        me = self.me
        if self.last_discard is None:
            return {"type": "none"}
        discarder, t = self.last_discard
        counts14 = list(self.counts[me])
        counts14[t] += 1
        if self._can_win(me, counts14, t, tsumo=False):
            return {"type": "hora", "target": discarder,
                    "pai": id_to_mjai(t)}
        options = self._call_options(me, t, discarder)
        if not options:
            return {"type": "none"}
        act = self.policy.decide_call(self._view(), t, options)
        if act is None:
            return {"type": "none"}
        kind, trio, _ = act
        if kind == "peng":
            return {"type": "pon", "pai": id_to_mjai(t),
                    "consumed": [id_to_mjai(t)] * 2}
        if kind == "chi":
            return {"type": "chi", "pai": id_to_mjai(t),
                    "consumed": [id_to_mjai(x) for x in trio if x != t]}
        if kind == "minkan":
            return {"type": "daiminkan", "pai": id_to_mjai(t),
                    "consumed": [id_to_mjai(t)] * 3}
        return {"type": "kakan", "pai": id_to_mjai(t),
                "consumed": [id_to_mjai(t)]}

    def _respond_discard(self):
        """Discard after our own reach (or an untriggered prompt)."""
        view = self._view()
        self._await_discard = False
        tile = self.policy.choose_discard(view)
        if tile is None:
            return {"type": "none"}
        return {"type": "dahai", "pai": id_to_mjai(tile)}

    def _respond_default(self, possible_actions):
        """Fallback when no trigger is known.

        Never decline a win: if the server offers `hora`, take it verbatim.
        Otherwise discard if we must act, else pass.
        """
        for a in possible_actions:
            if a.get("type") == "hora":
                return dict(a)
        for a in possible_actions:
            if a.get("type") == "dahai":
                tile = None
                try:
                    tile = self.policy.choose_discard(self._view())
                except Exception:
                    tile = None
                pai = id_to_mjai(tile) if tile is not None else a["pai"]
                # same red-five rule as _legalize: prefer the plain copy
                def _plain(p):
                    return str(p).endswith("r")
                legal = sorted(
                    (p["pai"] for p in possible_actions
                     if p.get("type") == "dahai"),
                    key=_plain)
                pick = next((p for p in legal if p == pai), None)
                if pick is None:
                    pick = next((p for p in legal
                                 if _plain(p) is False and _plain(pai)
                                 and p == pai[:-1]), None)
                return {"type": "dahai", "pai": pick or legal[0]}
        return {"type": "none"}

    @staticmethod
    def _legalize(action, possible_actions):
        """Guarantee the action is one of the server's legal options.

        Hora is matched on TYPE ALONE and answered with the server's own
        option dict. RiichiLab's hora option carries no tile
        ({"type": "hora", "actor": 0}), so comparing tiles here silently
        turned every ron into a pass -- the single worst bug this driver
        had (0 ron wins in 51 ranked games).

        Discards are matched by TILE TYPE, not string: the server names red
        fives "5mr"/"5pr"/"5sr", and holding the red copy means "5p" is not
        a legal discard while "5pr" alone is. Exact-string matching fell
        through to the random legal fallback in that case.

        Claims (chi/pon/kan) have the same problem one level deeper: the
        `consumed` list must use the server's own red-five spelling or the
        action comes back "not_in_legal_actions" and the round ends in a
        chombo. So claims are matched on tile type plus the *multiset* of
        consumed tiles and answered with the server's option dict.
        """
        if action.get("type") == "hora":
            for p in possible_actions:
                if p.get("type") == "hora":
                    return dict(p)

        def norm(pai):
            return pai[:-1] if isinstance(pai, str) and pai.endswith("r") \
                else pai

        def norm_set(vals):
            return sorted(norm(v) for v in vals or [])

        if action.get("type") == "dahai":
            want = norm(action.get("pai"))
            cands = [p for p in possible_actions
                     if p.get("type") == "dahai"
                     and norm(p.get("pai")) == want]
            if cands:
                # The server lists the red copy before the plain one
                # ('5pr', …, '5p'). Taking the first match threw the aka
                # dora away 54 times while a plain five was in hand, so
                # always prefer the plain spelling.
                cands.sort(key=lambda p: str(p.get("pai", "")).endswith("r"))
                return dict(cands[0])   # keep the server's exact spelling

        if action.get("type") in ("chi", "pon", "kan", "daiminkan", "ankan",
                                  "kakan"):
            want_c = norm_set(action.get("consumed"))
            for p in possible_actions:
                if p.get("type") != action.get("type"):
                    continue
                if norm(p.get("pai")) != norm(action.get("pai")):
                    continue
                # same sequence / same pair, whatever the red-five spelling
                if norm_set(p.get("consumed")) == want_c:
                    return dict(p)

        def matches(a, b):
            if a.get("type") != b.get("type"):
                return False
            if a.get("type") == "dahai" and a.get("pai") != b.get("pai"):
                return False
            if a.get("pai") is not None and a.get("pai") != b.get("pai"):
                return False
            return True

        if any(matches(action, p) for p in possible_actions):
            return dict(action)
        # our choice is not legal (state drift) — pick a safe legal action
        for want in ("dahai", "none", "hora", "reach"):
            for p in possible_actions:
                if p.get("type") == want:
                    if want == "dahai" and p.get("tsumogiri"):
                        return {"type": "dahai", "pai": p["pai"]}
                    return {"type": want,
                            **({"pai": p["pai"]} if "pai" in p else {})}
        return {"type": possible_actions[0]["type"]
                if possible_actions else "none"}


# ------------------------------------------------------------------ entry

def run_bot(policy_name="gto", player_id=0, seed=None, stdin=None,
            stdout=None):
    """Read mjai events from stdin, write actions to stdout."""
    import sys
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    policy = make_policy(policy_name, seed)
    bot = MjaiBot(policy, player_id)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        for action in bot.on_event(ev):
            stdout.write(json.dumps(action, separators=(",", ":")) + "\n")
            stdout.flush()
    return bot
