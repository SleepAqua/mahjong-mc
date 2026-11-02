# Strategy — Louis's rules, riichi theory, and the policy in `my_strategies/louis.py`

This document is the spec for the `louis` policy: what the bot is trying to do,
in which order, and why. Every numbered rule below is traceable to a function
in `my_strategies/louis.py`.

    # play it locally against the field
    python3 -m mahjong_mc --games 20000 --policies louis,gto,defensive,greedy

    # play it online (the systemd unit already does this)
    python3 -m mahjong_mc.riichi_ws --policy louis

---

## 1. Discard order for lone tiles (rule 1)

A *lone* tile is one that shares no block with the rest of the hand: no pair,
no adjacent tile, no tile within two of it in the same suit. A single honour is
always lone.

Order of disposal, first thrown away → last kept:

| # | tile | rationale |
|---|------|-----------|
| 0 | lone guest wind (客風, neither round nor seat wind) | no yaku, no pair value, one of four |
| 1 | lone round wind (bakaze) | everyone holds it, only a pair has value |
| 2 | lone 1 / 9 (1 without 2 or 3, 9 without 7 or 8) | only one run can use it; edge waits are slow |
| 3 | lone dragon | pair value is real (yakuhai), but a lone dragon is dead weight |
| 4 | lone seat wind (jikaze) | yakuhai if paired, same as dragons but one copy of value |
| 5 | lone 2 / 8 | two runs possible but both are edge-ish, weak acceptance |
| 6 | lone 3 / 7 | better acceptance than 2/8 |
| 7 | lone 4 / 6 | can accept either side |
| 8 | lone 5 | most central, most acceptance, also has red-five value |

**Where this deviates from standard theory — one entry only.** Your list keeps
dragons and the seat wind *after* the terminals, which is textbook: a live
yakuhai is 1 han and pon-able, so it outlives a lone 1/9. The single
non-standard entry was the **round wind** sitting at position 1, ahead of the
terminals. It is yakuhai like a dragon, so it now shares their place (rank 3),
and the deadline below sends any honour that has stopped being pairable to the
front. Everything else in your order is unchanged.

(I had this wrong in an earlier revision of this document — I wrote "1/9 above
dragons" as the deviation, misreading your list. Corrected here and in the
code.)

**The order is authoritative, not a tie-break.** Among the discards that keep
the best shanten, if any candidate is a lone tile, the policy throws the one
your table ranks first — even when tile efficiency would prefer a different
tile. Efficiency only decides once no lone tile is left in the pool (rule 2).
This was a correction: the first implementation made the table a tie-break and
the bot discarded a lone dragon while holding an isolated 1m, which is exactly
the behaviour this rule exists to prevent. `tests/test_louis_policy.py` now
pins it, including the hand from that game.

`_lone_rank()` / `_is_lone()`.

---

## 2. Shape priority when nothing is lone (rule 2)

Two-tile block value, best → worst:

1. **ryanmen** (両面, e.g. 34) — accepts two tile types, up to 8 copies
2. **pair** — can become a triplet or, more often, the head
3. **kanchan** (嵌張, e.g. 35) — one middle tile, up to 4 copies
4. **penchan** (辺張, 12 or 89) — one tile, and the 1/9 side is often dead

Encoded as a block-quality score (`_shape_score`) that counts triplets and
pairs, then partial runs, scoring ryanmen 4, pairs 3, kanchan 2, penchan 1.
It is a secondary term (weight 3) — acceptance count stays the primary driver,
because a ryanmen with one live copy is worse than a kanchan with three.

This is the standard ordering and does not conflict with your rules.

---

## 3. Keep dora (rule 3)

Dora is known from the dora indicators, so the engine now exposes
`view.dora_indicators` (previously only `dora_count`). Discarding a dora costs
a 30-point penalty plus 12 per extra copy held; that penalty is large enough to
protect a dora pair but not large enough to keep folding a dora into a broken
shape forever.

---

## 4. Pairs (rules 4 and 5)

