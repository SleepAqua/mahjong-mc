"""Japanese-standard scoring: yaku, han, fu and points.

Implements the common EMA-style ruleset:

    yaku:   riichi, ippatsu, menzen tsumo, pinfu, tanyao, yakuhai (dragons,
            winds), chanta/junchan, itsuu, sanshoku(doukou), sanankou,
            sankantsu, chiitoitsu, toitoi, honroutou, shousangen, honitsu,
            chinitsu, ryanpeikou, iipeikou, rinshan, chankan, haitei, houtei
    yakuman: chiiniisou, chinroutou, daisangen, shousuushii, suuankou,
            suukantsu, kokushi musou (kazoe yakuman at 13+ han)
    fu:     base 20 (chiitoitsu 25), +10 menzen ron, +10 tsumo (non-pinfu),
            wait/meld/pair bonuses, rounded up to 10
    points: fu * 2^(2+han) with mangan/haneman/baiman/sanbaiman/yakuman caps;
            dealer pays/receives 1.5x; honba handled by the engine

Not implemented (documented): red fives, nagashi mangan, renhou, pao,
double yakuman, chuuren/ryuuiisou, south rounds.
"""

from __future__ import annotations

from .tiles import NUM_TILE_TYPES

YAOCHUU = frozenset({0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33})
TERMINALS = frozenset({0, 8, 9, 17, 18, 26})
DRAGONS = (31, 32, 33)
WINDS = (27, 28, 29, 30)

# meld kinds
CONCEALED = "concealed"  # run/triplet from the closed hand
ANKAN = "ankan"
MINKAN = "minkan"
SHOUMINKAN = "shouminkan"


def is_yaochuu(t: int) -> bool:
    return t in YAOCHUU


def is_terminal(t: int) -> bool:
    return t in TERMINALS


def dora_next(t: int) -> int:
    if t < 27:
        return t - t % 9 + (t + 1) % 9
    if t < 31:
        return 27 + (t - 27 + 1) % 4
    return 31 + (t - 31 + 1) % 3


def count_dora(counts, called_melds, indicators) -> int:
    """Dora tiles held, given indicator tiles."""
    targets = {dora_next(t) for t in indicators}
    total = sum(counts[t] for t in targets)
    for ts, _ in called_melds:
        total += sum(1 for x in ts if x in targets)
    return total


def _decompositions(counts, n_melds=4):
    """Yield (concealed_melds, pair) — melds are (tiles, CONCEALED).

    `n_melds` is how many melds the CONCEALED part must still supply
    (4 minus the number of already-called melds).
    """
    c = list(counts)

    def rec(rest, melds_out, pair):
        i = 0
        while i < NUM_TILE_TYPES and rest[i] == 0:
            i += 1
        if i == NUM_TILE_TYPES:
            if pair is not None and len(melds_out) == n_melds:
                yield tuple(melds_out), pair
            return
        n = rest[i]
        if n >= 3:  # triplet
            rest[i] -= 3
            yield from rec(rest, melds_out + [((i, i, i), CONCEALED)], pair)
            rest[i] += 3
        if i < 27 and i % 9 <= 6 and rest[i + 1] >= 1 and rest[i + 2] >= 1:
            rest[i] -= 1
            rest[i + 1] -= 1
            rest[i + 2] -= 1
            yield from rec(
                rest, melds_out + [((i, i + 1, i + 2), CONCEALED)], pair)
            rest[i] += 1
            rest[i + 1] += 1
            rest[i + 2] += 1
        if pair is None and n >= 2:
            rest[i] -= 2
            yield from rec(rest, melds_out, i)
            rest[i] += 2

    yield from rec(c, [], None)


def _seven_pairs(counts) -> bool:
    return sum(counts) == 14 and all(n in (0, 2) for n in counts)


def _kokushi(counts) -> bool:
    """All 13 terminal/honour types plus exactly one duplicate."""
    if sum(counts) != 14:
        return False
    if any(counts[t] == 0 for t in YAOCHUU):
        return False
    if any(counts[t] for t in range(NUM_TILE_TYPES) if t not in YAOCHUU):
        return False
    return sum(1 for t in YAOCHUU if counts[t] == 2) == 1


