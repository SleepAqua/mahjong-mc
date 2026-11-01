# mahjong-mc — Monte Carlo Mahjong (Japanese rules)

Play four-player Mahjong **millions of times** to test strategies, instead of
playing round by round yourself. Plug in a strategy (a `Policy` object) and
let the engine play it against baselines millions of times, then read off
win rates, deal-in rates and scores.

Pure Python 3, no dependencies. Tested on Python 3.14.

## Quick start

```bash
cd ~/coding/mahjong-mc

# run the test suite (68 tests)
python3 -m unittest discover -s tests -v

# 5,000 games: greedy vs three defensive, all 8 cores
python3 -m mahjong_mc --games 5000 --policies greedy,defensive,defensive,defensive --workers 8
```

Example output (8-core machine, ~200 games/s):

```
seat policy          win%   tumo%    ron%  deal-in%  riichi%  pts/game  avg rank
--------------------------------------------------------------------------------
   0 greedy        17.30%   4.38%  12.92%    14.40%   12.48%     -45.0     2.066
   1 defensive     18.84%   4.94%  13.90%    13.80%   13.06%     -14.6     2.047
   2 defensive     18.88%   4.64%  14.24%    13.76%   13.48%      11.6     2.055
   3 defensive     19.28%   4.90%  14.38%    13.48%   12.82%      -7.8     2.041

games: 5000  seed: 7  elapsed: 24.6s  (203 games/s)
1,000,000 games ≈ 81.9 min on this machine
```

**What the columns mean**

- `win%` — share of games this seat won (tumo + ron)
- `tumo%` — wins by self-draw; `ron%` — wins by claiming a discard
- `deal-in%` — share of this seat's discards that got ron'd (放铳率)
- `riichi%` — share of games where this seat declared riichi
- `pts/game` — average points won/lost per game (han/fu scoring, 25000 start)
- `avg rank` — average finishing position (1 = best)

**Why the win rates don't sum to 100%** — because games can end in an
exhaustive draw (the wall runs out). The four win rates sum to
1 − draw rate; in the run above ~26% of games were draws. At an exhaustive
draw, tenpai players collect 3000 total from the noten players (听牌罚符),
which is already reflected in `pts/game`.

## Rules (Japanese standard)

- 136 tiles: 122-tile live wall + 14-tile dead wall (dora indicators)
- win = 4 melds + pair, or seven pairs (a win needs at least one yaku;
  hands without a yaku are not wins under these rules)
- riichi / ippatsu / permanent furiten / forced tsumu-giri after riichi
- ankan / minkan / shouminkan (called and added), chankan ron
- dora, ura dora, kan dora; rinshan kaihou, haitei, houtei
- han/fu scoring: 25+ yaku incl. riichi, pinfu, tanyao, yakuhai, chanta/
  junchan, itsuu, sanshoku(doukou), sanankou, sankantsu, chiitoitsu,
  toitoi, honroutou, shousangen, honitsu, chinitsu, ryanpeikou, iipeikou;
  yakuman: chiiniisou, chinroutou, daisangen, shousuushii, suuankou,
  suukantsu (multiple yakuman stack; 13+ han = kazoe yakuman)
- dealer (oya) pays/receives 1.5x; honba +300 on ron, +100 each on tsumo;
  riichi sticks go to the winner
- exhaustive draw: noten-bappu (3000 total, split among the tenpai)
- the dealer rotates one seat per game in batch runs, so every seat plays
  oya equally often

### Known limitations (documented, not bugs)

- Each batch game is one independent kyoku: points reset to 25000, honba
  and riichi sticks start at 0 (no multi-kyoku session).
- Not implemented: red fives, nagashi mangan, renhou, pao, south rounds,
  chuuren/ryuuiisou yakuman.
- Ron is auto-accepted (declining a ron is not modelled).

## Architecture

