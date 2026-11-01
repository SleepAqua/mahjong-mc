"""RiichiLab (riichi.dev) WebSocket driver — play ranked mahjong AI games.

    python3 -m mahjong_mc.riichi_ws --token <BOT_TOKEN> --policy gto
    python3 -m mahjong_mc.riichi_ws --validate          # one-shot validation

RiichiLab replaced the retired mjai.app (shut down 2026-04-30). Bots
register at https://riichi.dev/bots (GitHub login), receive a token, and
connect to the game server over WebSocket. The server streams standard
MJAI events and prompts with `request_action`; the bot replies with one
action echoing the request_id. `MjaiBot` in reactive mode maintains all
state from the echoed event stream, so every existing policy works
unchanged.

Zero dependencies: the WebSocket client is implemented with stdlib
socket + ssl (client frames are masked as RFC 6455 requires).

Time budget on RiichiLab: 3 s grace + 15 s bank per kyoku; invalid
actions (not in possible_actions) are chombo, so every reply is
validated against possible_actions with a legal fallback.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import signal
import socket
import ssl
import struct
import sys
import time

from mahjong_mc.mc import load_policy_dir
from mahjong_mc.mjai import MjaiBot
from mahjong_mc.policies import make_policy

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_STRATEGY_DIR = os.path.join(_PROJECT_ROOT, "my_strategies")

DEFAULT_RANKED_URL = "wss://game.riichi.dev/ws/ranked"
DEFAULT_VALIDATE_URL = "wss://game.riichi.dev/ws/validate"
_RECONNECT_DELAY = 5.0
_IDLE_TIMEOUT = 600.0  # seconds of silence before a liveness ping


class WSClosed(Exception):
    """The server closed the WebSocket (or the TCP connection dropped)."""


class WSClient:
    """Minimal RFC 6455 client: text frames only, stdlib only."""

    def __init__(self, host, port, path, token, timeout=None, secure=True):
        self.host = host
        self.port = port
        self.path = path
        raw = socket.create_connection((host, port), timeout=30)
        if secure:
            ctx = ssl.create_default_context()
            self.sock = ctx.wrap_socket(raw, server_hostname=host)
        else:
            self.sock = raw  # local testing
        self.sock.settimeout(timeout)
        self._buf = b""
        self._handshake(token)

    @classmethod
    def from_url(cls, url, token):
        secure = url.startswith("wss://")
        if not secure and not url.startswith("ws://"):
            raise ValueError(f"expected ws:// or wss:// URL, got {url!r}")
        rest = url[len("wss://") if secure else len("ws://"):]
        hostport, _, path = rest.partition("/")
        path = "/" + path
        host, _, port = hostport.partition(":")
        return cls(host, int(port or (443 if secure else 80)), path, token,
                   timeout=_IDLE_TIMEOUT, secure=secure)

    def _handshake(self, token):
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Authorization: Bearer {token}\r\n"
            "\r\n"
        )
        self.sock.sendall(req.encode())
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WSClosed("handshake: connection closed")
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0]
        if b" 101" not in status:
            raise WSClosed(f"handshake failed: {status.decode(errors='replace')}")
        self._buf = rest

    # ------------------------------------------------------------- frames

    def _read_exact(self, n):
        while len(self._buf) < n:
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                raise
            if not chunk:
                raise WSClosed("connection closed by peer")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _read_frame(self):
        """Return (opcode, payload) or None on a close frame."""
        b0, b1 = self._read_exact(2)
        opcode = b0 & 0x0F
        masked = b1 & 0x80
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read_exact(8))[0]
        mask = self._read_exact(4) if masked else None
        payload = self._read_exact(length) if length else b""
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload

    def _send_frame(self, opcode, payload=b""):
        header = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    # -------------------------------------------------------------- public

    def send_text(self, text):
        self._send_frame(0x1, text.encode("utf-8"))

    def recv_text(self):
        """Next text message, or None when the socket closes."""
        fragments = []
        idle = 0
        while True:
            try:
                opcode, payload = self._read_frame()
            except socket.timeout:
                idle += 1
                if idle >= 3:
                    raise WSClosed("no data for 3 idle periods")
                self._send_frame(0x9)  # ping to keep the link warm
                continue
            idle = 0
            if opcode == 0x8:      # close
                code = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else 0
                reason = payload[2:].decode("utf-8", errors="replace")
                print(f"[riichi] peer closed the socket (code {code}"
                      f"{', reason ' + repr(reason) if reason else ''})",
                      file=sys.stderr)
                self._send_frame(0x8, payload[:2])
                return None
            if opcode == 0x9:      # ping -> pong
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:      # pong
                continue
            if opcode in (0x1, 0x2):
                fragments.append(payload)
                if payload is not None:
                    return b"".join(fragments).decode("utf-8",
                                                      errors="replace")
            if opcode == 0x0:      # continuation
                fragments.append(payload)
                continue

    def close(self):
        try:
            self._send_frame(0x8)
            self.sock.close()
        except OSError:
            pass

    def __iter__(self):
        while True:
            msg = self.recv_text()
            if msg is None:
                raise WSClosed("connection closed by peer")
            msg = msg.strip()
            if not msg:
                continue
            try:
                yield json.loads(msg)
            except json.JSONDecodeError:
                continue


# ------------------------------------------------------------------- loop

def _fallback_action(options):
    """Cheapest legal action when the policy blew up."""
    for want in ("none", "dahai", "hora", "reach"):
        for opt in options:
            if opt.get("type") == want:
                return dict(opt)
    return {"type": options[0]["type"]} if options else {"type": "none"}


def _archive_game(log_path, keep=100):
    """Copy the finished game's event log into logs/games/ (ring buffer)."""
    if not log_path or not os.path.exists(log_path):
        return
    import shutil
    gdir = os.path.join(os.path.dirname(log_path), "games")
    os.makedirs(gdir, exist_ok=True)
    dest = os.path.join(gdir, time.strftime("%Y%m%d-%H%M%S") + ".log")
    try:
        shutil.copyfile(log_path, dest)
        files = sorted(os.listdir(gdir))
        for old in files[:-keep]:
            os.remove(os.path.join(gdir, old))
    except OSError:
        pass