def _wait_type(decomp_melds, win_tile):
    """'ryanmen' | 'kanchan' | 'penchan' | 'tanki' | 'shanpon'."""
    for tiles, kind in decomp_melds:
        if kind == CONCEALED and win_tile in tiles:
            lo, hi = tiles[0], tiles[-1]
            if hi - lo == 2:  # run
                if win_tile == lo:
                    return "penchan" if lo % 9 == 0 else "ryanmen"
                if win_tile == hi:
                    return "penchan" if hi % 9 == 8 else "ryanmen"
                return "kanchan"
            return "shanpon"  # triplet
    return "tanki"


# ------------------------------------------------------------------ yaku

def _yaku_of(counts, decomp_melds, called_melds, pair, win_tile, tsumo,
             seat_wind, prevalent_wind, riichi, ippatsu, dora, ura,
             rinshan, chankan, haitei, houtei):
    """(han, yakuman_count, yaku names) for one decomposition."""
    yaku = []
    yakuman = 0
    han = 0
    # ankan keeps the hand menzen (it is a concealed kan)
    menzen = not any(k in ("chi", "peng", MINKAN, SHOUMINKAN)
                     for _, k in called_melds)
    all_melds = list(decomp_melds) + list(called_melds)

    full = list(counts)
    for ts, _ in called_melds:
        for x in ts:
            full[x] += 1
    present = [t for t in range(34) if full[t]]

    # situational
    if riichi:
        han += 1
        yaku.append("riichi")
    if ippatsu and riichi:
        han += 1
        yaku.append("ippatsu")
    if menzen and tsumo:
        han += 1
        yaku.append("menzen tsumo")
    if rinshan:
        han += 1
        yaku.append("rinshan")
    if chankan:
        han += 1
        yaku.append("chankan")
    if haitei and tsumo:
        han += 1
        yaku.append("haitei")
    if houtei and not tsumo:
        han += 1
        yaku.append("houtei")

    # structure
    has_yaochuu = any(is_yaochuu(t) for t in present)
    has_terminal = any(is_terminal(t) for t in present)
    suits = {t // 9 for t in present if t < 27}
    honors_present = any(t >= 27 for t in present)

    if not has_yaochuu:
        han += 1
        yaku.append("tanyao")

    for d in DRAGONS:
        if full[d] >= 3:
            han += 1
            yaku.append("yakuhai(dragon)")
    for w in WINDS:
        if full[w] >= 3 and (w == prevalent_wind or w == seat_wind):
            han += 1
            yaku.append("yakuhai(wind)")

    wait = _wait_type(decomp_melds, win_tile)
    all_runs = all(ts[-1] - ts[0] == 2 for ts, _ in all_melds)
    if (menzen and wait == "ryanmen" and tsumo and all_runs
            and not is_yaochuu(pair)):
        han += 1
        yaku.append("pinfu")

    runs = [ts for ts, k in all_melds if ts[-1] - ts[0] == 2]
    triplets = [ts for ts, k in all_melds
                if ts[0] == ts[1] == ts[2] and len(ts) == 3]
    kans = [ts for ts, k in all_melds if len(ts) == 4]
    concealed_triplets = [ts for ts, k in all_melds
                          if ts[0] == ts[1] == ts[2] and len(ts) == 3
                          and k in (CONCEALED, ANKAN)]

    # itsuu
    for suit in range(3):
        base = suit * 9
        if all(any(tuple(r) == (base + i, base + i + 1, base + i + 2)
                   for r in runs) for i in (0, 3, 6)):
            han += 2 if menzen else 1
            yaku.append("itsuu")
            break

    # sanshoku doukou
    triplet_shapes = {}
    for ts in triplets:
        triplet_shapes.setdefault(ts[0] % 9, set()).add(ts[0] // 9)
    if any(len(v) == 3 for v in triplet_shapes.values()):
        han += 2
        yaku.append("sanshoku doukou")

    # sanshoku
    run_shapes = {}
    for ts in runs:
        run_shapes.setdefault(ts[0] % 9, set()).add(ts[0] // 9)
    if any(len(v) == 3 for v in run_shapes.values()):
        han += 2 if menzen else 1
        yaku.append("sanshoku")

    if len(concealed_triplets) >= 3:
        han += 2
        yaku.append("sanankou")
    if len(kans) >= 3:
        han += 2
        yaku.append("sankantsu")
    if len(triplets) == 4:
        han += 2
        yaku.append("toitoi")
    if has_yaochuu and not any(t not in YAOCHUU for t in present):
        han += 2
        yaku.append("honroutou")

    dragon_triplets = [d for d in DRAGONS if full[d] >= 3]
    if len(dragon_triplets) == 2 and pair in DRAGONS:
        han += 2
        yaku.append("shousangen")

    def every_set_has(pred):
        return pred(pair) and all(any(pred(x) for x in ts)
                                  for ts, _ in all_melds)

    if every_set_has(is_yaochuu):
        han += 2 if menzen else 1
        yaku.append("chanta")
    if every_set_has(is_terminal) and not honors_present:
        han += 3 if menzen else 2
        yaku.append("junchan")

    run_tuples = [tuple(ts) for ts in runs]
    identical = {}
    for ts in run_tuples:
        identical[ts] = identical.get(ts, 0) + 1
    double_runs = sum(1 for v in identical.values() if v >= 2)
    if menzen and double_runs == 2:
        han += 3
        yaku.append("ryanpeikou")
    elif menzen and double_runs == 1:
        han += 1
        yaku.append("iipeikou")

    if len(suits) == 1 and not honors_present:
        han += 6 if menzen else 5
        yaku.append("chinitsu")
    elif len(suits) == 1 and honors_present:
        han += 3 if menzen else 2
        yaku.append("honitsu")

    # yakuman
    if honors_present and not any(t < 27 for t in present):
        yakuman += 1
        yaku.append("chiiniisou")
    if has_terminal and all(is_terminal(t) for t in present):
        yakuman += 1
        yaku.append("chinroutou")
    if len(dragon_triplets) == 3:
        yakuman += 1
        yaku.append("daisangen")
    wind_triplets = [w for w in WINDS if full[w] >= 3]
    if len(wind_triplets) == 3 and pair in WINDS:
        yakuman += 1
        yaku.append("shousuushii")
    if len(concealed_triplets) == 4:
        yakuman += 1
        yaku.append("suuankou")
    if len(kans) == 4:
        yakuman += 1
        yaku.append("suukantsu")

    han += dora + ura

    if han >= 13 and yakuman == 0:
        yakuman = 1
        yaku.append("kazoe yakuman")
        han = 0

    return han, yakuman, yaku


# ------------------------------------------------------------------ fu

def _fu_of(decomp_melds, called_melds, pair, win_tile, tsumo,
           seat_wind, prevalent_wind, chiitoitsu):
    if chiitoitsu:
        return 25
    fu = 20
    # ankan keeps the hand menzen (it is a concealed kan)
    menzen = not any(k in ("chi", "peng", MINKAN, SHOUMINKAN)
                     for _, k in called_melds)
    if menzen and not tsumo:
        fu += 10  # menzen ron
    elif tsumo:
        wait = _wait_type(decomp_melds, win_tile)
        if wait != "ryanmen":
            fu += 10  # non-pinfu tsumo
    wait = _wait_type(decomp_melds, win_tile)
    if wait in ("kanchan", "penchan", "tanki"):
        fu += 2
    for ts, kind in list(decomp_melds) + list(called_melds):
        if len(ts) == 3 and ts[0] == ts[1] == ts[2]:  # triplet
            simple = not is_yaochuu(ts[0])
            if kind in (CONCEALED, ANKAN):
                fu += 4 if simple else 8
            else:
                fu += 2 if simple else 4
        elif len(ts) == 4:  # kan
            simple = not is_yaochuu(ts[0])
            if kind == ANKAN:
                fu += 16 if simple else 32
            else:
                fu += 8 if simple else 16
    if pair in (prevalent_wind, seat_wind) or pair in DRAGONS:
        fu += 2
    return (fu + 9) // 10 * 10


# ------------------------------------------------------------------ points

def _points(fu: int, han: int, yakuman: int):
    """(ron_ko, ron_oya, tsumo_ko, tsumo_oya, limit_name).

    tsumo_ko  = what a NON-dealer pays when a non-dealer wins by tsumo
                (the dealer pays 2x this)
    tsumo_oya = what each non-dealer pays when the dealer wins by tsumo
    """
    if yakuman:
        return (32000 * yakuman, 48000 * yakuman, 8000 * yakuman,
                16000 * yakuman, f"yakuman x{yakuman}")
    if han >= 5:
        if han < 6:
            return 8000, 12000, 2000, 4000, "mangan"
        for threshold, name in ((8, "haneman"), (11, "baiman"),
                                (13, "sanbaiman")):
            if han < threshold:
                table = {
                    "mangan": (8000, 12000, 2000, 4000),
                    "haneman": (12000, 18000, 3000, 6000),
                    "baiman": (16000, 24000, 4000, 8000),
                    "sanbaiman": (24000, 36000, 6000, 12000),
                }
                return table[name] + (name,)
        return 24000, 36000, 6000, 12000, "sanbaiman"
    if (han == 4 and fu >= 40) or (han == 3 and fu >= 70):
        return 8000, 12000, 2000, 4000, "mangan"
    base = fu * (1 << (2 + han))
    ron_ko = -(-base * 4 // 100) * 100
    ron_oya = -(-base * 6 // 100) * 100
    ko_ts = -(-base * 1 // 100) * 100
    oya_ts = -(-base * 2 // 100) * 100
    return ron_ko, ron_oya, ko_ts, oya_ts, ""


# ------------------------------------------------------------------ API

def score_hand(counts, called_melds, win_tile, tsumo, dealer, seat,
               riichi=False, ippatsu=False, dora=0, ura_dora=0,
               rinshan=False, chankan=False, haitei=False, houtei=False,
               prevalent_wind=0):
    """Score a winning hand. Returns a dict or None if there is no yaku.

    `counts` is the concealed count vector including the win tile;
    `called_melds` is a list of (tiles, kind).
    """
    seat_wind = (seat - dealer) % 4
    ura = ura_dora if riichi else 0

    best = None
    if not called_melds and _kokushi(counts):
        ron_ko, ron_oya, ko_ts, oya_ts, limit = _points(0, 0, 1)
        return {
            "han": 0, "fu": 0, "yakuman": 1,
            "yaku": ["kokushi musou"], "limit": limit,
            "ron_ko": ron_ko, "ron_oya": ron_oya,
            "tsumo_ko": ko_ts, "tsumo_oya": oya_ts,
        }
    if _seven_pairs(counts) and not called_melds:
        han = 2 + dora + ura
        yakuman = 1 if han >= 13 else 0
        if yakuman:
            han = 0
        fu = 25
        ron_ko, ron_oya, ko_ts, oya_ts, limit = _points(fu, han, yakuman)
        best = {
            "han": han, "fu": fu, "yakuman": yakuman, "yaku": ["chiitoitsu"],
            "limit": limit, "ron_ko": ron_ko, "ron_oya": ron_oya,
            "tsumo_ko": ko_ts, "tsumo_oya": oya_ts,
        }
    n_melds = 4 - len(called_melds)
    for decomp_melds, pair in _decompositions(counts, n_melds):
        han, yakuman, yaku = _yaku_of(
            counts, decomp_melds, called_melds, pair, win_tile, tsumo,
            seat_wind, prevalent_wind, riichi, ippatsu, dora, ura,
            rinshan, chankan, haitei, houtei)
        if han == 0 and yakuman == 0:
            continue  # no yaku on this decomposition
        fu = _fu_of(decomp_melds, called_melds, pair, win_tile, tsumo,
                    seat_wind, prevalent_wind, chiitoitsu=False)
        ron_ko, ron_oya, ko_ts, oya_ts, limit = _points(fu, han, yakuman)
        cand = {
            "han": han, "fu": fu, "yakuman": yakuman, "yaku": yaku,
            "limit": limit, "ron_ko": ron_ko, "ron_oya": ron_oya,
            "tsumo_ko": ko_ts, "tsumo_oya": oya_ts,
        }
        if best is None or (cand["han"], cand["yakuman"]) > \
                (best["han"], best["yakuman"]):
            best = cand
    return best