* **three or more pairs**: a pair is worth more as a head than as material, but
  beyond two pairs the hand starts to lack blocks. The policy keeps the
  shanten-minimising discard and lets ukeire decide whether a pair must be
  broken; the lone-tile bonus is always weaker than the pair break, which is
  your "but still better than lone cards" clause.
* **four or more pairs**: seven pairs becomes the primary route
  (`seven_pairs_shanten`), and the shanten used for discard choice is the
  minimum of the normal and the seven-pairs value. Seven pairs is closed-only,
  2 han 25 fu (3 han with riichi), and it doubles as a menzen riichi vehicle —
  it also has the practical advantage of needing no blocks at all, so hands
  that look hopeless assembly-wise can still be live.

Note that `rules.shanten()` already folds seven pairs into its minimum, so the
policy cannot accidentally abandon a seven-pairs hand that is closer than the
normal structure.

---

## 5. Folding and pushing (rule 6)

The flat version — fold whenever someone riichis and we are not tenpai — is
what the first build did, and it is right far more often than attacking. It is
now value-aware (`_should_fold`), because "tenpai" is not the same as "worth
pushing":

| our state | decision |
|---|---|
| not tenpai | fold |
| tenpai, live winning tiles ≥ `PUSH_COPIES` (6) | push |
| tenpai, hand value ≥ `PUSH_VALUE` (3900 pts) | push |
| tenpai, narrow wait and cheap hand | fold — a 1,000-point hand is not worth a 20% chance of paying 8,000 |
| 1-shanten, value ≥ `SEMI_PUSH_VALUE` (7700) and wall ≥ 30 | semi-push: keep attacking, but safety still ranks the discards |

Hand value is a rough han estimate (riichi + dora + tanyao + yakuhai pairs)
mapped through the real scoring table. In betaori the policy stops caring about
shape and throws the safest tile in hand, preferring one from a safe pair so its
twin is a guaranteed safe discard next turn.

When we *are* attacking, danger is subtracted from every candidate's score
(×`DANGER_WEIGHT`), so among equally strong discards the safe one wins.

---

## 6. Defence: the actual safety functions (rule 7)

`_safe_against(view, tile, threats)` decides whether a discard can be ron'd by
every player currently in riichi:

* **genbutsu** — the tile is already in that player's discard pile. 100% safe,
  no exceptions. Also covers the riichi declaration tile and everything they
  discarded afterwards.
* **suji** (筋) — if that player has discarded 4 of a suit, then 1 and 7 of
  that suit cannot be a *ryanmen* wait (they would have needed the 4). Checked
  in both directions (1-4-7, 2-5-8, 3-6-9). Suji is a strong reduction, not a
  guarantee: kanchan, penchan, shanpon and tanki waits are unaffected.
* **honour counting** — a lone honour can only be waited on as a pair, so once
  two copies are visible *outside our hand* it is effectively dead. Honour
  tiles are also the safest thing to hold while folding for exactly this
  reason.
* **kabe / no-chance** — if all four copies of a tile are visible (our hand
  included), nobody can hold one, so it cannot be a wait. Applied as the
  `visible >= 4 → safe` case.

When nothing is fully safe, `_danger()` ranks the candidates: honours ≈ 40,
1/9 ≈ 55, 2/8 ≈ 70, 3/7 ≈ 85, 4/5/6 ≈ 100, minus 25 if three copies are
visible (a thin wait is a smaller bet). The cheapest tile is discarded, which is
the practical version of "fold with the least bad tile".

Deliberately **not** implemented: opponent hand-reading from discard patterns,
matagi-suji, and betaori that preserves tenpai. They need either more state than
the `View` exposes or a trained model; see §9.

---

## 7. Thirteen orphans (rule 8)

If the dealt hand contains **10 or more distinct** terminal/honour types, the
policy commits to kokushi for that hand and stops evaluating normal shapes.
It exits the commitment if kokushi shanten climbs above 3, so a dead attempt
does not poison the rest of the kyoku.

Kokushi was not supported by the engine at all (no win detection, no scoring),
so it was added:

