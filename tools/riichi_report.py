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

BOT_ID = 457
API = "https://api.riichi.dev/api/v1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get(path, attempts=3):
    last = ""
    for i in range(attempts):
        out = subprocess.run(
            ["curl", "-s", "-m", "25", "-A", "Mozilla/5.0",
             "-w", "\n%{http_code}", f"{API}/{path}"],
            capture_output=True, text=True)
        body, _, code = out.stdout.rpartition("\n")
        if out.returncode == 0 and code.strip() == "200" and body.strip():
            return json.loads(body)
        last = (f"curl exit {out.returncode}, http {code.strip() or '?'}, "
                f"{body[:120]!r}")
        time.sleep(1.5 * (i + 1))
    raise SystemExit(f"API request failed: {path} ({last})")


def bot():
    return _get(f"bots/{BOT_ID}")["data"]


def games(limit=100):
    return _get(f"bots/{BOT_ID}/games?limit={limit}")["data"]["games"]


def leaderboard_rows():
    rows, off = [], 0
    while True:
        page = _get(f"leaderboard?limit=100&offset={off}&activity=all")["data"]
        if not page:
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


def digest(date_str=None, days=1):
    d = bot()
    gs = games(200)
    local_games = [(g, _local(g["played_at"])) for g in gs]
    if date_str:
        sel = [(g, t) for g, t in local_games
               if t and t.date().isoformat() == date_str]
        label = date_str
    else:
        cutoff = dt.date.today() - dt.timedelta(days=days - 1)
        sel = [(g, t) for g, t in local_games if t and t.date() >= cutoff]
        label = ("today" if days == 1 else f"last {days} days")
    sel.sort(key=lambda x: x[1], reverse=True)

    ranks = [0, 0, 0, 0]
    dcs = 0
    for g, _ in sel:
        if 1 <= g["rank"] <= 4:
            ranks[g["rank"] - 1] += 1
        if g.get("is_disconnected"):
            dcs += 1
    delta = sum(g.get("rating_delta") or 0 for g, _ in sel)
    rows = leaderboard_rows()
    pos = position(d["rating"], rows)
    total = len(rows)
    # rank at the start of the period = position of the rating before the
    # oldest game in the selection
    rank_move = None
    if sel:
        oldest = min(sel, key=lambda x: x[1])[0]
        start_rating = oldest.get("rating_before")
        if start_rating is not None:
            rank_move = position(start_rating, rows) - pos

    lines = []
    lines.append(f"RiichiLab · louis · {label}")
    lines.append("")
    if sel:
        scores = [g["score"] for g, _ in sel]
        best = max(sel, key=lambda x: x[0]["score"])
        lines.append(f"games {len(sel)}  ·  1st {ranks[0]}  2nd {ranks[1]}  "
                     f"3rd {ranks[2]}  4th {ranks[3]}"
                     + (f"  ·  {dcs} disconnected" if dcs else ""))
        move = ""
        if rank_move:
            move = (f"  (\u25b2{rank_move} this period)" if rank_move > 0
                    else f"  (\u25bc{-rank_move} this period)")
        lines.append(f"rating {d['rating']} ({delta:+d} this period)  ·  "
                     f"rank {pos} of {total}{move}  ·  "
                     f"lifetime games {d['total_games']}")
        avg_rank = sum(g["rank"] for g, _ in sel) / len(sel)
        lines.append(f"avg rank {avg_rank:.2f}  ·  "
                     f"top-2 finishes {100*(ranks[0]+ranks[1])/len(sel):.0f}%")
        lines.append(f"avg score {sum(scores)/len(scores):+.0f}  ·  "
                     f"best {best[0]['score']:+d} ({best[1].strftime('%H:%M')})"
                     f"  ·  worst {min(scores):+d}")
        lines.append("")
        lines.append("last games (local time, rank, score, rating change):")
        for g, t in sel[:8]:
            lines.append(f"  {t.strftime('%H:%M')}  {g['rank']}{_ord(g['rank'])}"
                         f"  {g['score']:+6d}  ({g.get('rating_delta', 0):+d})"
                         f"{'  [DC]' if g.get('is_disconnected') else ''}")
    else:
        lines.append(f"no ranked game recorded for {label}.")
        lines.append(f"rating {d['rating']}  ·  rank {pos} of {total}  ·  "
                     f"lifetime games {d['total_games']}")

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
    args = ap.parse_args()

    text = digest(args.date, args.days)
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