```
mahjong_mc/
  tiles.py     tile encoding (0-33), count vectors, shuffled wall
  rules.py     is_win / shanten / ukeire (cached per-suit profile engine)
  engine.py    Game, Rules, View — deterministic 4-player Japanese-rules loop
  scoring.py   yaku / han / fu / points (score_hand)
  policies.py  Policy base class, registry, random / greedy / defensive
  mc.py        Monte Carlo runner + CLI (multiprocessing, JSON export)
  play.py      interactive terminal mode (human seat)
my_strategies/ your own strategies (auto-loaded by the CLI)
tests/         68 unit tests: scoring, rules, engine, play, MC statistics
examples/      compare_strategies.py — head-to-head matchups
```

Design notes:

- Everything is **deterministic given the seed**: same seed → same game, so
  parallel chunks are reproducible and serial/parallel runs agree exactly.
- The engine enforces invariants: all 136 tiles are always accounted for
  (live wall + dead wall + hands + melds + discards), illegal discards
  raise, and a turn cap ends pathological call loops as a draw.
- `shanten` decomposes per suit and caches profiles; this is what makes
  ~200 games/s possible in pure Python.
- Results aggregate per seat in the worker processes (O(1) memory), so a
  1,000,000-game run streams counters instead of storing every game.

## The evolved "GTO" strategy

True GTO is out of reach for 4-player mahjong, but the strategy space is
searchable: `examples/evolve.py` runs an evolutionary search over a
parameterized family (`examples/evolved_strategy.py`) — population, fitness
against a fixed reference field, elites survive, mutated copies replace the
rest. The winner is written to **`my_strategies/gto.py`**:

    python3 -m examples.evolve --population 8 --generations 8 --games 2000

Current champion (evolved, seed 42, 939 pts/game in training):

```
seat policy          win%   tumo%    ron%  deal-in%  riichi%  pts/game
   0 gto           25.64%   5.98%  19.66%     7.84%   47.66%     729.8
   1 greedy        19.56%   4.62%  14.94%    12.78%   14.76%     525.6
   2 safety        20.94%   5.72%  15.22%    11.20%   14.04%     693.6
```