* `rules.is_kokushi()` and `rules.kokushi_shanten()`, folded into
  `rules.shanten()` (a hand with a triplet anywhere reports 13 — unreachable)
* `scoring.score_hand()` returns a yakuman (32000 / 48000 dealer, 8000/16000
  tsumo) with the yaku name `kokushi musou`
* `tests/test_kokushi.py` covers complete hand, tenpai, twelve kinds + pair,
  triplet disqualification, dealer pricing

Note: the RiichiLab server scores wins itself, so online the bot only has to
*declare* the win; locally the new scoring keeps the Monte Carlo honest.

---

## 8. When the bot riichis and when it calls

Not in your list, but the bot needs a rule:

* **riichi** when tenpai, no commitment to kokushi, wall ≥ 10 tiles, and
  (a) nobody is in riichi, or (b) exactly one is and our wait has ≥ 6 live
  copies. Two or more riichi ⇒ no riichi.
* **calls**: peng only, and only on a yakuhai tile, and only when it strictly
  lowers shanten. No chi (an open hand without a yaku is a dead hand), no
  daiminkan (too slow, kills concealment). Chiitoitsu and kokushi are closed
  hands by definition, so calling them away is never right.
* **kan**: ankan only for a dora tile or when shanten ≥ 2. Added kan
  (shouminkan) is never taken — it invites chankan for no gain.

---

## 9. Measured results

Monte Carlo, 20,000 games, seed 42, 8 workers — all four seats in one field:

    seat policy          win%   tumo%    ron%  deal-in%  riichi%  pts/game  avg rank
    --------------------------------------------------------------------------------
       0 louis         22.48%   5.67%  16.82%    11.71%   38.35%     235.2     2.316
       1 gto           19.18%   5.38%  13.80%    12.16%   31.51%     -17.3     2.355
       2 defensive     16.48%   4.29%  12.19%    15.59%   12.62%    -133.8     2.085
       3 greedy        16.52%   4.46%  12.05%    15.42%   13.14%     -96.0     2.082

`avg rank` flatters the low-variance bots: `defensive` folds so much it rarely
loses big and rarely wins big. `pts/game` is the honest metric, and `louis` is
+228 points per game ahead of the previous champion.

---

## 10. Can the bot learn from its own games (rule 11)?

Yes in principle, but the honest answer is "not the way AlphaGo did, not with
what we have".

What AlphaGo needed: a fast simulator, a compact representation, and millions
of self-play games on GPUs. What we have: a pure-Python engine at ~100
games/s per 8 cores, i.e. ~8.6M games/day if it runs flat out, and no
representation of a *position* that a network could consume cheaply.

Three realistic routes, cheapest first:

1. **Evolutionary search over parameters (built).** Two scripts:
   `examples/evolve.py` mutates the old parameter family (that produced `gto`),
   and `examples/evolve_louis.py` mutates the five weights this policy depends
   on — push thresholds, the honour deadline and the danger weight — using
   paired seeds so candidates are compared on the same deals. The winner is
   written to `my_strategies/louis_params.json`, which the policy loads on
   import. It optimises *my* heuristics, not a model: no new information enters
   the bot, only better numbers on the same ideas.
2. **Self-play with a learned value function.** Features from the View
   (shanten, ukeire, dora, safety counts, turn, wall, points, riichi flags,
   melds) → small MLP or gradient-boosted trees trained to predict final
   placement; use it instead of the hand-tuned weights. Needs numpy/scikit, a
   few hundred thousand self-play games, and a fixed evaluation field. Days of
   compute, not minutes. This is the smallest step that deserves the word
   "learning".
3. **Behaviour cloning from the logs.** We already log every game the online bot
   plays (`logs/last_game.log`), including the server's legal-action list. That
   gives states, not labels — the bot's action was the label, and the bot is the
   thing we want to improve, so cloning it is circular. Useful for bug-finding,
   not for strength.

What is actually worth doing next, in order:
1. tune the new weights by evolution (hours, free)
2. add opponent-discard-pattern features to the danger model (the biggest
   remaining gap vs a human expert)
