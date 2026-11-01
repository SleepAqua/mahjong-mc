#!/usr/bin/env python3
"""Scan archived game logs for ron opportunities and state drift.

The open question after the driver fixes: does RiichiLab ever OFFER us a ron,
and do we take it? Every `request_action` carries a base64 `observation` blob
with the server's ground truth (`hands`, `waits`, `is_tenpai`,
`_legal_actions`), so this can be answered offline with no server churn.

    python3 tools/scan_games.py                 # all archived games
    python3 tools/scan_games.py --detail        # plus per-game rows

Reads logs/games/*.log (written on end_game) and optionally the two current
logs so it works before any archive exists.
"""
from __future__ import annotations

import argparse
import base64
import collections
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = [os.path.join(ROOT, "logs", "last_game.log.prev"),
        os.path.join(ROOT, "logs", "last_game.log")]
LOGS += sorted(glob.glob(os.path.join(ROOT, "logs", "games", "*.log")))


def analyse(path):
    recs = []
    for line in open(path, encoding="utf-8"):
        try:
            recs.append(json.loads(line))
        except ValueError:
            continue
    reqs = [r["msg"] for r in recs
            if r.get("dir") == "in" and r["msg"].get("type") == "request_action"]
    outs = {r["action"].get("request_id"): r["action"]
            for r in recs if r.get("dir") == "out"}
    me = next((r["me"] for r in recs if r.get("dir") == "out"), None)
    kinds = collections.Counter()
    tenpai = ron_offers = ron_taken = 0
    missed = []
    for m in reqs:
        blob = m.get("observation")
        if not blob:
            continue
        try:
            d = json.loads(base64.b64decode(blob))
        except Exception:
            continue
        legal = {a.get("action_type") for a in d.get("_legal_actions") or []}
        kinds.update(legal)
        # `waits`/`is_tenpai` in the blob come back empty/false even at prompts
        # where Riichi is legal (proved: 10 such prompts, all waits==[]), so the
        # only trustworthy tenpai signal is Riichi being offered. A discard
        # prompt offering Riichi means a closed tenpai hand.
        if d.get("waits") or "Riichi" in legal:
            tenpai += 1
        if "Ron" in legal:
            ron_offers += 1
            rid = m.get("request_id")
            sent = outs.get(rid, {})
            if sent.get("type") == "hora":
                ron_taken += 1
            else:
                missed.append((rid, sorted(legal), sent.get("type")))
    return {"file": os.path.basename(path), "me": me, "prompts": len(reqs),
            "tenpai": tenpai, "ron_offers": ron_offers,
            "ron_taken": ron_taken, "missed": missed, "kinds": dict(kinds)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", action="store_true")
    args = ap.parse_args()

    seen = set()
    rows = []
    for path in LOGS:
        if not os.path.exists(path):
            continue
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        r = analyse(path)
        if r["prompts"]:
            rows.append(r)

    if not rows:
        print("no logs yet")
        return
    tot = lambda k: sum(r[k] for r in rows)
    print(f"games {len(rows)}  ·  prompts {tot('prompts')}  ·  "
          f"tenpai prompts {tot('tenpai')}  ·  ron offers {tot('ron_offers')}"
          f"  ·  ron taken {tot('ron_taken')}")
    merged = collections.Counter()
    for r in rows:
        merged.update(r["kinds"])
    print("legal action types seen:", dict(merged))
    if tot("ron_offers") and tot("ron_taken") < tot("ron_offers"):
        print("!! ron offered but not taken:")
        for r in rows:
            for m in r["missed"][:3]:
                print("   ", r["file"], m)
    if args.detail:
        for r in rows:
            print(f"  {r['file']}  me={r['me']}  prompts={r['prompts']}  "
                  f"tenpai={r['tenpai']}  ron_offers={r['ron_offers']}")


if __name__ == "__main__":
    main()
