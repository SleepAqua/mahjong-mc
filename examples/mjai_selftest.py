"""Self-test for the mjai adapter: scripted kyoku events in, valid actions out.

    python3 -m examples.mjai_selftest

Feeds a hand-crafted kyoku through MjaiBot and asserts the bot answers
correctly at every decision point (valid discard after its tsumo, ron when
tenpai with a yaku, none when nothing to call, reach when the policy wants
it) without needing Tenhou or any server.
"""

from __future__ import annotations

import io
import os
import json

from mahjong_mc.mjai import MjaiBot, id_to_mjai, mjai_to_id
from mahjong_mc.mc import load_policy_dir
from mahjong_mc.policies import make_policy
from mahjong_mc import tiles

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_policy_dir(os.path.join(_PROJECT_ROOT, "my_strategies"))


def hand_to_tehai(tile_ids):
    return [id_to_mjai(t) for t in tile_ids]


# my (seat 0) hand: 234m 456m 789p 22s 33s — tenpai on 2s/3s, tanyao yaku
MY_HAND = [1, 2, 3, 4, 5, 6, 15, 16, 17, 19, 19, 20, 20]
# sanity: 13 tiles
assert len(MY_HAND) == 13

# arbitrary 13-tile hands for seats 1-3 (tile ids)
OTHERS = {
    1: [0, 0, 0, 3, 4, 5, 12, 13, 14, 15, 16, 17, 22],   # 111m 234p 567p 1s
    2: [1, 1, 1, 6, 7, 8, 15, 16, 17, 18, 18, 20, 20],   # 222m 345p 678p 2s 3s
    3: [2, 2, 2, 9, 10, 11, 19, 20, 21, 22, 22, 23, 23], # 333m 456p 789p 4s
}


def seat_tehais():
    tehais = [hand_to_tehai(MY_HAND)]
    for seat in (1, 2, 3):
        tehais.append(hand_to_tehai(OTHERS[seat]))
    return tehais


def feed(bot, events):
    """Feed events; return the flattened list of actions the bot emitted."""
    actions = []
    for ev in events:
        actions.extend(bot.on_event(ev))
    return actions


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    return cond