3. only then consider a learned value function

None of this replaces the server's own rating signal: the arena is the only
place that tells us whether it worked.

---

## 11. Evaluating the rule set — what changed, what I would change

### Rules that are sound as written

* **the lone-tile concept itself.** Most players think in "blocks"; ranking the
  tiles that belong to no block at all is the right abstraction, and it is why
  the bot stops hoarding isolated honours.
* **lone 1/9 above lone 2/8 above lone 3/7.** Terminals accept two tile types
  and only one run; that ordering agrees with tile-efficiency literature [S1].
* **keep dora, keep pairs, fold when someone riichis.** All three are pure
  expected value and need no defence.
* **four+ pairs → seven pairs**, and **10+ distinct terminals/honours →
  kokushi**. Both are standard thresholds [S5][S20]; your numbers sit at the
  conventional boundary.

### Refinements I applied

1. **A lone yakuhai now has a deadline.** It keeps its place in your order only
   while it can still be paired: after six discards, or once two copies are
   visible elsewhere, it drops to the front of the queue. A dragon held to the
   last discard is a hand with no yaku and no blocks. [S2]
2. **One-chance does not count as safe.** I first implemented "three copies
   visible ⇒ safe against a single riichi" and it made the bot deal in more,
   not less: three visible still leaves one copy in a hand, which is a live
   tanki or shanpon wait. It stays a danger modifier (−25), which is exactly
   what the sources say it is — a tiebreaker inside a safety rank. [S8][S9]
3. **Folding keeps a safe pair.** When choosing the tile to fold with, a tile
   that is both safe and part of a pair is preferred, because its twin is a
   guaranteed safe discard on the next turn (mawashiuchi). [S15]
4. **No riichi on a narrow wait late.** With no opponent in riichi, tenpai, ten
   or more discards played and fewer than four live winning tiles, the bot
   stays damaten: a bad wait late wins ~33%, and damaten keeps the option to
   fold if someone else declares. [S16][S17]

### Changes I would make but did not (your call, one line each)

* **kokushi tenpai skips riichi.** Riichi is legal and adds value; the bot
  declines it. Conservative, not wrong.

### Applied after the evaluation above

* **rule 1: the round wind joins the value honours** (see §1).
* **rule 2: a pair is a head before it is a shape.** The first pair now scores
  5 against ryanmen 4 and kanchan 2; extra pairs fall back to 3, because they
  feed shanpon and chiitoitsu instead of forming a new block. [S1][S3]
* **rule 7: real opponent reading.** `_pond_read` adds danger from an
  opponent's discard order — a suit they have cut four or more times is
  discounted, a late discard two steps away in the same suit (matagi-suji)
  raises danger, and an early 5 (ura-suji) raises it around the 1-4 and 6-9
  neighbourhoods. Crude, but it sees what suji alone cannot.
* **rule 6: push/fold by hand value** instead of "tenpai or not" — see §5.

### The 2026-11-02 losing streak: what the games actually say

Six consecutive 4ths (11:49–12:18), all narrow (−5100, +10900, −6500, −3500,
+9200, +6700), none of them chombos. Across the 100 logged games (949 kyoku):

    us      agari 17.2%/kyoku   deal-in 29.4%
    field   agari 23.9%         deal-in 19.8%

so the bot was not unlucky, it was losing the fight on both sides of the table.
Where the deal-ins came from: 62% to a declared riichi, 30% to an **open**
hand, 8% to dama. And 51% of them happened while we were in 4th place, against
30% of our discards — about twice the deal-in rate per discard, in the one place
the policy deliberately changes behaviour (`_score_pressure` returned "+1 push"
from 4th regardless of the gap).

What that produced:

* **chombo from claim spelling.** Two chombos in the logs were `chi`/`pon`
  sent with `consumed: ["5p","5p"]` while one copy was the red five; the server
  answered `not_in_legal_actions` and ended the round (mangan). Claims are now
  answered with the server's own option dict.
