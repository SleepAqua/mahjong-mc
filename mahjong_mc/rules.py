"""Win detection, shanten (向听) and ukeire (有效进张) calculations.

Every function takes a 34-length count list describing a player's TOTAL
holding: concealed hand + meld tiles (13 tiles during play, 14 at the win).

Conventions:
    is_win()     - complete hand (4 melds + pair, or seven pairs)
    shanten()    - -1 = complete, 0 = tenpai, higher = further away
    ukeire()     - how many drawable tiles reduce the shanten

Implementation note: shanten decomposes per suit (melds and blocks never
span two suits), so each suit's count vector is converted once into its set
of achievable (melds, blocks) profiles and cached; the four group profiles
are then combined with a tiny DP maximising 2*melds + blocks under the
melds + blocks <= 5 constraint. This is far faster than a joint recursion
and is reused across the millions of hands seen in a Monte Carlo run.
"""

from __future__ import annotations

from .tiles import NUM_TILE_TYPES

_MAX_BLOCKS = 5  # 4 melds + pair


def _forms_melds(counts: list[int], n: int) -> bool:
    """True iff `counts` (restored before returning) decomposes into n melds."""
    for t in range(NUM_TILE_TYPES):
        c = counts[t]
        if c == 0:
            continue
        if n == 0:
            return False  # tiles remain but no meld slots left
        # triplet
        if c >= 3:
            counts[t] -= 3
            ok = _forms_melds(counts, n - 1)
            counts[t] += 3
            if ok:
                return True
        # sequence (suited tiles only)
        if t < 27 and t % 9 <= 6 and counts[t + 1] >= 1 and counts[t + 2] >= 1:
            counts[t] -= 1
            counts[t + 1] -= 1
            counts[t + 2] -= 1
            ok = _forms_melds(counts, n - 1)
            counts[t] += 1
            counts[t + 1] += 1
            counts[t + 2] += 1
            if ok:
                return True
        return False  # tile t cannot start any meld on this path
    return n == 0


def _meld_tiles(m):
    """Accept both (tiles, kind) meld records and plain tile tuples."""
    if len(m) == 2 and isinstance(m[1], str):
        return m[0]
    return m


