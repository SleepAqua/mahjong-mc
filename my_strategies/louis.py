"""Louis's strategy — hand-built rules + defence theory.

Implements the rule set in doc/strategy.md (see that file for the reasoning
and sources). Summary:

  1. lone-tile discard order: guest wind, round wind, 1/9, dragon, seat
     wind, 2/8, 3/7, 4/6, 5
  2. when nothing is lone: ryanmen > pair > kanchan > penchan
  3. keep dora
  4. three pairs: consider breaking one for a better wait (never before a
     lone tile)
  5. four+ pairs: seven pairs
  6. someone riichi + we are not tenpai -> full fold (betaori)
  7. defence: genbutsu, suji, wall (kabe / no-chance), honour counting
  8. 10+ distinct terminal/honour types in the deal -> thirteen orphans

Registered as policy name ``louis``.
"""

from __future__ import annotations

import json
import os

from mahjong_mc.policies import Policy, register
from mahjong_mc.rules import kokushi_shanten, shanten, ukeire
from mahjong_mc.scoring import dora_next

WINDS = (27, 28, 29, 30)
DRAGONS = (31, 32, 33)
HONORS = tuple(range(27, 34))
TERMINALS = (0, 8, 9, 17, 18, 26)
YAO = frozenset(TERMINALS + HONORS)

SUIT_NAMES = "mps"


def _seat_wind(seat, dealer):
    return (seat - dealer) % 4


def seven_pairs_shanten(total) -> int:
    """Shanten to seven pairs (0 = tenpai, -1 = complete)."""
    pairs = sum(1 for c in total if c >= 2)
    kinds = sum(1 for c in total if c >= 1)
    s = 6 - pairs
    if kinds < 7:                       # not enough distinct types to pair up
        s = max(s, 7 - kinds)
    return s


def _is_lone(total, t) -> bool:
    """True when tile t shares no block with the rest of the holding."""
    if total[t] >= 2:                    # a pair/triplet is a block
        return False
    if t >= 27:                          # a single honour is always lone
        return True
    n = t % 9
    for d in (-2, -1, 1, 2):
        if 0 <= n + d <= 8 and total[t + d] > 0:
            return False
    return True


def _lone_rank(total, t, seat, dealer, turn=0, seen=0, round_wind=27) -> int:
    """Discard priority for a lone tile: lower = throw away sooner.

    0 guest wind (or a dead yakuhai) · 1 isolated 1/9 · 3 round wind / dragon
    4 seat wind · 5 lone 2/8 · 6 lone 3/7 · 7 lone 4/6 · 8 lone 5

    Refined rule: a lone yakuhai is only worth keeping while it can still be
    paired. Once two copies are visible elsewhere, or the hand is six discards
    old, it drops to rank 0 and goes before the terminals — holding a dead
    honour is how hands rot into no-yaku.
    """
    n = t % 9
    if t >= 27:
        dead = seen >= 2 or turn >= LouisPolicy.HONOR_DEAD_TURN
        if t == round_wind:
            # a live round wind is 1 han like a dragon: keep it with the other
            # value honours, not ahead of the terminals
            return 0 if dead else 3
        if t == WINDS[_seat_wind(seat, dealer)]:
            return 0 if dead else 4
        if t in DRAGONS:
            return 0 if dead else 3
        return 0                          # guest wind (kengi) — worthless
    if n in (0, 8):                       # 1 or 9
        return 2
    if n in (1, 7):                       # 2 or 8
        return 5
    if n in (2, 6):                       # 3 or 7
        return 6
    if n in (3, 5):                       # 4 or 6
        return 7
    return 8                              # 5 — most valuable


def _growth(total, t) -> int:
    """How much tile t can still grow: held neighbours within 2, plus its pair."""
    if t >= 27:
        return 3 * (total[t] - 1)
    n = t % 9
    g = (total[t] - 1) * 2
    for d in (-2, -1, 1, 2):
        if 0 <= n + d <= 8 and total[t + d] > 0:
            g += 2 if abs(d) == 1 else 1
    return g