* **red fives thrown away.** 54 discards took the aka dora out while a plain
  copy was in hand, because the server lists `5pr` before `5p` and the driver
  took the first match.
* **red fives not valued.** The 34-type engine cannot see that a 5 is red, so
  `_hand_value` under-counted every hand holding one by a han. The driver now
  tracks the red fives it holds and adds them to `dora_count`.
* **desperation push.** The 4th-place push is now gated on the gap to third
  (`DESPERATE_GAP`, 12,000): push when a mangan will not save the placement,
  play normally when it will.

### What was tried and rejected (measured, not argued)

Paired A/B, 24,000 games each, fixed seed, seats rotated:

    variant                                 excess vs control      verdict
    open hands / late hand as threats       +30 pts, 4th% flat     neutral
    suji keeps residual danger (0.3)        +35 pts, 4th% flat     neutral

Both were worth testing — 38% of the deal-ins are to hands the threat list
ignored — but neither pays for the extra folding in this field. They stay as
off-by-default switches (`SOFT_DANGER`, `SUJI_RESIDUAL`).

**Harness caveat, now fixed:** `tools/ab_test.py` pinned A to seat 0, and a
policy playing itself "won" +75 points and 0.14 places. Seats now rotate. Any
pre-2026-11 A/B result smaller than that offset is not evidence.

**Simulator caveat:** the local field deals in 11.6% where the online field
deals in 29.4% for the same policy. The local sim cannot rank defensive
changes for the online arena; it can only reject clearly bad ones.


### Measurement honesty, and how many games a test needs

Rules changes are easy to make and hard to prove. Three independent 1,000-game
blocks (seeds 42, 3000, 6000, refined policy):

    block      louis pts/game    gto pts/game
    seed 42        -67.1            +136.2
    seed 3000     +305.8             -33.4
    seed 6000     +186.7             +83.9

Per-block spread is ±200 points per game: a 1k run cannot rank two policies, it
can only catch a gross regression.

The right test is **paired**: both policies play the same deals, so the per-game
score difference cancels the deal luck. Measured on a 2,000-game pilot the
difference has sd ≈ 5,600 points/game, so

    SE = 5600 / sqrt(N)   →  N = (1.96 * 5600 / target_SE)^2

| target SE | games | CI half-width | wall time (8 cores) |
|-----------|-------|---------------|---------------------|
| 125 | 2,000 | ±245 | <1 min |
| 50 | 48,000 | ±98 | ~10 min |
| 25 | 193,000 | ±49 | ~30 min |

For tuning decisions use **48,000 paired games** — that resolves a 100 pt/game
difference at 95% confidence in about ten minutes. Use 1k only as a smoke test.

    python3 tools/ab_test.py --pilot 2000     # measure variance, get the N
    python3 tools/ab_test.py --games 48000    # the real test

Results, paired, field defensive/greedy:

| test | games | result | verdict |
|---|---|---|---|
| `louis` (rule refinements) vs `gto` | 48,000 | +185.7 ±53.0, win 21.9% vs 19.5%, rank 2.321 vs 2.514 | louis better |
| `louis` (evolved weights) vs `louis_old` (pre-evolution) | 48,000 | +58.7 ±52.2, win 21.8% vs 20.6%, rank 2.309 vs 2.477 | tuned better |
| current `louis` vs `gto` | 12,000 | +205.7 ±105.0, win 22.1% vs 19.2% | louis better |

`louis_old` = identical code with the original weights, so the second row isolates
the evolution step: +59 points per game, roughly a third of the gap to `gto`.

### Human benchmark (the target)

Louis's own 4-player ranked record, 245 games, 4-dan — this is what the bot is
supposed to be chasing:

| metric | Louis (human) | bot before | bot after the style fix |
|---|---|---|---|
| win rate / kyoku | 26.6% | 5.5% | — (measured locally, see below) |
| deal-in rate | 15.7% | 22.7% | — |
| call rate | **54.8%** | 7.3% | — |
| riichi rate | 17.8% | 18.5% | — |
| tsumo share of wins | 28.7% | ~92% | — |
| 1st / 2nd / 3rd / 4th | 27.8 / 25.3 / 22.4 / 24.5 | 5.6 / 7.4 / 22.2 / 64.8 | — |
| avg rank | **2.40** | 3.46 | — |