(5,000 games, seed 42.) The winner's shape: never calls (pure menzen —
riichi + menzen tsumo + possible chinitsu/honitsu beat the value of cheap
melds), high safety weight on discards, riichi almost always (but not
against an opponent who already riichi'd), honor pairs kept for yakuhai.
It also beat three defensive players head-to-head (21.5% / +113 pts), so it
is not just exploiting the training field.

Note its `avg rank` can trail lower-variance strategies — a 48% riichi rate
means bigger wins AND bigger losses; `pts/game` is the fairer metric here.

## Playing online: RiichiLab (riichi.dev)

> mjai.app was retired on 2026-04-30. Its successor, **RiichiLab**, is the
> live bot arena — GitHub login, bot tokens, OpenSkill leaderboard.

RiichiLab speaks MJAI over **WebSocket** (not stdin/stdout): the server
streams standard MJAI events, prompts with `request_action`, and expects
one action back echoing the `request_id` (3 s grace + 15 s bank per
kyoku; invalid actions are chombo). The driver is zero-dependency
(stdlib socket+ssl):

```bash
# 1. register: sign in at https://riichi.dev/bots with GitHub, create a
#    bot, copy the token (shown once)
# 2. validate (one game vs 3 tsumogiri bots, seat 0)
python3 -m mahjong_mc.riichi_ws --validate --token <TOKEN>
# 3. ranked play — the bot stays queued and plays continuously
python3 -m mahjong_mc.riichi_ws --token <TOKEN> --policy gto
```

Options: `--policy NAME` (any `my_strategies/` name), `--games N` (stop
after N), `--seed N`, `--url` (override), or set `RIICHI_TOKEN` instead
of `--token`. Strategies work unchanged: `MjaiBot` in reactive mode keeps
all state from the echoed event stream (opponents' hands/draws arrive
masked as `"?"`), and every reply is validated against `possible_actions`
with a legal fallback so the bot can never send a chombo action.
Measured decision latency: ~0.3 ms (budget 3 s).

## Playing on Tenhou / other mjai bridges

The stdin/stdout mjai adapter still serves Tenhou-style bridges
(kobalab mjai-bridge, Akagi):

```bash
python3 mjai_bot.py <player_id> [policy_name] [policy_file]
# e.g.
python3 mjai_bot.py 0 gto
python3 mjai_bot.py 1 mine my_strategies/mine.py
```

It reads mjai JSONL events on stdin and writes actions on stdout;
strategies in `my_strategies/` are auto-loaded like the CLI. `MjaiView`
mimics the engine's `View` API, so every policy works unchanged.

Verify it without a server:

```bash
python3 -m examples.mjai_selftest     # scripted kyoku: reach, ron, furiten, kans
python3 -m unittest tests.test_mjai   # unit tests incl. the real subprocess entry point
```

**Watch it play locally** (no server needed) — the bot at seat 0 fights
three engine policies through the real mjai event protocol:

```bash
python3 -m examples.mjai_demo --games 500 --policy gto --field greedy,defensive,random
```

Results print in the same win%/pts table as the Monte Carlo runner.
Approximation: dora indicators aren't visible through the engine View, so
the bot's dora count reads 0 (no shipped policy reads dora_count).

Where to run it:

- **mjai.app** (AI contest platform): native `python bot.py <player_id>`
- **kobalab 電脳麻将** (local server): `mjai-bridge -r <room> -n <name> <url> mjai_bot.py`
- **Tenhou**: needs an mjai client ID and a private room — bot play in
  ranked games violates Tenhou's terms

Limitation: mjai only feeds events; opponent hand reading (danger
estimation) is not provided by the protocol, so defensive strategies are
weaker on Tenhou than in self-play.

## Writing your own strategy

Drop a `.py` file into **`my_strategies/`** — it is auto-loaded, no flags
needed:

```bash
# 1. edit my_strategies/mine.py (a working greedy+early-discard policy)
# 2. run it head-to-head, any number of games:
python3 -m mahjong_mc --games 100000 --policies mine,greedy,random,random --workers 8
```

Every `Policy` subclass with a `name` in `my_strategies/*.py` becomes
available to `--policies` (also works with `--policy-file PATH` for a
one-off file outside the directory). The template's full API surface:

```python
view.hand           tuple of concealed tile ids you hold
view.counts         concealed hand as a 34-length count list
view.total_counts   your full holding incl. melds
view.melds          your melds: list of (tiles, kind)
view.discards       per-seat tuples of discarded tiles
view.melds_all      per-seat melds (all players)
view.unseen_counts  copies possibly still in wall / opponents' hands
view.wall_left      tiles left in the live wall
view.dealer         the oya seat
view.points         per-seat points
view.riichi         per-seat riichi flags
view.can_riichi     you may declare riichi right now
view.dora_count     visible dora in your holding
view.last_drawn     the tile you just drew
```

Policy hooks: `choose_discard(view) -> tile id`,
`decide_call(view, tile, options) -> option or None`,
`decide_riichi(view) -> bool`,
`decide_kan(view, tile, options) -> option or None`.

Or from Python:

```python
from mahjong_mc.mc import run_batch, print_table

stats = run_batch(50_000, ["mine", "greedy", "random", "random"],
                  seed=0, workers=8)
print_table(stats)
```

## Play it yourself (interactive mode)

One human seat against three AI strategies, in the terminal:

```bash
python3 -m mahjong_mc.play                                   # you vs greedy/defensive/random
python3 -m mahjong_mc.play --policies greedy,human,random,random --no-hints
```

You sit wherever `human` appears in `--policies`. At each discard prompt you
see your hand (numbered), a `discard→shanten` hint line, everyone's melds and
discards, the wall count and dora. AI moves are narrated live:

```
Your hand (14 tiles):
  [1]3m [2]4m [3]6m [4]7m [5]2p [6]3p [7]1s [8]2s [9]3s [10]5s [11]7s [12]南 [13]北 [14]中
  discard→shanten:  3m→4  4m→4  6m→4  7m→4  2p→4  3p→4  1s→4  2s→5  3s→4  5s→3  7s→3  南→3  北→3  中→3
Table:
  You     (oya) melds: -              discards: -
  ...
Discard> 1
  South discards 1p
  West discards 8m
  North calls chi on 8m
```

Input: a tile (`5m`, `东`), its number (`[3]`), `h` for help, `q` to quit.
Riichi and kan decisions are prompted when available. After the game the
winning hand with its yaku/han/fu breakdown is shown, and you can play again.

## CLI reference

All commands run from `~/coding/mahjong-mc`.

### 1. Monte Carlo runner — `python3 -m mahjong_mc`

```
--games N            int, default 1000. Number of games (you choose the scale).
--policies a,b,c,d   REQUIRED. Exactly 4 comma-separated policy names.
                     Built-in: random, greedy, defensive.
                     Auto-loaded from my_strategies/: mine, safety, gto.
--seed N             int, default 0. Game i uses seed+i (fully reproducible).
--workers N          int, default 0 = all CPU cores. Parallel processes.
--no-chi             disable chi calls.
--no-peng            disable peng calls.
--no-kan             disable all kans.
--json PATH          also write the full stats as JSON.
--policy-file PATH   load extra policies from one .py file.
--policy-dir DIR     load policies from a directory of .py files
                     (default: my_strategies/ next to the project root).
```

Example: `python3 -m mahjong_mc --games 100000 --policies gto,greedy,safety,random --workers 8 --seed 42`

### 2. Interactive play — `python3 -m mahjong_mc.play`

```
--policies a,b,c,d   default "human,greedy,defensive,random".
                     Exactly one name must be `human` — that is your seat.
--seed N             default None (random game). Fix it to replay a deal.
--no-hints           hide the discard→shanten hint line.
```

In-game input:
- discard: `5m` / `1p` / `9s` / `东` (tile), `[3]` (hand number), `h` help, `q` quit
- call menu: number, the call name (`peng`/`chi`/`minkan`/`shouminkan`), or `0` pass
- riichi prompt: `y` / `n` (empty = no), `q` quit
- kan prompt: number, the kan name (`ankan`/`shouminkan`), or `0` no kan
- between games: `y` play again / anything else exits

### 3. Evolution search — `python3 -m examples.evolve`

```
--population N       int, default 8. Variants per generation.
--generations N      int, default 8. Generations to run.
--games N            int, default 2000. Games per variant per generation.
--seed N             int, default 0. Base seed (each generation derives its
                     own paired seeds from it).
--workers N          int, default 0 = all cores.
--out PATH           default my_strategies/gto.py. Where the winner is written.
```

Rough runtime: population × generations × games / ~200 games/s. The default
(8 × 8 × 2000) takes ~8 minutes on 8 cores.

### Strategy parameter sweep

The `safety` policy reads one env var:

```
MJ_SAFETY=w   float, default 1.0. Discard safety weight (0 = pure greedy).
```

Example:
```
for w in 0 1 2 4; do
  MJ_SAFETY=$w python3 -m mahjong_mc --games 20000 \
      --policies safety,greedy,random,random --workers 8 --seed 7
done
```

### Python API

```python
from mahjong_mc.mc import run_batch, run_game, print_table
from mahjong_mc.play import play_game

stats = run_batch(50_000, ["gto", "greedy", "random", "random"],
                  seed=0, workers=8, policy_file="my_strategies/gto.py")
print_table(stats)

res = run_game(["greedy"] * 4, seed=1)   # one game, result dict

game = play_game(["human", "greedy", "random", "random"],
                 seed=3, hints=False)     # interactive, returns Game or None
```

## Testing

```bash
python3 -m unittest discover -s tests -v
```

Covers: scoring on known hands (chiitoitsu, tanyao, chinitsu, yakuman,
mangan, kan fu, dora, no-yaku-is-not-a-win), win detection incl. melds and
kans, shanten values, ukeire, tile conservation over many games,
determinism, parallel == serial, riichi/kan/call bookkeeping, and the
interactive mode.
