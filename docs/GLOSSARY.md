# Glossary — Japanese Mahjong terms in English

Every term and tile name this project uses, with the Japanese form, the
romaji the code already uses, and the English name. Where the codebase's
string is Chinese rather than Japanese (the honour-tile names, and a few
README comments), both are given.

Rule of thumb for the English column: yaku and game terms are usually left
in romaji in English-language mahjong literature (riichi, furiten, tenpai).
The "English name" below is what an English rules sheet or wiki calls it.

## 1. Tiles (牌 / パイ)

### Suits

| Code | Japanese | Romaji | English name | Nickname |
|---|---|---|---|---|
| m | 萬子 | manzu | characters / character tiles | "man", "craks" |
| p | 筒子 | pinzu | circles / dot tiles | "pin", "dots", "balls" |
| s | 索子 | souzu | bamboos / bamboo tiles | "sou", "bams" |
| z | 字牌 | jihai | honour tiles | "honors", "winds & dragons" |

Tile notation `5m` = 5 of characters; `1p` = 1 of circles; `9s` = 9 of
bamboo. In Japanese romaji notation these are `5m / 1p / 9s` too
(man / pin / sou).

### Honour tiles (字牌, 7 kinds)

| Code | Code string (Chinese) | Japanese | Romaji | English name |
|---|---|---|---|---|
| 27 | 东 | 東 | ton / higashi | East wind |
| 28 | 南 | 南 | nan / minami | South wind |
| 29 | 西 | 西 | shaa / nishi | West wind |
| 30 | 北 | 北 | pee / kita | North wind |
| 31 | 白 | 白 | haku | White dragon (haku) |
| 32 | 发 | 發 | hatsu | Green dragon (hatsu) |
| 33 | 中 | 中 | chun | Red dragon (chun) |

Winds = 風牌 (fuuhai, "wind tiles"); dragons = 三元牌 (sangenpai,
"dragon tiles"). In mjai the seven honours are `E S W N P F C`.

### Winds have two kinds of role — don't mix them up

| Japanese | Romaji | English name | Meaning |
|---|---|---|---|
| 場風 | bakaze | round wind / prevalent wind | the wind of the current round (East round, South round…); same for all four players |
| 自風 | jikaze | seat wind | the wind of your own seat; the dealer is East, then South, West, North going round |
| 圏風 | kengi / bakaze | (variant word for round wind) | rarely used; same thing |

Both are only "value winds" when they match a triplet you hold. A wind that
is neither is worthless:

| Japanese | Romaji | English name | Meaning |
|---|---|---|---|
| 役牌 | yakuhai | value wind | seat wind or round wind triplet → 1 han each |
| 連風牌 / ダブ東 | renpuuhai / dabuton | double wind | a wind that is both seat and round wind → 2 han |
| 客風牌 / オタ風 | kyakufuuhai / otakaze | guest wind ("ota-kaze") | wind matching neither; no yaku, no pair fu |
| 風牌の雀頭 | fuuhai no jantou | wind pair | pair of a value wind → +2 fu |

Code: `score_hand(..., prevalent_wind=...)` and the derived
`seat_wind = (seat - dealer) % 4`. Both are hard-coded to East round
(`prevalent_wind=0`) everywhere it is called, so this engine only ever
plays 東風戦 (East round) — no South round yet, as the README says.


### Tile groups

| Japanese | Romaji | English name | Meaning |
|---|---|---|---|
| 数牌 | suuhai | suited tile / number tile | 1-9 in the three suits |
| 老頭牌 | routouhai | terminal | 1 or 9 |
| 中張牌 | chuuchanpai | simple tile | 2-8 |
| 么九牌 | yaochuuhai | terminal-or-honour ("yaochuu") | 1, 9, or any honour |
| 幺九牌 | — | same as above (Chinese form used in the README) | |
| 赤ドラ | aka dora | red five | one red 5 per suit (not implemented here) |
| 花牌 | hanahai | flower tile | Chinese rules only, not used in riichi |

## 2. Yaku (役) — hand patterns

Han in brackets: (closed / open). "Closed" = menzen 門前.