The human line is the diagnosis: he **calls in 54.8% of hands**, keeps riichi at
17.8% (open hands cannot riichi), and still deals in only 15.7%. The bot called
7.3%, won 5.5%, dealt in 22.7% — it was strictly worse at both ends. A closed,
riichi-only bot is not "defensive", it is passive: no calls, almost no wins,
noten penalties at every draw, fourth place.

Two policy changes followed from that, and both are in `my_strategies/louis.py`:

1. **Calls are real now** (`decide_call`, gated by `_open_yaku_ok`): chi/pon/
   daiminkan whenever the tile is yakuhai, the hand is tanyao, or the hand is
   heading for honitsu — i.e. whenever the opened hand still has a yaku — and
   only when the hand is within `CALL_MAX_SHANTEN` (2). An open no-yaku hand is
   a dead hand, so the yaku gate is absolute.
2. **Fold dead hands only** (`_should_fold`): a 1-shanten with value keeps
   attacking; only a worthless 1-shanten late, a cheap narrow tenpai, or a
   2-shanten without value folds. Riichi only counts as hand value when the
   hand is closed.

Measured, 12,000 paired games against the identical code with calling disabled
and the old fold rule:

    win% 22.9 vs 19.5   avg rank 2.266 vs 2.537   4th 21.7% vs 28.6%

The 4th rate is the number that matters, and it moved 7 points. Live numbers
need a few hundred games before they mean anything.

### What top players and the strong bots actually do (research pass)

Sources: [S21] npmahjong push-or-fold and course material, [S22] Riichi Nomi
push/fold lecture, [S23] simzhou push/fold standards, [S24] Mortal v3 model card
and mjai-reviewer FAQ, [S25] riichi.wiki five-block theory.

Four findings that changed the policy:

1. **Folding is not free.** A clean fold is worth roughly **-1,500 to -2,000
   points** on average (noten penalties at every draw), so the push/fold
   question is never "is this risky" but "is pushing worth more than -1,500".
   That single number is why a passive bot loses placements: it pays the fold
   price every hand and never collects the win. [S22]
2. **The standard ladder** is tenpai → push, 1-shanten → at most one dangerous
   tile, 2-shanten or worse → full fold. Our old rule betaori'd at 1-shanten
   too, which is stricter than the literature. [S23]
3. **Five-block theory**: a hand needs five blocks. With six or more, cut the
   weakest block whole rather than dribbling singles; with four, keep the loose
   tile that can still grow. [S25][S21]
4. **Mortal optimises placement, not points.** Its reward is the change in
   expected finishing order (Φ_k+1 − Φ_k) from a placement model, evaluated
   over the whole hanchan. Two consequences: score context belongs in the
   decision (a 4th-place bot should push; a big leader should fold), and any
   local metric that ignores placement is measuring the wrong thing. [S24]

Implemented from that:

* **`_push_ev` / `_should_fold`** — push when `p_win × hand_value − p_loss ×
  loss − noten` beats a fold worth -1,500; `p_win` ≈ 5% per live winning tile
  for tenpai, 1.8% for 1-shanten. The threshold tables are gone; the constants
  they used to encode are now the cost of the alternatives.
* **`_score_pressure`** — in a real hanchan (not a level local game): 4th place
  late makes folding 700 points worse; a big lead in 1st/2nd makes folding 700
  points better. Returns 0 in the local Monte Carlo, where every kyoku starts
  level, so it cannot be measured there.
* **`_block_count` / `_growth`** — with 6+ blocks, prefer discarding from the
  weakest block.

Measured, 12,000 paired games, current vs the value-threshold version of the
same code (calls on, block cut off, old fold):

    win% 22.9 vs 20.6   avg rank 2.275 vs 2.463   4th 22.6% vs 26.8%

