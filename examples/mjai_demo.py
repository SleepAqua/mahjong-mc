"""Local demo: watch an mjai-bot strategy play games in our own engine.

    python3 -m examples.mjai_demo --games 200 --policy gto --field greedy,defensive,random

The bot (any my_strategies/ policy) sits at seat 0 driven through the mjai
event protocol; the three opponents are ordinary engine policies. State is
translated engine->mjai on every view call, so this exercises the real
adapter path (MjaiBot) without any server. Results are printed as the same
win%/pts table as the Monte Carlo runner.

Approximations (documented): dora indicators are not visible through the
engine View, so the bot's dora count reads 0 — none of the shipped policies
read dora_count, so decisions are unaffected.
"""

from __future__ import annotations

import argparse

from mahjong_mc.engine import Game, Rules
from mahjong_mc.mc import load_policy_dir, print_table
from mahjong_mc.mjai import MjaiBot, id_to_mjai, mjai_to_id
from mahjong_mc.policies import make_policy
from mahjong_mc.rules import shanten

import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_policy_dir(os.path.join(_PROJECT_ROOT, "my_strategies"))

NO_DORA = "5m"  # placeholder marker; see module docstring


class BridgePolicy:
    """Wraps MjaiBot behind the engine's Policy interface (seat 0)."""

    name = "bridge"

    def __init__(self, policy_name, seed=None):
        self.bot = MjaiBot(make_policy(policy_name, seed), 0)
        self.started = False
        self.stash = None          # bot response from the last sync
        self.pending_discard = None  # discard queued by a call response
        self.prev = None           # (counts, discards, melds, riichi) snapshot

    # ------------------------------------------------------------- sync

    def _snapshot(self, view):
        return (tuple(view.counts),                      # my hand counts
                tuple(tuple(d) for d in view.discards),  # all discards
                tuple(tuple(m) for m in view.melds_all),  # all melds
                tuple(view.riichi))

    def _sync(self, view):
        """Emit mjai events for everything that changed; stash the reply."""
        cur = self._snapshot(view)
        if not self.started:
            self.started = True
            self.prev = cur
            # the dealt 13 tiles; the 14th (if just drawn) comes as a tsumo
            dealt = list(view.hand)
            if view.last_drawn is not None and len(dealt) == 14:
                dealt.remove(view.last_drawn)
            tehais = [id_to_mjai(t) for t in dealt]
            self.bot.on_event({
                "type": "start_game", "id": 0,
                "names": ["bot"] * 4})
            self.bot.on_event({
                "type": "start_kyoku", "bakaze": "E",
                "dora_marker": NO_DORA, "kyoku": 1, "honba": 0,
                "kyotaku": 0, "oya": view.dealer,
                "scores": list(view.points),
                # live mjai only reveals the POV's hand
                "tehais": [tehais, [], [], []]})
            if view.last_drawn is not None:
                acts = self.bot.on_event(
                    {"type": "tsumo", "actor": 0,
                     "pai": id_to_mjai(view.last_drawn)})
                self.stash = acts
            return
        pc, pd, pm, pr = self.prev
        cc, cd, cm, cr = cur
        # other seats' new discards
        for seat in range(4):
            if seat == 0:
                continue
            for t in cd[seat][len(pd[seat]):]:
                acts = self.bot.on_event(
                    {"type": "dahai", "actor": seat,
                     "pai": id_to_mjai(t)})
                self.stash = acts
        # other seats' new melds (chi/pon/kan) — approximate reconstruction
        for seat in range(4):
            if seat == 0:
                continue
            for m in cm[seat][len(pm[seat]):]:
                ts, kind = m
                t = ts[0]
                if kind == "chi":
                    consumed = [x for x in ts if x != t]
                    ev = {"type": "chi", "actor": seat, "target": 3,
                          "pai": id_to_mjai(t),
                          "consumed": [id_to_mjai(x) for x in consumed]}
                elif kind == "peng":
                    ev = {"type": "pon", "actor": seat, "target": 3,
                          "pai": id_to_mjai(t),
                          "consumed": [id_to_mjai(t)] * 2}
                else:
                    ev = {"type": "kan", "actor": seat,
                          "pai": id_to_mjai(t),
                          "consumed": [id_to_mjai(t)] * 3}
                self.bot.on_event(ev)
        # new riichi declarations
        for seat in range(4):
            if cr[seat] and not pr[seat]:
                self.bot.on_event({"type": "reach", "actor": seat})
        # reconcile my hand against the bot's state — the engine's view is
        # ground truth. (A pure grew-vs-prev check misses draws when the
        # engine never asked decide_call between two of my turns: the bot
        # would never learn it drew and would fall back to a wrong discard.)
        bot_c = self.bot.counts[0]
        for t in range(34):
            for _ in range(bot_c[t] - cc[t]):
                # the engine discarded a tile the bot still holds
                self.bot.on_event({"type": "dahai", "actor": 0,
                                   "pai": id_to_mjai(t)})
        for t in range(34):
            for _ in range(cc[t] - bot_c[t]):
                # the engine drew a tile the bot never saw
                acts = self.bot.on_event(
                    {"type": "tsumo", "actor": 0, "pai": id_to_mjai(t)})
                self.stash = acts
        self.prev = cur

    # --------------------------------------------------------- policies

    def choose_discard(self, view):
        self._sync(view)
        if self.pending_discard is not None:
            t = self.pending_discard
            self.pending_discard = None
            return t
        for act in (self.stash or []):
            if act.get("type") == "dahai":
                self.stash = None
                return mjai_to_id(act["pai"])
        # fallback: discard the first tile (should not happen)
        return view.hand[0]

    def decide_riichi(self, view):
        self._sync(view)
        return bool(self.stash and self.stash[0].get("type") == "reach")

    def decide_call(self, view, tile, options):
        self._sync(view)
        stash = self.stash or []
        self.stash = None
        for act in stash:
            if act.get("type") in ("peng", "chi", "kan"):
                # a call response also carries the follow-up discard; keep
                # it queued so the engine's next discard matches the bot's
                for follow in stash:
                    if follow.get("type") == "dahai":
                        self.pending_discard = mjai_to_id(follow["pai"])
                        break
                return self._to_engine_action(act)
        return None

    def decide_kan(self, view, tile, options):
        self._sync(view)
        for act in (self.stash or []):
            if act.get("type") == "kan":
                self.stash = None
                return self._to_engine_action(act)
        return None

    @staticmethod
    def _to_engine_action(act):
        """Translate an mjai kan/pon/chi action to engine option format."""
        t = mjai_to_id(act["pai"])
        consumed = [mjai_to_id(x) for x in act.get("consumed", [])]
        if act["type"] == "pon":
            return ("peng", (t, t, t), "peng")
        if act["type"] == "chi":
            trio = tuple(sorted([t] + consumed))
            return ("chi", trio, "chi")
        # kan
        if len(consumed) == 1:
            return ("shouminkan", (t, t, t, t), "shouminkan")
        if "target" in act:
            return ("minkan", (t, t, t, t), "minkan")
        return ("ankan", (t, t, t, t), "ankan")