def _block_count(total) -> int:
    """Blocks the hand already has: completed melds, pairs and partial runs."""
    c = list(total)
    blocks = 0
    for t in range(34):
        while c[t] >= 3:
            c[t] -= 3
            blocks += 1
    for t in range(34):
        if c[t] >= 2:
            c[t] -= 2
            blocks += 1
    for t in range(27):
        n = t % 9
        if c[t] == 0:
            continue
        for d in (1, 2):
            j = t + d
            if j < 27 and n + d <= 8 and c[j] > 0:
                c[t] -= 1
                c[j] -= 1
                blocks += 1
                break
    return blocks


def _shape_score(total) -> int:
    """Block quality of a 13-tile holding.

    Refined rule 2: a pair is a *head* before it is a shape. The first pair is
    worth more than a kanchan or penchan (without a head the hand is not even
    tenpai); extra pairs drop back to ryanmen-adjacent value because they feed
    shanpon and chiitoitsu instead of a new block.
    """
    c = list(total)
    score = 0
    for t in range(34):
        while c[t] >= 3:                  # triplet
            c[t] -= 3
            score += 3
    head = any(x >= 2 for x in c)
    for t in range(34):
        if c[t] >= 2:
            c[t] -= 2
            score += 5 if not head else 3  # head bonus for the first pair
            head = True
    # two-tile partial runs, best shape first
    for t in range(27):
        n = t % 9
        if c[t] == 0:
            continue
        for d, val in ((1, 4), (2, 2)):   # adjacent = ryanmen, gap = kanchan
            j = t + d
            if j < 27 and n + d <= 8 and c[j] > 0:
                if d == 1:
                    penchan = n == 0 or j % 9 == 8
                    val = 1 if penchan else 4
                else:
                    val = 2
                c[t] -= 1
                c[j] -= 1
                score += val
                break
    return score