Adding §Sources entries S21–S25 in the list below.

**What the A/B taught, in one place**

1. Defence was under-weighted by every hand-tuned version. The search more than
   doubled the danger weight (2.0 → 3.25) and narrowed what counts as a
   pushable tenpai (6 → 8 live tiles). Both point the same way: this bot was
   attacking too often with too little.
2. A lone honour lives one turn longer than I assumed (deadline 6 → 7) — at a
   real table the pair forms later than in a 14-tile heuristic.
3. Small parameter gains look bigger in-sample than they are: +23 pts/game on
   the tuning seeds, +59 on 48k fresh paired games with a ±52 CI. Never quote
   the in-sample number as the result.
4. 12,000 paired games are not enough to call a ~60-point difference (CI ±105
   straddles zero); the same test at 48,000 does. Screening budget and decision
   budget are different numbers.
5. The harness must mutate the *registered* policy class. Loading the strategy
   file twice (once by the policy loader, once by a direct import) produced a
   search where every candidate scored identically — a silent no-op that looks
   like "the parameters don't matter".

**Evolution (step 1 of §10) result** — `examples/evolve_louis.py`, 5 candidates ×
3 generations × 2,000 games, paired seeds:

    start    PUSH_COPIES 6  PUSH_VALUE 3900  SEMI 7700  DEAD_TURN 6  DANGER 2.00  → +335.2
    final    PUSH_COPIES 8  PUSH_VALUE 4011  SEMI 7142  DEAD_TURN 7  DANGER 3.25  → +358.7

In-sample gain is ~23 points/game, out-of-sample (48k paired) ~+59 with a wider
CI. Direction: push wider waits less often, weight danger harder, and keep a
lone honour one turn longer. Written to `my_strategies/louis_params.json`, which
the policy reads at import — no code change to deploy a tuned bot.

---

## Sources, and where the literature disagrees with the rule list

The rules above are yours; this section is what the standard literature says
where the two differ, so the differences are a decision and not an accident.
Sources are numbered and listed at the end.

**Three corrections worth knowing** [S1][S2][S6]:

* your list has no *guest wind* entry, but the guest wind is the single most
  disposable tile in the game — no sequence, no yaku. It is coded as rank 0,
  ahead of the round wind.
* round wind and seat wind are both yakuhai (1 han, pon-able) and a live one
  outranks a lone terminal: rank 1/9 belongs *after* the value honours, not
  before. The code follows your order anyway (it is a tie-break, and the
  measurements in §9 are with your order) — flip two constants in
  `_lone_rank()` if you want the textbook order and re-run the benchmark.
* `pair > kanchan` is not standard: a pair is a head first and a set second, and
  is ranked on its own. It is implemented as your rule 2 says, because pairs
  also feed rules 4 and 5.

**Safety ladder** (use literally; it beats hand-reading) [S8]: SS genbutsu ·
S yakuhai with 2+ out / guest wind with 1+ out / suji 1-9 · A live guest wind /
double suji 456 · B yakuhai with 1 out / suji 2-8 · C live yakuhai / suji 3-7 ·
D no-suji 1/9 / single suji 456 · E no-suji 2-8, 3-7 · F no-suji 456. Adjacent
ranks differ by roughly 50% in deal-in rate. The code collapses SS–B into
`_safe_against()` and D–F into `_danger()`.

**Push/pull numbers** (Tenhou Houou logs, 2016–2020) [S12]: a clean fold against
one riichi costs about 1,120 points; one deal-in costs about five folds. A
ryanmen tenpai against a non-dealer riichi wins ~48%, deals in ~16%, and is
worth ~+3,300 versus folding — so pushing any ryanmen tenpai is correct, while
a narrow wait (32% win / 21% deal-in) needs ~2,000 points of hand value to be
worth it, mangan against a dealer. This is why §5 folds only when not tenpai.