def main():
    ok = True
    policy = make_policy("gto", seed=1)
    bot = MjaiBot(policy, 0)

    kyoku = {
        "type": "start_kyoku",
        "bakaze": "E", "dora_marker": "5m",
        "kyoku": 1, "honba": 0, "kyotaku": 0, "oya": 0,
        "scores": [25000] * 4,
        "tehais": seat_tehais(),
    }
    feed(bot, [{"type": "start_game", "id": 0, "names": ["me"] * 4}, kyoku])

    print("mjai bot self-test (policy=gto, seat 0)")

    # 1. my tsumo: expect reach + tsumu-giri (hand is tenpai, menzen)
    t = "1m"  # a tile that does not complete anything (fill from wall)
    acts = feed(bot, [{"type": "tsumo", "actor": 0, "pai": t}])
    kinds = [a["type"] for a in acts]
    ok &= check("tsumo -> reach then dahai", kinds == ["reach", "dahai"])
    ok &= check("reach discards the drawn tile (tsumu-giri)",
                acts[-1].get("tsumogiri") is True and acts[-1]["pai"] == t)

    # 2. opponent discards a tile I could win on but the hand lacks a yaku
    #    path -> must NOT claim (we replace 22s 33s waits by checking a
    #    non-winning tile): expect 'none'
    acts = feed(bot, [{"type": "dahai", "actor": 1, "pai": "9s"}])
    ok &= check("unrelated discard -> none",
                [a["type"] for a in acts] == ["none"])

    # 3. real ron test: reset, give seat 0 a tanyao tenpai, opponent feeds it
    bot2 = MjaiBot(make_policy("gto", seed=1), 0)
    feed(bot2, [{"type": "start_game", "id": 0, "names": ["me"] * 4},
                {"type": "start_kyoku", "bakaze": "E", "dora_marker": "5m",
                 "kyoku": 1, "honba": 0, "kyotaku": 0, "oya": 0,
                 "scores": [25000] * 4, "tehais": seat_tehais()}])
    # seat 0 draws and discards WITHOUT riichi this time (damaten path):
    # force by using a policy that never riichis
    from mahjong_mc.policies import ShantenPolicy

    class NoRiichi(ShantenPolicy):
        def decide_riichi(self, view):
            return False

    bot3 = MjaiBot(NoRiichi(seed=1), 0)
    feed(bot3, [{"type": "start_game", "id": 0, "names": ["me"] * 4},
                {"type": "start_kyoku", "bakaze": "E", "dora_marker": "5m",
                 "kyoku": 1, "honba": 0, "kyotaku": 0, "oya": 0,
                 "scores": [25000] * 4, "tehais": seat_tehais()}])
    acts = feed(bot3, [{"type": "tsumo", "actor": 0, "pai": "1m"}])
    ok &= check("no-riichi tsumo -> plain dahai",
                [a["type"] for a in acts] == ["dahai"])
    # now opponent discards 2s -> 234m 456m 789p 222s 33s, tanyao
    acts = feed(bot3, [{"type": "dahai", "actor": 1, "pai": "2s"}])
    ok &= check("tenpai tanyao ron on fed tile",
                [a["type"] for a in acts] == ["hora"]
                and acts[0].get("target") == 1 and acts[0]["pai"] == "2s")

    # 4. furiten: same ron tile already in our discards -> must pass
    bot4 = MjaiBot(NoRiichi(seed=1), 0)
    feed(bot4, [{"type": "start_game", "id": 0, "names": ["me"] * 4},
                {"type": "start_kyoku", "bakaze": "E", "dora_marker": "5m",
                 "kyoku": 1, "honba": 0, "kyotaku": 0, "oya": 0,
                 "scores": [25000] * 4, "tehais": seat_tehais()}])
    feed(bot4, [{"type": "tsumo", "actor": 0, "pai": "1m"}])  # discards 1m
    # make seat 0 discard a 2s so it becomes furiten, then feed 2s again
    feed(bot4, [{"type": "tsumo", "actor": 0, "pai": "2s"}])
    acts = feed(bot4, [{"type": "dahai", "actor": 1, "pai": "2s"}])
    ok &= check("furiten -> no hora", [a["type"] for a in acts] == ["none"])

    # 5. tile conversion round-trip
    ok &= check("tile conversion",
                all(mjai_to_id(id_to_mjai(t)) == t for t in range(34)))

    # 6. minkan mechanics: a policy that always kans must emit a proper kan
    #    action and then wait for the replacement draw
    from mahjong_mc.policies import ShantenPolicy

    class AlwaysKan(ShantenPolicy):
        def decide_riichi(self, view):
            return False

        def decide_call(self, view, tile, options):
            for act in options:
                if act[0] == "minkan":
                    return act
            return None

        def decide_kan(self, view, tile, options):
            return options[0] if options else None

    bot5 = MjaiBot(AlwaysKan(seed=1), 0)
    tehais = seat_tehais()
    tehais[0] = hand_to_tehai([4, 4, 4, 5, 6, 7, 13, 14, 15, 22, 22, 23, 23])
    feed(bot5, [{"type": "start_game", "id": 0, "names": ["me"] * 4},
                {"type": "start_kyoku", "bakaze": "E", "dora_marker": "5m",
                 "kyoku": 1, "honba": 0, "kyotaku": 0, "oya": 0,
                 "scores": [25000] * 4, "tehais": tehais}])
    acts = feed(bot5, [{"type": "dahai", "actor": 1, "pai": "5m"}])
    ok &= check("minkan emits kan with 3 consumed",
                len(acts) == 1 and acts[0]["type"] == "kan"
                and acts[0]["pai"] == "5m"
                and acts[0]["consumed"] == ["5m", "5m", "5m"]
                and acts[0]["target"] == 1)
    # after minkan the bot waits for the replacement tsumo, then discards
    acts = feed(bot5, [{"type": "tsumo", "actor": 0, "pai": "9m"}])
    ok &= check("post-minkan tsumo -> dahai",
                [a["type"] for a in acts] == ["dahai"])
    # ankan from own draw with the always-kan policy
    bot6 = MjaiBot(AlwaysKan(seed=1), 0)
    tehais2 = seat_tehais()
    tehais2[0] = hand_to_tehai([4, 4, 4, 5, 6, 7, 13, 14, 15, 22, 22, 23, 23])
    feed(bot6, [{"type": "start_game", "id": 0, "names": ["me"] * 4},
                {"type": "start_kyoku", "bakaze": "E", "dora_marker": "5m",
                 "kyoku": 1, "honba": 0, "kyotaku": 0, "oya": 0,
                 "scores": [25000] * 4, "tehais": tehais2}])
    acts = feed(bot6, [{"type": "tsumo", "actor": 0, "pai": "5m"}])
    ok &= check("ankan from draw emits kan",
                any(a["type"] == "kan" and a.get("target") is None
                    for a in acts))

    print("\n" + ("ALL PASS" if ok else "FAILURES PRESENT"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