### Situational (1 han each)

| Romaji in code | Japanese | English name |
|---|---|---|
| riichi | 立直 | riichi — declared ready hand, 1000-point stick |
| ippatsu | 一発 | one-shot — win in the turn after riichi |
| menzen tsumo | 門前清自摸和 | fully concealed self-draw |
| rinshan (kaihou) | 嶺上開花 | after a kan — win on the dead-wall replacement tile |
| chankan | 搶槓 | robbing a kan — ron on an added kan |
| haitei (raoyue) | 海底撈月 | last tile — self-draw on the final wall tile |
| houtei (raoyui) | 河底撈魚 | last discard — ron on the final discard |

### Structure

| Romaji | Japanese | English name | Han |
|---|---|---|---|
| pinfu | 平和 | all sequences, no value | 1 |
| tanyao | 断幺九 | all simples (no terminals/honours) | 1 |
| yakuhai | 役牌 | value honour triplet (dragon, seat wind, round wind) | 1 each |
| iipeikou | 一盃口 | pure double sequence | 1 (closed) |
| chanta | 混全帯幺九 | mixed outside hand — every set has a terminal/honour | 2 / 1 |
| junchan | 純全帯幺九 | pure outside hand — every set has a terminal | 3 / 2 |
| itsuu | 一気通貫 | straight — 123-456-789 in one suit | 2 / 1 |
| sanshoku (doujun) | 三色同順 | three-colour straight | 2 / 1 |
| sanshoku doukou | 三色同刻 | three-colour triplets | 2 |
| sanankou | 三暗刻 | three concealed triplets | 2 |
| sankantsu | 三槓子 | three kans | 2 |
| toitoi | 対々和 | all triplets | 2 |
| chiitoitsu | 七対子 | seven pairs | 2 |
| honroutou | 混老頭 | all terminals and honours | 2 |
| shousangen | 小三元 | little three dragons | 2 |
| honitsu | 混一色 | half flush — one suit + honours | 3 / 2 |
| chinitsu | 清一色 | full flush — one suit only | 6 / 5 |
| ryanpeikou | 二盃口 | twice pure double sequence | 3 (closed) |

### Yakuman (役満)

| Romaji | Japanese | English name |
|---|---|---|
| chiiniisou | 字一色 | all honours |
| chinroutou | 清老頭 | all terminals |
| daisangen | 大三元 | big three dragons |
| shousuushii | 小四喜 | little four winds |
| suuankou | 四暗刻 | four concealed triplets |
| suukantsu | 四槓子 | four kans |
| kazoe yakuman | 数え役満 | counted yakuman — 13+ han without a yakuman pattern |

(Yakuman not implemented here: 九蓮宝燈 chuuren poutou "nine gates",
緑一色 ryuuiisou "all green", 国士無双 kokushi musou "thirteen orphans",
天和/地和 tenhou/chiihou "heavenly/earthly hand", 四暗刻単騎 suuankou tanki
"single-wait four concealed triplets", 大四喜 daisuushii "big four winds".)

### Limits (点数上限)

| Romaji | Japanese | English name | Han |
|---|---|---|---|
| mangan | 満貫 | mangan (capped hand) | 5, or 4 han 40+ fu, 3 han 70+ fu |
| haneman | 跳満 | haneman | 6-7 |
| baiman | 倍満 | baiman | 8-10 |
| sanbaiman | 三倍満 | sanbaiman | 11-12 |
| yakuman | 役満 | yakuman | 13+, or a yakuman pattern |

## 3. Fu (符)

| Japanese | Romaji | English name | Value |
|---|---|---|---|
| 副底 | futei | base | 20 |
| 門前清栄和加符 | menzen ron kafu | closed ron bonus | +10 |
| 自摸符 | tsumo fu | self-draw fu | +2 (this repo models it as +10 on non-pinfu tsumo) |
| 待ち符 | machi fu | wait fu | +2 for kanchan / penchan / tanki |
| 刻子符 | koutsu fu | triplet fu | 2/4 open, 4/8 closed (simple / terminal-honour) |
| 槓子符 | kantsu fu | kan fu | 8/16 open, 16/32 closed |
| 雀頭符 | jantou fu | pair fu | +2 for dragons, seat wind, round wind |
| 七対子 | chiitoitsu | seven pairs | fixed 25 |
| 平和自摸 | pinfu tsumo | pinfu self-draw | fixed 20 |
| 喰い平和 | kui pinfu | open all-sequence hand | fixed 30 |

