#!/usr/bin/env python3
"""Download full-information mjai replays of any bot's games.

RiichiLab publishes every ranked game as an mjai JSONL file on
logs.riichi.dev, with all four hands revealed — unlike the bot's own logs,
where opponents are masked. That makes it the only way to study how a strong
bot *decides* rather than how it scored.

    python3 tools/fetch_replays.py --bot 323 --games 100 -o /tmp/mjai
    python3 tools/fetch_replays.py --game 14695430-5bc2-423b-bd5c-54bfce3a348d

Each game is written as <out>/<bot>_<game_id>.jsonl.gz, plus seats_<bot>.json
mapping game id -> the bot's seat, which the analyser needs.

The API is public; no token is required. Please keep the download count modest
— one request per game, no parallelism.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse

API = "https://api.riichi.dev/api/v1"
LOGS = "https://logs.riichi.dev/mjai-logs"


def _get(path):
    out = subprocess.run(
        ["curl", "-s", "-m", "25", "-A", "Mozilla/5.0", f"{API}/{path}"],
        capture_output=True, text=True).stdout
    return json.loads(out)


def game_ids(bot_id, count, four_player=True):
    """Newest ranked games first, walking the cursor the API pages with."""
    ids, cursor = [], None
    while len(ids) < count:
        path = f"bots/{bot_id}/games?limit=50"
        if cursor:
            path += "&cursor=" + urllib.parse.quote(cursor)
        data = _get(path)["data"]
        for g in data.get("games") or []:
            if not four_player or g.get("player_count") == 4:
                if g.get("game_type", "ranked") == "ranked":
                    ids.append((g["game_id"], g["played_at"]))
        cursor = data.get("next_cursor")
        if not data.get("has_more") or not cursor:
            break
    return ids[:count]


def fetch(game_id, played_at, path):
    y, m, d = played_at[:10].split("-")
    url = f"{LOGS}/{y}/{m}/{d}/{game_id}.jsonl.gz"
    code = subprocess.run(
        ["curl", "-s", "-m", "30", "-A", "Mozilla/5.0", "-o", path,
         "-w", "%{http_code}", url], capture_output=True, text=True).stdout
    return code == "200"


def seat_of(game_id, bot_id):
    data = _get(f"games/{game_id}")["data"]
    for p in data.get("players") or []:
        if str(p.get("bot_id")) == str(bot_id):
            return p["seat"]
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bot", type=int, help="bot id whose games to fetch")
    ap.add_argument("--game", help="a single game id")
    ap.add_argument("--games", type=int, default=20)
    ap.add_argument("-o", "--out", default="replays")
    args = ap.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    if args.game:
        path = os.path.join(args.out, f"{args.game}.jsonl.gz")
        ok = fetch(args.game, _get(f"games/{args.game}")["data"]["played_at"], path)
        print(path if ok else f"failed: {args.game}")
        return 0 if ok else 1

    if not args.bot:
        ap.error("either --bot or --game is required")

    seats_path = os.path.join(args.out, f"seats_{args.bot}.json")
    seats = {}
    if os.path.exists(seats_path):
        seats = json.load(open(seats_path, encoding="utf-8"))

    got = 0
    for game_id, played_at in game_ids(args.bot, args.games):
        path = os.path.join(args.out, f"{args.bot}_{game_id}.jsonl.gz")
        if os.path.exists(path):
            got += 1
        elif fetch(game_id, played_at, path):
            got += 1
            time.sleep(0.3)
        if game_id not in seats:
            seat = seat_of(game_id, args.bot)
            if seat is not None:
                seats[game_id] = seat
    json.dump(seats, open(seats_path, "w", encoding="utf-8"), indent=1)
    print(f"{got} replays in {args.out}, {len(seats)} seat mappings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