def _log_line(path, obj):
    """Append one JSON line to the debug log (no-op unless RIICHI_EVENT_LOG)."""
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _session(ws, policy_name, seed, stats, stop_after_validation):
    log = os.environ.get("RIICHI_EVENT_LOG")
    bot = None
    for msg in ws:
        t = msg.get("type")
        _log_line(log, {"dir": "in", "msg": msg})
        if t is None and msg.get("error"):
            print(f"[riichi] server error: {msg['error']}", file=sys.stderr)
            continue
        if t == "start_game":
            seat = msg.get("id", 0)
            if log:
                # keep the previous game for inspection, then start fresh
                if os.path.exists(log):
                    os.replace(log, log + ".prev")
                open(log, "w").close()
            bot = MjaiBot(make_policy(policy_name, seed), seat)
            bot.reactive = True
            print(f"[riichi] game start (seat {seat})", file=sys.stderr)
        elif t == "request_action" and bot is not None:
            options = msg.get("possible_actions", [])
            try:
                action = bot.respond(options, msg.get("request_id"))
            except Exception as e:          # never lose the game to a bug
                print(f"[riichi] policy error ({type(e).__name__}: {e}); "
                      f"falling back to a legal action", file=sys.stderr)
                action = _fallback_action(options)
            action.setdefault("actor", bot.me)
            if msg.get("request_id") is not None:
                action["request_id"] = msg.get("request_id")
            _log_line(log, {"dir": "out", "me": bot.me, "action": action,
                            "counts": bot.counts[bot.me],
                            "wall_left": bot.wall_left,
                            "last_drawn": bot.last_drawn})
            ws.send_text(json.dumps(action, separators=(",", ":")))

        elif t == "end_game":
            stats["games"] += 1
            scores = msg.get("scores")
            print(f"[riichi] game over: {scores} "
                  f"(total {stats['games']}, wins {stats['wins']})",
                  file=sys.stderr)
            # The server expects the bot to disconnect after end_game; if we
            # just sit on the socket the bot stays flagged as "already
            # connected to a game" and never rejoins the queue.
            # (During validation keep the socket open: validation_result
            # arrives AFTER end_game.)
            _archive_game(log)
            if not stop_after_validation:
                return
        elif t == "validation_result":
            print(f"[riichi] validation result: {msg}", file=sys.stderr)
            stats["validated"] = msg.get("passed")
            return
        elif bot is not None:
            bot.on_event(msg)
            if t == "hora" and msg.get("actor") == bot.me:
                stats["wins"] += 1