Fu is rounded up to the next 10 (切り上げ, kiriage).

## 4. Shape and wait names

| Japanese | Romaji | English name | Meaning |
|---|---|---|---|
| 面子 | mentsu | meld / set | run or triplet |
| 順子 | juntsu | sequence / run | e.g. 2-3-4 |
| 刻子 | koutsu | triplet | three of a kind |
| 槓子 | kantsu | kan / quad | four of a kind |
| 雀頭 | jantou | pair / head | the two-tile pair |
| 両面 | ryanmen | two-sided wait | e.g. 23 waiting 1-4 |
| 嵌張 | kanchan | closed wait | e.g. 24 waiting 3 |
| 辺張 | penchan | edge wait | 12 waiting 3, 89 waiting 7 |
| 単騎 | tanki | pair wait | waiting for the pair |
| 双碰 | shanpon | twin-pair wait | two triplets, either completes |
| 延べ単 | nobetan | stretch wait | ryanmen + tanki on the drawn tile |
| 一向聴 | ishanten | one-shanten (1 away from tenpai) | |
| 向聴 | shanten | shanten number / "distance to ready" | the hint line's `discard→shanten` |
| 有効牌 | yuukouhai | ukeire / effective tile | a draw that improves shanten |
| 聴牌 | tenpai | ready hand | one tile from a win |
| 不聴 | noten | not ready | |
| 振聴 | furiten | furiten — cannot ron | |
| 同巡振聴 | doujun furiten | temporary furiten | until your next draw |
| 捨て牌振聴 | sutehai furiten | permanent furiten | any of your discards is a winning tile |
| 立直振聴 | riichi furiten | riichi furiten | missed the ron after riichi |
| 黙聴 | damaten | silent ready hand (no riichi) | |

## 5. Calls, kans and meld kinds

| Romaji in code | Japanese | English name |
|---|---|---|
| chi | チー | chi — call a sequence (left player only) |
| peng / pon | ポン | pon — call a triplet |
| minkan / daiminkan | 大明槓 | open kan — kan by calling a discard |
| ankan | 暗槓 | closed kan — four in hand, declared |
| shouminkan / kakan | 小明槓 / 加槓 | added kan — fourth tile added to a pon |
| concealed | — | closed meld (in hand, not called) |
| tsumogiri | ツモ切り | discard the tile you just drew |
| tedashi | 手出し | discard from the hand (not the drawn tile) |
| furiten ron | 振聴ロン | a ron that is illegal under furiten |
| chombo | 錯和 / チョンボ | chombo — dead-hand penalty for an illegal win |

## 5b. Dora family (ドラ)

Dora is not a yaku — it adds han to a hand that already has one. "Dora" is
short for ドラ牌 "bonus tile"; the tile that *makes* the bonus is the
indicator, and the actual dora is the next tile in sequence (9m→1m,
North→East, Chun→Haku — `dora_next()` in scoring.py).

| Japanese | Romaji | English name | Where it lives |
|---|---|---|---|
| ドラ | dora | dora / bonus tile | +1 han per copy in your finished hand |
| ドラ表示牌 | dora hyoujipai | dora indicator | face-up in the dead wall (王牌 wanpai) |
| 裏ドラ | ura dora | hidden dora (under-dora) | stacked under the indicator, face-down; counts only if you win after riichi |
| 裏ドラ表示牌 | ura dora hyoujipai | hidden dora indicator | the facedown tile beneath the dora indicator |
| 槓ドラ | kan dora | kan dora ("flipped" dora) | a new indicator revealed after each kan (up to 5 total in a hand) |
| 裏槓ドラ | ura kan dora | hidden kan dora | its face-down partner |
| ドラ捲り | dora mekuri | dora flip | the act of revealing a kan dora |
| 赤ドラ | aka dora | red five | one red 5 in each suit, always worth 1 han (not implemented here) |
| 白ポッチ | shiro pocchi | white-dragon joker | niche local rule: the white dragon as an extra dora (not here) |
| ドラ数 | dora suu | dora count | `view.dora_count` — visible dora in your holding |