def is_win(counts, melds=(), seven_pairs: bool = True) -> bool:
    """True if the total (concealed counts + melds) is a winning hand.

    A kan meld is 4 tiles but the player's holding only grows by 3 per kan
    (the 4th tile is the dead-wall replacement), so a winning hand with
    kans has 14 + #kans physical tiles. The concealed part must supply the
    remaining melds plus the pair.
    """
    meld_tiles = 0
    kans = 0
    for m in melds:
        ts = _meld_tiles(m)
        meld_tiles += len(ts)
        if len(ts) == 4:
            kans += 1
    if sum(counts) + meld_tiles != 14 + kans:
        return False
    if is_kokushi(counts, melds):
        return True
    if seven_pairs and not melds:
        if sum(c // 2 for c in counts) == 7:
            return True
    n_melds = 4 - len(melds)
    c = list(counts)
    for t in range(NUM_TILE_TYPES):
        if c[t] >= 2:
            c[t] -= 2
            ok = _forms_melds(c, n_melds)
            c[t] += 2
            if ok:
                return True
    return False


# --------------------------------------------------------------------------
# thirteen orphans (kokushi musou)
# --------------------------------------------------------------------------

YAOCHUU = frozenset([0, 8, 9, 17, 18, 26] + list(range(27, 34)))


def is_kokushi(counts, melds=()) -> bool:
    """Thirteen orphans: all 13 terminal/honour types plus one duplicate."""
    if melds or sum(counts) != 14:
        return False
    if any(counts[t] == 0 for t in YAOCHUU):
        return False
    if any(n for t, n in enumerate(counts) if t not in YAOCHUU):
        return False
    return sum(1 for t in YAOCHUU if counts[t] == 2) == 1


def kokushi_shanten(counts) -> int:
    """Shanten to thirteen orphans (0 = tenpai, -1 = complete, 13 = no hope).

    A hand with a triplet or a quad anywhere can never be kokushi, so it
    reports 13 (unreachable) rather than a misleadingly low number.
    """
    n = sum(counts)
    if n not in (13, 14) or any(c >= 3 for c in counts):
        return 13
    kinds = sum(1 for t in YAOCHUU if counts[t] > 0)
    pair = 1 if any(counts[t] >= 2 for t in YAOCHUU) else 0
    return 13 - kinds - pair


# --------------------------------------------------------------------------
# shanten via per-group (melds, blocks) profiles
# --------------------------------------------------------------------------

_SUIT_CACHE: dict[tuple, tuple] = {}
_HONOR_CACHE: dict[tuple, tuple] = {}
_PROF_PAIRS: dict[int, tuple] = {}
_TRANS: dict[tuple, int] = {}
_BEST: dict[int, int] = {}


def _prof_mask(profiles: set) -> int:
    """Encode a profile set as a 36-bit int (bit m*6 + b)."""
    mask = 0
    for m, b in profiles:
        mask |= 1 << (m * 6 + b)
    return mask


def _suit_profiles(key: tuple):
    """(profile mask, pair count) for one suit's 9 counts.

    The profile set contains achievable (melds, blocks) decompositions; a
    "block" is a pair or a two-tile partial run. Leftover single tiles are
    left unassigned (tanki / dead weight), which keeps the formula
    shanten = 8 - 2*melds - blocks correct after maximisation.
    """
    cached = _SUIT_CACHE.get(key)
    if cached is not None:
        return cached
    c = list(key)
    profiles: set = set()

    def rec(i: int, melds: int, blocks: int) -> None:
        while i < 9 and c[i] == 0:
            i += 1
        if i == 9:
            profiles.add((melds, blocks))
            return
        if melds + blocks >= _MAX_BLOCKS:
            return
        n = c[i]
        if n >= 3:  # triplet
            c[i] -= 3
            rec(i, melds + 1, blocks)
            c[i] += 3
        if n >= 2:  # pair
            c[i] -= 2
            rec(i, melds, blocks + 1)
            c[i] += 2
        if i <= 6 and c[i + 1] >= 1 and c[i + 2] >= 1:  # run
            c[i] -= 1
            c[i + 1] -= 1
            c[i + 2] -= 1
            rec(i, melds + 1, blocks)
            c[i] += 1
            c[i + 1] += 1
            c[i + 2] += 1
        if i <= 7 and c[i + 1] >= 1:  # partial run
            c[i] -= 1
            c[i + 1] -= 1
            rec(i, melds, blocks + 1)
            c[i] += 1
            c[i + 1] += 1
        rec(i + 1, melds, blocks)  # lone tile left unassigned

    rec(0, 0, 0)
    pairs = sum(x >> 1 for x in key)
    result = (_prof_mask(profiles), pairs)
    if len(_SUIT_CACHE) > 1_000_000:
        _SUIT_CACHE.clear()
        _PROF_PAIRS.clear()
        _TRANS.clear()
        _BEST.clear()
    _SUIT_CACHE[key] = result
    return result


def _honor_profiles(key: tuple):
    """(profile mask, pair count) for the 7 honor types (no runs)."""
    cached = _HONOR_CACHE.get(key)
    if cached is not None:
        return cached
    c = list(key)
    profiles: set = set()

    def rec(i: int, melds: int, blocks: int) -> None:
        if i == 7:
            profiles.add((melds, blocks))
            return
        if melds + blocks >= _MAX_BLOCKS:
            return
        n = c[i]
        opts = {(0, 0)}
        if n >= 2:
            opts.add((0, 1))
        if n >= 3:
            opts.add((1, 0))
        if n >= 4:
            opts.add((0, 2))
        for dm, db in opts:
            rec(i + 1, melds + dm, blocks + db)

    rec(0, 0, 0)
    pairs = sum(x >> 1 for x in key)
    result = (_prof_mask(profiles), pairs)
    if len(_HONOR_CACHE) > 1_000_000:
        _HONOR_CACHE.clear()
    _HONOR_CACHE[key] = result
    return result


def _combine(prof_mask: int, mask: int) -> int:
    """Advance the DP state bitmask by one group's profile set."""
    key = (prof_mask, mask)
    r = _TRANS.get(key)
    if r is not None:
        return r
    pairs = _PROF_PAIRS.get(prof_mask)
    if pairs is None:
        pairs = tuple(
            (i // 6, i % 6) for i in range(36) if prof_mask >> i & 1
        )
        _PROF_PAIRS[prof_mask] = pairs
    new = 0
    mm = mask
    while mm:
        low = mm & -mm
        mm ^= low
        idx = low.bit_length() - 1
        M = idx // 6
        B = idx - M * 6
        for m2, b2 in pairs:
            M2 = M + m2
            B2 = B + b2
            if M2 + B2 <= _MAX_BLOCKS:
                new |= 1 << (M2 * 6 + B2)
    _TRANS[key] = new
    return new


def _best_of(mask: int) -> int:
    """Minimum shanten value encoded by a state bitmask."""
    r = _BEST.get(mask)
    if r is not None:
        return r
    best = 8
    mm = mask
    while mm:
        low = mm & -mm
        mm ^= low
        idx = low.bit_length() - 1
        s = 8 - 2 * (idx // 6) - (idx - (idx // 6) * 6)
        if s < best:
            best = s
    _BEST[mask] = best
    return best


def shanten(counts) -> int:
    """Shanten of a 13 (+3 per meld) tile holding. -1 = win, 0 = tenpai."""
    c = counts
    g0 = _suit_profiles((c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7], c[8]))
    g1 = _suit_profiles((c[9], c[10], c[11], c[12], c[13], c[14], c[15],
                         c[16], c[17]))
    g2 = _suit_profiles((c[18], c[19], c[20], c[21], c[22], c[23], c[24],
                         c[25], c[26]))
    g3 = _honor_profiles((c[27], c[28], c[29], c[30], c[31], c[32], c[33]))
    mask = 1  # state (0 melds, 0 blocks)
    mask = _combine(g0[0], mask)
    mask = _combine(g1[0], mask)
    mask = _combine(g2[0], mask)
    mask = _combine(g3[0], mask)
    best = _best_of(mask)
    seven = 6 - (g0[1] + g1[1] + g2[1] + g3[1])
    best = seven if seven < best else best
    koku = kokushi_shanten(c)
    return koku if koku < best else best


def ukeire(counts, remaining):
    """(improving tile types, total remaining copies) for a 13-tile holding.

    `remaining[t]` must be the number of copies of tile t still available to
    draw (wall + opponents' concealed tiles). A tile type is "improving" when
    drawing it strictly lowers the shanten. Only tile types that could
    possibly interact with the hand (held types, or same-suit neighbours
    within 2 of a held tile) are tested — an isolated new tile can never
    reduce the shanten.
    """
    base = shanten(counts)
    # candidate types: held types + same-suit neighbours within distance 2
    cands = set()
    for t in range(NUM_TILE_TYPES):
        if counts[t] > 0:
            cands.add(t)
            if t < 27:
                base9 = t - t % 9
                n = t % 9
                for d in (-2, -1, 1, 2):
                    nn = n + d
                    if 0 <= nn <= 8:
                        cands.add(base9 + nn)
    types: list[int] = []
    copies = 0
    for t in sorted(cands):
        avail = remaining[t]
        if avail <= 0:
            continue
        counts[t] += 1
        if shanten(counts) < base:
            types.append(t)
            copies += avail
        counts[t] -= 1
    return types, copies