_CURRENT = {"ws": None}


def _install_term_handler():
    """Close the socket properly on SIGTERM.

    Killing the process without a WebSocket close frame leaves the bot flagged
    server-side as "already connected to a game", which blocks every reconnect
    until the server times the session out.
    """
    def handler(signum, frame):
        ws = _CURRENT.get("ws")
        if ws is not None:
            try:
                ws.close()
            except OSError:
                pass
        raise SystemExit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass


def run(url, token, policy_name, seed=None, games=None, validate=False):
    _install_term_handler()
    stats = {"games": 0, "wins": 0, "validated": None}
    delay = _RECONNECT_DELAY
    while games is None or stats["games"] < games:
        ws = None
        before = stats["games"]
        try:
            ws = WSClient.from_url(url, token)
            _CURRENT["ws"] = ws
            print("[riichi] connected, joining the queue"
                  + (" (validation game)" if validate else "")
                  + "…", file=sys.stderr)
            _session(ws, policy_name, seed, stats, validate)
            if validate and stats["validated"] is not None:
                break
        except (WSClosed, OSError) as e:
            print(f"[riichi] connection closed ({e})", file=sys.stderr)
        except KeyboardInterrupt:
            break
        finally:
            _CURRENT["ws"] = None
            if ws is not None:
                ws.close()
        if games is not None and stats["games"] >= games:
            break
        # back off while the server keeps rejecting us (a game that finished
        # counts as progress and resets the delay)
        if stats["games"] == before:
            delay = min(delay * 2, 120.0)
        else:
            delay = _RECONNECT_DELAY
        print(f"[riichi] reconnecting in {delay:.0f}s", file=sys.stderr)
        time.sleep(delay)
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="riichi-ws",
        description="Play RiichiLab (riichi.dev) ranked games with any "
                    "mahjong-mc policy over the mjai WebSocket protocol")
    ap.add_argument("--token", default=os.environ.get("RIICHI_TOKEN"),
                    help="bot token from riichi.dev/bots "
                         "(or set RIICHI_TOKEN)")
    ap.add_argument("--policy", default="gto",
                    help="policy name (any my_strategies/ name)")
    ap.add_argument("--url", default=None,
                    help="override the WebSocket URL")
    ap.add_argument("--validate", action="store_true",
                    help="run the one-shot validation game "
                         "(wss://game.riichi.dev/ws/validate)")
    ap.add_argument("--games", type=int, default=None,
                    help="stop after N games (default: run forever)")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)

    if not args.token:
        ap.error("no bot token: pass --token or set RIICHI_TOKEN "
                 "(register a bot at https://riichi.dev/bots)")

    url = args.url or (DEFAULT_VALIDATE_URL if args.validate
                       else DEFAULT_RANKED_URL)
    if os.path.isdir(_DEFAULT_STRATEGY_DIR):
        load_policy_dir(_DEFAULT_STRATEGY_DIR)
    stats = run(url, args.token, args.policy, seed=args.seed,
                games=args.games, validate=args.validate)
    print(f"[riichi] finished: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