Related, not dora: オープン立直 open riichi, and `honba` 本場 which is a
point bonus, not a han bonus.

## 6. Round, table and scoring terms

| Japanese | Romaji | English name | Meaning |
|---|---|---|---|
| 局 | kyoku | hand / round | one deal; this repo plays one independent kyoku per game |
| 東風戦 / 半荘 | tonpuusen / hanchan | east-only game / full game | |
| 親 | oya | dealer | seat 0, pays and receives 1.5x |
| 子 | ko | non-dealer | |
| 自風 | jikaze | seat wind | |
| 場風 | bakaze | round wind / prevalent wind | |
| 本場 | honba | honba counter (repeat stick) | +300 ron, +100 per payer on tsumo |
| 供託 | kyoukyaku | riichi sticks on the table | go to the winner |
| 点棒 | tenbou | point sticks | |
| 符 | fu | fu (hand value minor unit) | |
| 飜 / 翻 | han | han (hand value unit) | |
| 流局 | ryuukyoku | exhaustive draw / abortive draw | |
| 荒牌流局 | arahai ryuukyoku | exhaustive draw (wall emptied) | |
| 不聴罰符 | noten bappu | noten penalty | 3000 total from noten to tenpai |
| 聴牌罰符 | — | (non-standard term; the README means noten bappu) | |
| 飛び | tobi | bust / bankruptcy | game ends at negative points |
| 牌山 | yama | wall | 136 tiles |
| 王牌 | wanpai | dead wall | 14 tiles, holds dora indicators |
| 海底 | haitei | last live-wall tile | |
| 嶺上牌 | rinshanpai | dead-wall replacement tile | drawn after a kan |
| 安牌 | anpai | safe tile | cannot be ron'd |
| 危険牌 | kikenpai | dangerous tile | |
| 筋 | suji | suji ("line") | discarded 4 ⇒ 1 and 7 are safer |
| 現物 | genbutsu | genbutsu | a tile already discarded by that player |
| 生牌 | nama / namahai | fresh tile / live tile | unseen, can be claimed |
| 押し引き | oshi-hiki | push-fold decision | |
| ベタ降り | beta ori | full fold | |
| 牌効率 | hai kouritsu | tile efficiency | what `shanten`/`ukeire` measure |
| 打点 | daten | hand value | |
| 和了 | hoora / agari | win | |
| 栄和 | ron | ron — win on a discard | |
| 自摸 | tsumo | tsumo — win on your own draw | |
| 放銃 | houjuu | deal-in | `deal-in%` |
| 放銃率 | houjuuritsu | deal-in rate | `deal-in%` |
| 和了率 | hooraritsu | win rate | `win%` |
| 立直率 | riichiritsu | riichi rate | `riichi%` |
| 平均順位 | heikin junni | average placing | `avg rank` |
| 天鳳 | tenhou | Tenhou | the online server |
| 電脳麻将 | dennou maajan | "Cyber Mahjong" | kobalab's local mjai server |

## 7. Notes on this codebase's strings

- `tiles.HONOR_NAMES = "东南西北白发中"` is simplified Chinese, not kanji:
  Japanese is `東南西北白發中`. Display only — the ids and logic are
  unaffected.
- `SEAT_NAMES = ("East", "South", "West", "North")` already uses English
  wind names, and `play.py` prints "oya" and "[riichi]" as-is.
- Yaku and yakuman names returned by `score_hand()` are romaji
  (`"riichi"`, `"chinitsu"`, `"daisangen"`, `"kazoe yakuman"`).
- `README.md` mixes terms: `tumo%` is tsumo, `minkan` is often printed as
  `daiminkan` elsewhere, and `听牌罚符` should read `noten bappu`.