def run_demo(games, policy_name, field, seed=0):
    opponents = [make_policy(n, seed * 1000 + i)
                 for i, n in enumerate(field)]
    rows = []
    n_wins = n_tumo = n_ron = n_dealt = 0
    points_total = 0
    for k in range(games):
        gseed = seed * 1_000_003 + k
        bridge = BridgePolicy(policy_name, gseed)
        game = Game([bridge] + opponents, rules=Rules(), seed=gseed,
                    dealer=gseed % 4)
        game.run()
        res = game.result()
        pts = res["points"][0] - 25000
        points_total += pts
        if res["winner"] == 0:
            n_wins += 1
            n_dealt += 1 if res["kind"] == "ron" else 0
            if res["kind"] == "tumo":
                n_tumo += 1
            else:
                n_ron += 1
        if res["loser"] == 0:
            n_dealt += 1
    rows.append({
        "seat": 0, "policy": f"{policy_name} (mjai bot)", "games": games,
        "wins": n_wins, "win_rate": n_wins / games,
        "tumo": n_tumo, "ron": n_ron, "dealt_in": n_dealt,
        "deal_in_rate": n_dealt / games, "riichi": 0, "riichi_rate": 0.0,
        "draws": 0, "draw_rate": 0.0,
        "avg_points": points_total / games, "avg_rank": 0.0,
    })
    return {"rows": rows, "games": games, "seed": seed,
            "elapsed_s": 0.0, "games_per_s": 0.0}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="mjai-demo",
        description="Play an mjai-bot strategy against engine policies "
                    "locally (no server)")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--policy", default="gto",
                    help="policy name for the bot (any my_strategies/ name)")
    ap.add_argument("--field", default="greedy,defensive,random",
                    help="3 comma-separated opponent policy names")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    field = [s.strip() for s in args.field.split(",") if s.strip()]
    if len(field) != 3:
        ap.error("--field needs exactly 3 policy names")
    stats = run_demo(args.games, args.policy, field, seed=args.seed)
    print(f"mjai bot demo: {args.policy} vs {field} "
          f"({args.games} games, seed {args.seed})")
    print_table(stats)


if __name__ == "__main__":
    main()