class LouisPolicy(Policy):
    name = "louis"

    # ---- tunables (examples/evolve_louis.py mutates these) --------------
    # defaults = the evolved weights (see docs/strategy.md §11). The JSON
    # sidecar overrides these, but if it is missing these are still the tuned
    # values, not the original guesses.
    HONOR_DEAD_TURN = 7    # turn after which a lone yakuhai is dead
    DANGER_WEIGHT = 2.0     # how hard danger subtracts from an attacking discard
    CALL_MAX_SHANTEN = 3    # only call when the hand is this close
    BLOCK_CUT = True        # five-block theory: cut the weakest of 6+ blocks

    # ---- threats that are not in riichi ------------------------------
    # Over the 100 logged games 30% of our deal-ins went to *open* hands and
    # another 8% to dama, yet the threat list only knew about riichi seats --
    # so against those hands the bot played pure offence into fresh middles.
    # Off by default: paired A/B (24k games) measured it neutral-to-worse
    # (+30 to +75 points for the *old* policy, 4th% unchanged), so it is a
    # switch to revisit against a stronger field, not a shipped default.
    SOFT_DANGER = 0.0       # weight on danger from non-riichi opponents
    SOFT_WALL = 45          # wall_left at/below which every opponent counts
    SOFT_FOLD_SHANTEN = 2   # shanten at which soft threats are enough to fold
    SUJI_RESIDUAL = 0.0     # suji danger as a fraction of a fresh tile (0=free)

    # ---- speed, value, and where the leak actually is ----------------
    # We call 0.15/kyoku where the online field calls 0.41, win 17% of kyoku
    # where the field wins 24%, and are noten in 46% of exhaustive draws.
    # Shipped values come from bot 323 ("NO.24", rank 1): 0.47 calls/kyoku
    # against our 0.14, and 58 of its 76 calls at shanten 3-4 — it opens the
    # yaku early and races open (44% of its wins) instead of waiting for a
    # call that lowers shanten. Measured over 48,000 mirrored games in two
    # fields: points level (+6 ±17), average rank 0.020 better, 4th rate 0.5
    # points lower. Rank is what the arena grades on, so the trade is taken.
    CALL_SPEEDUP = 2        # min ukeire gain that justifies a call at equal shanten
    YAKUHAI_CALL_SHANTEN = 4  # pon a value honour at up to this shanten (0=off)
    NOTEN_SPRINT_WALL = 0   # at/below this wall_left, sprint for tenpai (0=off)
    SCORED_VALUE = False    # value the wait with the real scorer, not the table
    RICHI_MIN_VALUE = 0     # minimum points to declare riichi (0 = any tenpai)
    CANDIDATE_RISK = False  # fold cost from the cheapest discard, not the hand mean
    LONE_AUTHORITY_TURNS = 99  # rule 1 outranks tile efficiency for this many draws
    HARD_FOLD_SHANTEN = 3   # fold at this shanten against a riichi (see §5)
    LOSS_POINTS = 5200      # points a deal-in costs, before dealer doubling
    FOLD_EV = -1500         # what a clean fold is worth; push must beat it
    PUSH_WHEN_LAST = True   # from 4th place late in the hand, push harder…
    DESPERATE_GAP = 12000   # …but only when 3rd is this far ahead (a mangan
                            # will not save the placement, folding cannot either)

    # ---- defence -----------------------------------------------------

    @staticmethod
    def _visible(view, t):
        """Copies of t visible to us: all discards, all melds, our own hand."""
        n = view.counts[t]
        for d in view.discards:
            n += d.count(t)
        for melds in view.melds_all:
            for ts, _ in melds:
                n += ts.count(t)
        return n

    @classmethod
    def _safe_against(cls, view, t, threats):
        """True when t cannot be a ron for any threatening seat."""
        danger_free = True
        for s in threats:
            disc = view.discards[s]
            if t in disc:                 # genbutsu — 100% safe
                continue
            if t < 27:
                base = t - t % 9
                n = t % 9
                suji = False
                for d in (-3, 3):         # 1-4-7 / 2-5-8 / 3-6-9
                    if 0 <= n + d <= 8 and (base + n + d) in disc:
                        suji = True
                        break
                if suji:
                    continue
            else:
                # a lone honour can only be waited on as a pair, so once
                # two copies are visible *outside our hand* the wait is thin
                if cls._visible(view, t) - view.counts[t] >= 2:
                    continue
            danger_free = False
        return danger_free

    @classmethod
    def _is_suji(cls, view, t, threat):
        """True when 1-4-7 / 2-5-8 / 3-6-9 makes t only a two-sided trap."""
        if t >= 27:
            return False
        disc = view.discards[threat]
        n = t % 9
        base = t - n
        for d in (-3, 3):
            if 0 <= n + d <= 8 and (base + n + d) in disc:
                return True
        return False

    @classmethod
    def _danger(cls, view, t, threats):
        """Bigger = more dangerous. Used only to order risky discards.

        Per threat, because "safe" is per threat: a tile in one opponent's
        pond is still live against the other two. Suji used to count as free
        (danger 0); in reality a suji middle is roughly a quarter as dangerous
        as a fresh one, so SUJI_RESIDUAL scales it instead of zeroing it.
        """
        if not threats:
            return 0
        visible = cls._visible(view, t)
        if visible >= 4:                  # walled: nobody can hold a pair
            return 0
        score = 100
        n = t % 9
        if t >= 27:
            score = 45 if t in DRAGONS else 40      # pair wait only
        elif n in (0, 8):
            score = 55
        elif n in (1, 7):
            score = 70
        elif n in (2, 6):
            score = 85
        if visible >= 3:                  # thin wait -> safer
            score -= 25
        total = 0.0
        for s in threats:
            if t in view.discards[s]:     # genbutsu: cannot be a ron here
                continue
            if t >= 27 and visible - view.counts[t] >= 2:
                continue                  # pair wait with the copies gone
            d = score + cls._pond_read(view, t, s)
            if cls.SUJI_RESIDUAL > 0 and cls._is_suji(view, t, s):
                d *= cls.SUJI_RESIDUAL
            total += d
        return max(0, int(total / len(threats)))

    @classmethod
    def _soft_threats(cls, view):
        """Opponents who can ron without riichi: open hands, and late in the
        hand anyone at all — a dama tenpai looks exactly like a normal hand."""
        if cls.SOFT_DANGER <= 0:
            return []
        out = []
        for s in range(4):
            if s == view.seat or view.riichi[s]:
                continue
            if view.melds_all[s] or view.wall_left <= cls.SOFT_WALL:
                out.append(s)
        return out

    def _threat_danger(self, view, t, threats, soft=()):
        """Danger of t, riichi threats at full weight, the rest discounted."""
        d = self._danger(view, t, threats) * self.DANGER_WEIGHT
        if soft and self.SOFT_DANGER:
            d += self._danger(view, t, soft) * self.SOFT_DANGER
        return d

    @classmethod
    def _pond_read(cls, view, t, threat):
        """Danger adjustment from one opponent's discard order (hand reading).

        Cheap, but it is the part suji cannot see:
          * they have been cutting this suit heavily -> less likely collecting it
          * a late discard two steps away in the same suit (matagi-suji) makes
            the tiles inside it more dangerous
          * an early 5 in the suit (ura-suji off a 5) makes the 1-4 and 6-9
            neighbourhoods riskier
        """
        pond = view.discards[threat]
        if not pond or t >= 27:
            return 0
        suit = t // 9
        n = t % 9
        adj = 0
        same_suit = [x for x in pond if x < 27 and x // 9 == suit]
        if len(same_suit) >= 4:
            adj -= 20                      # not collecting that suit
        for x in pond[8:]:                 # late discards
            if x < 27 and x // 9 == suit and 1 <= abs(x % 9 - n) <= 2:
                adj += 12
        if any(x == suit * 9 + 4 for x in pond[:6]):   # early 5
            adj += 8
        return adj

    def _scored_value(self, view, total) -> int:
        """Points of the actual wait, scored by the engine's real scorer.

        The table in `_hand_value` cannot see pinfu, iipeikou or the wait
        itself, so a ryanmen pinfu and a kanchan tanki of the same "han
        estimate" were valued identically. Only tenpai hands can be scored
        exactly, which is precisely where push/fold is decided.
        """
        from mahjong_mc.scoring import score_hand
        dora = getattr(view, "dora_count", 0) or 0
        best = 0
        # `total` holds 14 tiles (we have just drawn), so every candidate is
        # discard-then-score: only the discards that leave tenpai can be
        # valued exactly, and those are the ones push/fold turns on.
        for d in set(view.hand):
            c13 = list(total)
            c13[d] -= 1
            if shanten(c13) != 0:
                continue
            tiles, _ = ukeire(c13, view.unseen_counts())
            for t in tiles:
                c14 = list(c13)
                c14[t] += 1
                # a closed hand counts as if we riichi, as the heuristic does
                res = score_hand(c14, list(view.melds), t, tsumo=False,
                                 dealer=view.dealer, seat=view.seat,
                                 dora=dora, riichi=not view.melds)
                if not res:
                    continue
                pts = (res["ron_oya"] if view.seat == view.dealer
                       else res["ron_ko"])
                best = max(best, pts)
        return best

    def _hand_value(self, view, total) -> int:
        """Rough points if this hand is won. Riichi only counts when closed:
        an open hand must earn its han from yaku (yakuhai, tanyao, honitsu)."""
        if self.SCORED_VALUE:
            scored = self._scored_value(view, total)
            if scored:
                return scored
        han = 0.0 if view.melds else 1.0              # riichi
        han += getattr(view, "dora_count", 0) or 0
        if not any(t >= 27 or (t % 9) in (0, 8) for t in range(34) if total[t]):
            han += 1                                 # tanyao potential
        yakuhai = list(DRAGONS) + [WINDS[_seat_wind(view.seat, view.dealer)], 27]
        han += sum(1.0 if total[t] >= 3 else 0.5
                   for t in yakuhai if total[t] >= 2)
        table = [(1, 1000), (2, 2000), (3, 3900), (4, 7700), (5, 8000),
                 (6, 12000), (8, 16000)]
        pts = 1000
        for need, val in table:
            if han >= need:
                pts = val
        return pts

    def _avg_danger(self, view, total, threats):
        """Mean danger (0..1-ish) of the tiles we would have to discard."""
        if not threats:
            return 0.0
        vals = [self._danger(view, t, threats)
                for t in set(view.hand)]
        return (sum(vals) / len(vals) / 100.0) if vals else 0.0

    def _risk(self, view, total, threats):
        """What pushing actually costs: the tile we would throw, not the mean.

        Averaging over the whole hand charges a hand holding one dangerous
        tile as if every tile were dangerous, so it folded hands that had a
        genbutsu to spare.
        """
        if self.CANDIDATE_RISK and threats:
            vals = [self._danger(view, t, threats) for t in set(view.hand)]
            if vals:
                return min(vals) / 100.0
        return self._avg_danger(view, total, threats)

    def _push_ev(self, view, total, threats, sh):
        """Expected points of pushing, versus the ~-1500 of a fold.

        Folding is not free: at an exhaustive draw the noten player pays, and
        standard analysis puts the cost of a clean fold at roughly -1,500 to
        -2,000 points. So the question is never "is pushing risky" but "is
        pushing worth more than -1500".
        """
        _, copies = ukeire(total, view.unseen_counts())
        if sh == 0:
            # a tenpai wins roughly 5% per live winning tile by the end of the
            # hand: ryanmen (8 copies) ~40%, kanchan (4) ~20%, tanki (1) ~5%
            p_win = min(0.85, copies * 0.05)
        elif sh == 1:
            p_win = min(0.40, copies * 0.018)
        else:
            p_win = 0.02
        value = self._hand_value(view, total)
        risk = self._risk(view, total, threats)
        p_loss = min(0.55, risk * (0.10 if sh == 0 else 0.16 if sh == 1 else 0.22))
        loss = self.LOSS_POINTS * (1.5 if view.dealer == view.seat else 1.0)
        noten = 0.0 if sh == 0 else 1500.0
        return p_win * value - p_loss * loss - noten

    def _score_pressure(self, view):
        """+1 = push harder, -1 = protect the lead, from the score situation.

        Only meaningful in a hanchan (online): every kyoku of a local Monte
        Carlo game starts level, so this returns 0 there.
        """
        pts = view.points
        mine = pts[view.seat]
        if len(set(pts)) == 1:
            return 0
        place = 1 + sum(1 for p in pts if p > mine)
        if place == 4 and view.wall_left < 35:
            # Desperation only when defence cannot save the placement. The old
            # rule pushed unconditionally from 4th; in the 100 logged games
            # 51% of our deal-ins happened in 4th place against 30% of our
            # discards, so it was buying deal-ins without buying rank.
            third = sorted(pts, reverse=True)[2]
            if self.PUSH_WHEN_LAST and third - mine >= self.DESPERATE_GAP:
                return 1
            return 0
        if place <= 2 and mine - min(pts) > 8000:
            return -1                      # protect the lead
        return 0

    def _should_fold(self, view, total, threats, sh):
        """Fold DEAD hands only.

        The old version folded every hand that was not tenpai, and against a
        strong field somebody is in riichi most of the time, so it folded
        almost every hand: 5.5% wins, 64.8% fourth. Folding without winning
        does not defend a placement, it hands one away.
        """
        if not threats:
            return False
        pressure = self._score_pressure(view)
        fold_ev = float(self.FOLD_EV)
        if pressure > 0:
            fold_ev -= 700.0               # in last place a fold costs more
        elif pressure < 0:
            fold_ev += 700.0               # protecting a lead is worth more
        push_ev = self._push_ev(view, total, threats, sh)
        if sh >= self.HARD_FOLD_SHANTEN:
            return True                    # too far to be worth a dangerous tile
        return push_ev < fold_ev

    # ---- main decision ------------------------------------------------

    def choose_discard(self, view):
        total = view.total_counts
        unseen = view.unseen_counts()
        seat, dealer = view.seat, view.dealer
        dora = {dora_next(i) for i in getattr(view, "dora_indicators", ())}

        # deal-level commitment to thirteen orphans (rule 8)
        if view.turn <= 1 and not view.melds:
            distinct_yao = sum(1 for t in YAO if total[t] > 0)
            self.kokushi = distinct_yao >= 10
        if getattr(self, "kokushi", False) and kokushi_shanten(total) > 3:
            self.kokushi = False

        pairs = sum(1 for c in total if c >= 2)
        force_seven = pairs >= 4          # rule 5: four pairs -> seven pairs

        threats = [s for s in range(4) if s != seat and view.riichi[s]]
        soft = self._soft_threats(view)
        best_sh = 8
        pool = []
        for t in sorted(set(view.hand)):
            c = list(total)
            c[t] -= 1
            if getattr(self, "kokushi", False):
                s = kokushi_shanten(c)
            else:
                s = shanten(c)
                if force_seven:           # keep the seven-pairs route alive
                    s = min(s, seven_pairs_shanten(c))
            if s < best_sh:
                best_sh, pool = s, [(s, t, c)]
            elif s == best_sh:
                pool.append((s, t, c))

        tenpai = best_sh == 0
        folding = self._should_fold(view, total, threats, best_sh)  # rule 6
        if (not folding and soft and not threats and not tenpai
                and best_sh >= self.SOFT_FOLD_SHANTEN
                and view.wall_left <= self.SOFT_WALL):
            # nobody in riichi, but the hand is late and far away: a live
            # middle is not worth a deal-in to a hand we cannot see
            folding = True

        if (self.NOTEN_SPRINT_WALL and not tenpai and not threats
                and best_sh <= 1 and view.wall_left <= self.NOTEN_SPRINT_WALL):
            # A noten draw is a guaranteed 1,000-3,000; a 1-shanten hand that
            # converts in one draw keeps it. With nobody in riichi there is
            # nothing to run from, so take the tenpai.
            def sprint_key(x):
                avail = list(unseen)
                avail[x[1]] = max(0, avail[x[1]] - 1)
                _, copies = ukeire(x[2], avail)
                return (8 * copies + _shape_score(x[2]) * 3, self.rng.random())
            return max(pool, key=sprint_key)[1]

        if folding:
            # betaori: safety first, hand shape ignored. Among equally safe
            # tiles prefer one from a *pair* that is already safe — its twin
            # is a guaranteed safe discard next turn (mawashiuchi).
            everyone = threats + soft

            def fold_key(x):
                t = x[1]
                danger = self._threat_danger(view, t, threats, soft)
                safe_twin = 1
                if danger == 0 and total[t] >= 2:
                    twin = list(total)
                    twin[t] -= 1
                    if self._safe_against(view, t, everyone):
                        safe_twin = 0
                return (danger, safe_twin, -self._visible(view, t),
                        self.rng.random())
            return min(pool, key=fold_key)[1]

        # ---- rule 1 is authoritative: if a lone tile can go, the lonest goes
        # first in *your* order, and that beats tile efficiency. Dora is kept
        # (rule 3) by pushing dora loners to the back of the queue.
        if getattr(self, "kokushi", False):
            # kokushi: keep every terminal/honour, shed the suit tiles
            return min(pool, key=lambda x: (
                x[0],
                0 if x[1] not in YAO else 1,
                self.rng.random(),
            ))[1]

        lone_pool = ([x for x in pool if _is_lone(total, x[1])]
                     if view.turn <= self.LONE_AUTHORITY_TURNS else [])
        if lone_pool:
            return min(lone_pool, key=lambda x: (
                _lone_rank(total, x[1], seat, dealer, turn=view.turn,
                           seen=self._visible(view, x[1]) - total[x[1]]),
                1 if x[1] in dora else 0,
                self._threat_danger(view, x[1], threats, soft),
                self.rng.random(),
            ))[1]

        # ---- no lone tiles left: rule 2 (shape) decides, then acceptance
        block_count = _block_count(total)
        best_key = None
        best_tile = None
        for s, t, c in pool:
            avail = list(unseen)
            avail[t] = max(0, avail[t] - 1)
            _, copies = ukeire(c, avail)
            sec = _shape_score(c) * 3
            dora_pen = 30 * (1 if t in dora else 0) + 12 * (total[t] - 1 if t in dora else 0)
            danger = 0
            if (threats or soft) and not tenpai:
                danger = self._threat_danger(view, t, threats, soft)
            # five-block theory: with too many blocks, cut the weakest one
            weak = (_growth(total, t) * 6
                    if block_count >= 6 and self.BLOCK_CUT else 0)
            key = (8 * copies + sec - dora_pen - danger - weak,
                   self.rng.random())
            if best_key is None or key > best_key:
                best_key, best_tile = key, t
        return best_tile

    # ---- calls / riichi / kan ----------------------------------------

    def _open_yaku_ok(self, view, tile, trio):
        """Will the hand still have a yaku after opening? An open no-yaku hand
        is a dead hand, so every call is gated on this."""
        if tile in DRAGONS or tile in (27, WINDS[_seat_wind(view.seat,
                                                            view.dealer)]):
            return True                        # yakuhai triplet is the yaku
        tiles = [t for t in range(34) for _ in range(view.total_counts[t])]
        every = tiles + [tile] + list(trio)
        if all(t < 27 and (t % 9) in (1, 2, 3, 4, 5, 6, 7) for t in every):
            return True                        # tanyao
        suits = {t // 9 for t in every if t < 27}
        if len(suits) <= 1:
            return True                        # honitsu / chinitsu route
        return False

    def decide_call(self, view, tile, options):
        total = view.total_counts
        s0 = shanten(total)
        yakuhai = tile in DRAGONS or tile in (WINDS[_seat_wind(view.seat,
                                                               view.dealer)],
                                             27)
        # A pon of a value honour is the yaku itself: it is worth taking even
        # when the hand is still three away, which is how the field reaches
        # tenpai so much earlier than we did (0.41 calls/kyoku vs our 0.15).
        limit = self.CALL_MAX_SHANTEN
        if yakuhai and self.YAKUHAI_CALL_SHANTEN > limit:
            limit = self.YAKUHAI_CALL_SHANTEN
        if s0 > limit:
            return None
        for act in options:
            kind, trio = act[0], act[1]
            if kind == "shouminkan":
                continue                      # invites chankan
            if kind == "minkan" and not yakuhai:
                continue                      # keep concealment unless value
            if not self._open_yaku_ok(view, tile, trio):
                continue                      # no yaku once open -> dead hand
            consumed = list(trio)
            consumed.remove(tile)
            held = {}
            for x in view.hand:
                held[x] = held.get(x, 0) + 1
            ok = True
            for x in consumed:
                held[x] = held.get(x, 0) - 1
                if held[x] < 0:            # added kan / tile not actually held
                    ok = False
            if not ok:
                continue
            c = list(total)
            c[tile] += 1
            best = None
            for x, n in held.items():
                if n <= 0:
                    continue
                c[x] -= 1
                s = shanten(c)
                c[x] += 1
                if s < s0 and (best is None or s < best):
                    best = s
            if best is not None:
                return act
            if self.CALL_SPEEDUP and best == s0:
                # same shanten, but the call opens a much wider path to it
                base = ukeire(total, view.unseen_counts())[1]
                c2 = list(total)
                c2[tile] += 1
                for x in consumed:
                    c2[x] -= 1
                for x in set(c2):
                    if c2[x] <= 0:
                        continue
                    c2[x] -= 1
                    gain = ukeire(c2, view.unseen_counts())[1]
                    c2[x] += 1
                    if gain >= base + self.CALL_SPEEDUP:
                        return act
        return None

    def decide_riichi(self, view):
        if not view.can_riichi or getattr(self, "kokushi", False):
            return False
        total = view.total_counts
        if shanten(total) != 0:
            return False
        if view.wall_left < 10:               # too late to matter
            return False
        threats = [s for s in range(4) if s != view.seat and view.riichi[s]]
        _, copies = ukeire(total, view.unseen_counts())
        if len(threats) >= 2:
            return False                      # too dangerous
        if threats:
            return copies >= 6                # only push a wide wait
        # no riichi but late and narrow: a bad wait late wins ~33%, damaten
        # keeps the option to fold when someone else declares
        if view.turn >= 10 and copies < 4:
            return False
        # riichi locks the hand: a 1-han tanki is not worth losing the ability
        # to fold, and the table below cannot see the wait. 28 of 195 logged
        # deal-ins happened in kyoku where we had already declared.
        if self.RICHI_MIN_VALUE and self._hand_value(view, total) < self.RICHI_MIN_VALUE:
            return False
        return True

    def decide_kan(self, view, tile, options):
        total = view.total_counts
        dora = {dora_next(i) for i in getattr(view, "dora_indicators", ())}
        for act in options:
            kind = act[0]
            if kind == "shouminkan":
                continue                      # added kan invites chankan
            if kind == "ankan" and (tile in dora or shanten(total) >= 2):
                return act
        return None


# ------------------------------------------------------------------ tuning
# examples/evolve_louis.py writes the winning weights here; the policy picks
# them up on import, so a tuned bot needs no code change.
_PARAMS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "louis_params.json")
if os.path.exists(_PARAMS_PATH):
    try:
        with open(_PARAMS_PATH, encoding="utf-8") as _f:
            for _k, _v in json.load(_f).items():
                if hasattr(LouisPolicy, _k):
                    setattr(LouisPolicy, _k, _v)
    except (OSError, ValueError):
        pass
