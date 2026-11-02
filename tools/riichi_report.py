#!/usr/bin/env python3
"""Daily digest for the RiichiLab bot (Louis / bot 457).

Reads only the public API — it never connects as a bot, so it can run while the
service is playing. Prints markdown; optionally writes it into
docs/reports/YYYY-MM-DD.md.

    python3 tools/riichi_report.py                 # today (locale date)
    python3 tools/riichi_report.py --date 2026-10-31
    python3 tools/riichi_report.py --write         # also save under docs/reports/
    python3 tools/riichi_report.py --days 7        # last 7 days summary
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.parse

BOT_ID = 457
API = os.environ.get("RIICHI_API", "https://api.riichi.dev/api/v1")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Wall-clock budget for all API work in one run. `riichi status` is meant to
# print and quit: once the budget is gone we print whatever we have instead of
# sitting in curl timeouts. Override with --deadline / RIICHI_DEADLINE.
DEADLINE = None
CURL_MAX = 25


def _remaining():
    if DEADLINE is None:
        return CURL_MAX
    return DEADLINE - time.monotonic()


def _get(path, attempts=3, optional=False):
    last = ""
    for i in range(attempts):
        budget = _remaining()
        if budget < 2:
            last = "no time left"
            break
        out = subprocess.run(
            ["curl", "-s", "-m", f"{min(CURL_MAX, budget):.1f}",
             "-A", "Mozilla/5.0",
             "-w", "\n%{http_code}", f"{API}/{path}"],
            capture_output=True, text=True)
        body, _, code = out.stdout.rpartition("\n")
        if out.returncode == 0 and code.strip() == "200" and body.strip():
            return json.loads(body)
        last = (f"curl exit {out.returncode}, http {code.strip() or '?'}, "
                f"{body[:120]!r}")
        if _remaining() < 4:
            break
        time.sleep(min(1.5 * (i + 1), max(0.0, _remaining() - 1)))
    msg = f"API request failed: {path} ({last})"
    if optional:
        return None
    raise SystemExit(msg)


# The site's own league: the leaderboard, and the rank printed on a bot page,
# are both computed over bots active in the last 2 months (?activity=2m). Asking
# for that window is what makes our rank agree with the web page; the default
# (all-time) board is ~110 places worse.
ACTIVITY = "2m"

# The games endpoint caps a page at 50 no matter what limit says, and pages by
# cursor. Anything that wants more than "the newest 50" has to walk them.
PAGE = 50


def bot():
    payload = _get(f"bots/{BOT_ID}?activity={ACTIVITY}")
    assert payload is not None
    return payload["data"]


def games(limit=PAGE, max_games=1000, stop_before=None):
    """Newest games, walking the cursor. Stops at `stop_before` (a local date).

    Returns (games, total) where total is the API's count of all games.
    """
    out, cursor, total = [], None, None
    while len(out) < max_games:
        path = f"bots/{BOT_ID}/games?limit={limit}"
        if cursor:
            path += "&cursor=" + urllib.parse.quote(cursor)
        payload = _get(path)
        assert payload is not None
        data = payload["data"]
        total = data.get("total", total)
        page = data.get("games") or []
        out += page
        if stop_before is not None:
            stamps = [_local(g["played_at"]) for g in page]
            oldest = min((t for t in stamps if t), default=None)
            if oldest is not None and oldest.date() < stop_before:
                break
        if not page or not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return out, total


def live():
    """Rating and game count as of the newest game.

    `bots/<id>` is a periodically rebuilt projection and can trail the games
    feed by several minutes (observed: it reported 1519 while the newest game
    already left us on 1535). The games list is always current, so the rating
    is recomputed from rating_before + rating_delta of the newest game.
    """
    payload = _get(f"bots/{BOT_ID}/games?limit=1", optional=True)
    data = (payload or {}).get("data") or {}
    gs = data.get("games") or []
    if not gs:
        return None
    g = gs[0]
    before = g.get("rating_before")
    if before is None:
        return None
    return {"rating": before + (g.get("rating_delta") or 0),
            "game": g, "total": data.get("total")}


def leaderboard_rows(optional=False, activity=ACTIVITY):
    rows, off = [], 0
    while True:
        payload = _get(f"leaderboard?limit=100&offset={off}&activity={activity}",
                       optional=optional)
        page = (payload or {}).get("data") if payload is not None else None
        if page is None or not page:
            break
        rows += page
        off += len(page)
        if len(page) < 100:
            break
    return rows


def position(rating, rows):
    """Leaderboard position for a rating (1 = best)."""
    return 1 + sum(1 for r in rows if r["rating"] > rating)


def rank_of(field=None, direction=-1):
    """Current leaderboard position of our rating."""
    rows = leaderboard_rows()
    mine = next((r for r in rows if r["bot_id"] == BOT_ID), None)
    return position(mine["rating"] if mine else 0, rows), len(rows)


UTC = dt.timezone.utc


def _local(stamp):
    """API timestamps are UTC without a suffix; return local time."""
    try:
        return dt.datetime.fromisoformat(stamp).replace(
            tzinfo=UTC).astimezone()
    except ValueError:
        return None


def _fmt_score(n):
    """Scores never carry a '+'; only the minus is informative."""
    return f"-{abs(n)}" if n < 0 else f"{n}"


def _fmt_delta(n):
    if n == 0:
        return "0"
    return f"-{abs(n)}" if n < 0 else f"+{n}"


def _pad(text, width, align):
    if align == "r":
        return text.rjust(width)
    if align == "c":
        return text.center(width)
    return text.ljust(width)


def _osc8(text, url):
    return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\"


def _render_table(header, rows, align=None, href_col=None, hrefs=None):
    """Box-drawn table on a terminal, markdown pipe table when piped.

    --write saves markdown, so the pipes are the file format; a live run gets
    grid lines. The game-id column is clickable (OSC 8) when the terminal
    supports it.
    """
    align = align or ["l"] * len(header)
    widths = [len(h) for h in header]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))
    tty = sys.stdout.isatty()
    out = []
    if tty:
        rule = lambda l, m, rr: l + m.join("\u2500" * (w + 2)
                                          for w in widths) + rr
        out.append(rule("\u250c", "\u252c", "\u2510"))
        out.append("\u2502" + "\u2502".join(
            f" {_pad(h, widths[i], align[i])} "
            for i, h in enumerate(header)) + "\u2502")
        out.append(rule("\u251c", "\u253c", "\u2524"))
        for idx, r in enumerate(rows):
            cells = []
            for i, cell in enumerate(r):
                text = _pad(cell, widths[i], align[i])
                if href_col is not None and i == href_col and hrefs:
                    text = _osc8(text, hrefs[idx])
                cells.append(f" {text} ")
            out.append("\u2502" + "\u2502".join(cells) + "\u2502")
        out.append(rule("\u2514", "\u2534", "\u2518"))
    else:
        out.append("| " + " | ".join(header) + " |")
        out.append("| " + " | ".join("---:" if a == "r" else ":---"
                                     for a in align) + " |")
        for idx, r in enumerate(rows):
            cells = []
            for i, cell in enumerate(r):
                if href_col is not None and i == href_col and hrefs:
                    cells.append(f"[{cell}]({hrefs[idx]})")
                else:
                    cells.append(cell)
            out.append("| " + " | ".join(cells) + " |")
    return out


def digest(date_str=None, days=1):
    d = bot()
    if date_str:
        cutoff = dt.date.fromisoformat(date_str)
        label = date_str
    else:
        cutoff = dt.date.today() - dt.timedelta(days=days - 1)
        label = "today" if days == 1 else f"last {days} days"

    # walk cursor pages until the whole window is covered (50 games a page)
    gs, total = games(stop_before=cutoff)
    truncated = len(gs) >= 1000
    local_games = [(g, _local(g["played_at"])) for g in gs]
    if date_str:
        sel = [(g, t) for g, t in local_games
               if t and t.date().isoformat() == date_str]
    else:
        sel = [(g, t) for g, t in local_games if t and t.date() >= cutoff]
    sel.sort(key=lambda x: x[1], reverse=True)

    ranks = [0, 0, 0, 0]
    dcs = pens = 0
    for g, _ in sel:
        if 1 <= g["rank"] <= 4:
            ranks[g["rank"] - 1] += 1
        if g.get("is_disconnected"):
            dcs += 1
        if g.get("is_penalized"):
            pens += 1
    delta = sum(g.get("rating_delta") or 0 for g, _ in sel)
    # rating as of the newest game; the bot projection lags minutes behind
    lv = live() or {}
    rating = lv.get("rating", d.get("rating"))
    rows = leaderboard_rows(optional=True) or []
    # the site's rank, over the same 2-month activity league
    rank = position(rating, rows) if rows else d.get("leaderboard_rank")
    if rank is None:
        rank_txt = "rank ?"
    elif rows:
        rank_txt = f"#{rank} of {len(rows)}"
    else:
        rank_txt = f"#{rank}"
    # rank at the start of the period = where the rating before the oldest
    # selected game would sit on the same board
    rank_move = None
    if sel and rows and rank is not None:
        oldest = min(sel, key=lambda x: x[1])[0]
        start_rating = oldest.get("rating_before")
        if start_rating is not None:
            rank_move = position(start_rating, rows) - rank

    lines = []
    lines.append(f"RiichiLab \u00b7 louis \u00b7 {label}")
    lines.append("")
    if sel:
        scores = [g["score"] for g, _ in sel]
        best = max(sel, key=lambda x: x[0]["score"])
        flags = []
        if dcs:
            flags.append(f"{dcs} disconnected")
        if pens:
            flags.append(f"{pens} penalised")
        lines.append(f"games {len(sel)}  ·  1st {ranks[0]}  2nd {ranks[1]}  "
                     f"3rd {ranks[2]}  4th {ranks[3]}"
                     + (("  ·  " + "  ·  ".join(flags)) if flags else "")
                     + ("  ·  truncated at 1000, use --days" if truncated
                        else ""))
        move = ""
        if rank_move:
            move = (f"  (\u25b2{rank_move} this period)" if rank_move > 0
                    else f"  (\u25bc{-rank_move} this period)")
        lines.append(f"rating {rating} ({delta:+d} this period)  \u00b7  "
                     f"{rank_txt}{move}  \u00b7  "
                     f"lifetime games {total or d['total_games']}")
        avg_rank = sum(g["rank"] for g, _ in sel) / len(sel)
        lines.append(f"avg rank {avg_rank:.2f}  \u00b7  "
                     f"top-2 finishes {100*(ranks[0]+ranks[1])/len(sel):.0f}%")
        lines.append(f"avg score {_fmt_score(round(sum(scores)/len(scores)))}"
                     f"  \u00b7  best {_fmt_score(best[0]['score'])}"
                     f" ({best[1].strftime('%H:%M')})"
                     f"  \u00b7  worst {_fmt_score(min(scores))}")
        lines.append("")
        lines.append("last games:")
        header = ["time", "rank", "score", "\u0394", "seat", "game", "note"]
        rows_t, hrefs = [], []
        for g, t in sel[:10]:
            note = "DC" if g.get("is_disconnected") else ""
            if g.get("is_penalized"):
                note = (note + " " if note else "") + "PEN"
            if g.get("game_type") and g["game_type"] != "ranked":
                note = (note + " " if note else "") + str(g["game_type"])
            rows_t.append([
                t.strftime("%m-%d %H:%M"),
                f"{g['rank']}{_ord(g['rank'])}",
                _fmt_score(g["score"]),
                _fmt_delta(g.get("rating_delta") or 0),
                str(g.get("seat", "")),
                str(g.get("game_id", ""))[:8],
                note,
            ])
            hrefs.append(f"https://riichi.dev/games/{g.get('game_id', '')}")
        lines += _render_table(header, rows_t,
                               align=["l", "r", "r", "r", "r", "l", "l"],
                               href_col=5, hrefs=hrefs)
    else:
        lines.append(f"no ranked game recorded for {label}.")
        lines.append(f"rating {rating}  \u00b7  {rank_txt}  \u00b7  "
                     f"lifetime games {total or d['total_games']}")

    lifetime = [d.get("total_1st") or 0, d.get("total_2nd") or 0,
                d.get("total_3rd") or 0, d.get("total_4th") or 0]
    n_life = sum(lifetime) or d.get("total_games") or 0
    if n_life:
        lines.append("")
        lines.append("lifetime finishes   "
                     + "   ".join(f"{i+1}st {100*lifetime[i]/n_life:.1f}%"
                                  if i == 0 else
                                  f"{i+1}{_ord(i+1)} {100*lifetime[i]/n_life:.1f}%"
                                  for i in range(4))
                     + f"   ({n_life} games)")

    a = d.get("aggregate_stats") or {}
    kyoku = a.get("total_kyoku") or 0
    if kyoku:
        lines.append("")
        lines.append(f"lifetime per-kyoku: agari {100*a['agari_count']/kyoku:.1f}%"
                     f"  deal-in {100*a['houju_count']/kyoku:.1f}%"
                     f"  riichi {100*a['riichi_count']/kyoku:.1f}%"
                     f"  ({kyoku} kyoku)")
    lines.append("")
    lines.append(f"bot https://riichi.dev/bots/{BOT_ID}"
                 f"  ·  leaderboard https://riichi.dev/leaderboard")
    return "\n".join(lines)


def _ord(n):
    return {1: "st", 2: "nd", 3: "rd"}.get(n, "th")


def brief():
    """Two lines for `riichi status`: rating, rank, and the newest game."""
    d = bot()
    lv = live() or {}
    rating = lv.get("rating", d.get("rating"))
    total = lv.get("total") or d.get("total_games")
    rank = d.get("leaderboard_rank")
    if rating != d.get("rating"):
        # the bot projection is behind; place the live rating on the board
        rows = leaderboard_rows(optional=True) or []
        if rows:
            rank = position(rating, rows)
    out = [f"rating {rating}  \u00b7  "
           + (f"#{rank}" if rank is not None else "rank ?")
           + f"  \u00b7  {total if total is not None else '?'} games"]
    if lv.get("game"):
        g = lv["game"]
        t = _local(g["played_at"])
        when = t.strftime("%m-%d %H:%M") if t else g["played_at"][:16]
        note = "  [DC]" if g.get("is_disconnected") else ""
        note += "  [PEN]" if g.get("is_penalized") else ""
        out.append(f"last  {when}  "
                   f"{g['rank']}{_ord(g['rank'])}  {_fmt_score(g['score'])}  "
                   f"({_fmt_delta(g.get('rating_delta') or 0)})  "
                   f"{str(g.get('game_id', ''))[:8]}{note}")
    return "\n".join(out)


def _env_file():
    """Read TELEGRAM_* out of ~/.hermes/.env without exporting anything."""
    vals = {}
    path = os.path.expanduser("~/.hermes/.env")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip("\"'")
    except OSError:
        pass
    return vals


def send_telegram(text):
    """Post the digest with the gateway's own Telegram bot. No LLM involved."""
    env = _env_file()
    token = env.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = env.get("TELEGRAM_HOME_CHANNEL") or os.environ.get(
        "TELEGRAM_HOME_CHANNEL")
    if not token or not chat:
        return False, "no TELEGRAM_BOT_TOKEN / TELEGRAM_HOME_CHANNEL found"
    out = subprocess.run(
        ["curl", "-s", "-m", "30", "-X", "POST",
         f"https://api.telegram.org/bot{token}/sendMessage",
         "--data-urlencode", f"chat_id={chat}",
         "--data-urlencode", f"text={text}"],
        capture_output=True, text=True)
    try:
        res = json.loads(out.stdout)
    except Exception:
        return False, f"telegram: unreadable reply {out.stdout[:120]!r}"
    return bool(res.get("ok")), ("sent" if res.get("ok")
                                 else f"telegram error: {res.get('description')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--write", action="store_true",
                    help="save to docs/reports/<date>.md")
    ap.add_argument("--telegram", action="store_true",
                    help="post the digest to Telegram (gateway bot token)")
    ap.add_argument("--brief", action="store_true",
                    help="two lines only: rating, rank, newest game "
                         "(what `riichi status` shows)")
    ap.add_argument("--deadline", type=float, default=None,
                    help="seconds of API work before giving up on slow calls "
                         "(default: RIICHI_DEADLINE or no limit)")
    args = ap.parse_args()

    global DEADLINE
    budget = args.deadline
    if budget is None and os.environ.get("RIICHI_DEADLINE"):
        budget = float(os.environ["RIICHI_DEADLINE"])
    if budget:
        DEADLINE = time.monotonic() + budget

    text = brief() if args.brief else digest(args.date, args.days)
    print(text)
    if args.write:
        day = args.date or dt.date.today().isoformat()
        out_dir = os.path.join(ROOT, "docs", "reports")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{day}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"<!-- generated {dt.datetime.now():%Y-%m-%d %H:%M} -->\n")
            f.write(text + "\n")
        print(f"\nwritten: {path}", file=sys.stderr)
    if args.telegram:
        ok, msg = send_telegram(text)
        print(f"telegram: {msg}", file=sys.stderr)
        # a dead Telegram route (Clash down) must not fail the daily job:
        # the digest is still written to docs/reports/
        if not ok:
            print("warning: Telegram delivery failed; digest saved to file only",
                  file=sys.stderr)


if __name__ == "__main__":
    main()