**Suji is not safety** [S9]: discarding a 4 kills the ryanmen 1-4-7 for that
player, but kanchan, penchan, shanpon, tanki and chiitoitsu waits survive.
Suji 1/9 is safest, then 2-8 and 3-7; single-suji 4/5/6 is the worst kind of
"suji". Dangerous variants (ura-suji off an early 5, matagi-suji, yonken-suji)
are deliberately not implemented — they need pond history modelling, see §10.

**Kabe / one-chance** [S9]: all four copies of a tile visible kills every wait
that needs it; three visible is only a tiebreaker. Implemented as the
`visible >= 4` case in `_safe_against()`.

**Riichi timing** [S16][S17]: riichi is the default for a closed tenpai;
damaten is for a guaranteed haneman+, or a late-game stick that changes
placement. Late in the hand a bad wait (single wait on 5 ≈ 33% win, shanpon
2-8 ≈ 41%) is not worth the riichi — hence the wall_left and live-copy tests in
`decide_riichi()`.

**Kokushi thresholds** [S20]: 9+ distinct terminal/honour types → aim; 7-8 →
situational; 6 or fewer → abandon. Your threshold (>9) is coded as `>= 10`,
with the extra guard that the attempt dies once kokushi shanten exceeds 3.

---

### Source list

S1 https://repo.riichi.moe/books/rb1/ch3.html — tile efficiency (Riichi Book 1, ch.3)
S2 https://simzhou.com/riichi_mahjong_book/en/pairi/pairi03.html — discarding lone honours vs terminals
S3 https://simzhou.com/riichi_mahjong_book/en/pairi/pairi08.html — shape values
S4 https://simzhou.com/riichi_mahjong_book/en/pairi/pairi19.html — tenpai comparison, damaten
S5 https://tsumoron.com/en/articles/glossary/chiitoitsu/ — when to commit to seven pairs
S6 https://npmahjong.com/yaku/chiitoitsu — chiitoitsu = 2 han 25 fu, closed only
S7 https://simzhou.com/riichi_mahjong_book/en/mamori/mamori02.html — genbutsu, furiten safety
S8 https://osamuko.com/basic-defense-techniques-in-mahjong/ — the SS–F safety ladder
S9 https://mahjong.in.ua/en/2013/07/defense-guide-suji/ — suji mechanics and what it misses
S10 https://simzhou.com/riichi_mahjong_book/en/mamori/mamori14.html — dangerous suji variants
S11 https://simzhou.com/riichi_mahjong_book/en/osihiki/osihiki03.html — when to fold
S12 https://npmahjong.com/blog/tenuki-when-to-ignore-a-riichi — fold cost vs push EV
S13 https://simzhou.com/riichi_mahjong_book/en/mamori/mamori06.html — how to fold
S14 https://simzhou.com/riichi_mahjong_book/en/mamori/mamori07.html — choosing the least bad tile
S15 https://simzhou.com/riichi_mahjong_book/en/mamori/mamori09.html — safe pairs / mawashiuchi
S16 https://simzhou.com/riichi_mahjong_book/en/reach/reach02.html — riichi vs damaten
S17 https://npmahjong.com/blog/riichi-wait-win-rates — wait-type win rates
S18 https://simzhou.com/riichi_mahjong_book/en/naki/naki03.html — call speed (pon ≈ 4×, chi ≈ 2×)
S19 https://simzhou.com/riichi_mahjong_book/en/naki/naki02.html — when a call is worth it
S20 https://tsumoron.com/en/articles/glossary/kokushi-musou/ — kokushi thresholds
S21 https://npmahjong.com/tools/push-or-fold — push/fold EV charts, Houou-level data
S22 https://www.youtube.com/watch?v=UyX0vTFyqXc — Riichi Nomi lecture: folding is -1,500 to -2,000 EV
S23 https://simzhou.com/riichi_mahjong_book/en/osihiki/osihiki03.html — the tenpai/1-shanten/2-shanten ladder
S24 https://huggingface.co/hhim8826/mortal3-b40c192 — Mortal v3: dueling DQN, placement-Φ reward, grp/tempai heads
S25 https://riichi.wiki/index.php?title=Riichi_Book_1 — five-block theory and the value/speed condition for pushing

