"""Tests for the RiichiLab WebSocket driver with a mock game server.

The mock server speaks the server side of the WebSocket handshake and
frame protocol on localhost (plain ws://), scripts MJAI events, and
records every action the bot sends — verifying the full reactive loop
without the real server.
"""

import base64
import hashlib
import json
import os
import socket
import struct
import sys
import threading
import unittest

from mahjong_mc.mjai import MjaiBot, id_to_mjai
from mahjong_mc.mc import load_policy_dir
from mahjong_mc.policies import ShantenPolicy, make_policy
from mahjong_mc.riichi_ws import WSClient, _session

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_policy_dir(os.path.join(_PROJECT_ROOT, "my_strategies"))

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class MockServer:
    """Server-side WebSocket: handshake, send scripted frames, collect replies."""

    def __init__(self, script):
        """script: list of steps. Each step is either:
        - ("send", [events...])  — send a batch of JSON events
        - ("expect", n)          — read n actions from the bot
        - ("end",)               — close after the last expected actions
        """
        self.script = script
        self.replies = []
        self.sock = None
        self._inbuf = b""
        self.ready = threading.Event()
        self.error = None

    def start(self):
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        t = threading.Thread(target=self._serve, daemon=True)
        t.start()
        self.thread = t
        return self.port

    def _serve(self):
        try:
            conn, _ = self.listener.accept()
            conn.settimeout(10)
            self.sock = conn
            self._handshake(conn)
            self.ready.set()
            self._run_script(conn)
        except Exception as e:  # surfaced to the test via join()
            self.error = e
            self.ready.set()
        finally:
            try:
                if self.sock is not None:
                    self.sock.close()
            except OSError:
                pass

    def _handshake(self, conn):
        data = b""
        while b"\r\n\r\n" not in data:
            data += conn.recv(4096)
        head = data.split(b"\r\n\r\n", 1)[0].decode()
        key = None
        for line in head.split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        accept = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        resp = ("HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n")
        conn.sendall(resp.encode())

    def _send_frame(self, conn, payload, opcode=0x1):
        n = len(payload)
        header = bytearray([0x80 | opcode])
        if n < 126:
            header.append(n)
        elif n < 65536:
            header.append(126)
            header += struct.pack(">H", n)
        else:
            header.append(127)
            header += struct.pack(">Q", n)
        conn.sendall(bytes(header) + payload)

    def _recv_frame(self, conn):
        b0, b1 = self._read_exact(conn, 2)
        opcode = b0 & 0x0F
        masked = b1 & 0x80
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read_exact(conn, 2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read_exact(conn, 8))[0]
        mask = self._read_exact(conn, 4) if masked else None
        payload = self._read_exact(conn, length) if length else b""
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload

    def _read_exact(self, conn, n):
        while len(self._inbuf) < n:
            chunk = conn.recv(65536)
            if not chunk:
                raise ConnectionError("client closed")
            self._inbuf += chunk
        out, self._inbuf = self._inbuf[:n], self._inbuf[n:]
        return out

    def _run_script(self, conn):
        for step in self.script:
            kind = step[0]
            if kind == "send":
                for ev in step[1]:
                    self._send_frame(conn, json.dumps(ev).encode())
            elif kind == "expect":
                got = 0
                while got < step[1]:
                    try:
                        opcode, payload = self._recv_frame(conn)
                    except socket.timeout:
                        break  # client went quiet
                    if opcode == 0x9:  # client ping -> pong
                        self._send_frame(conn, b"", opcode=0xA)
                        continue
                    self.replies.append(json.loads(payload.decode()))
                    got += 1
            elif kind == "end":
                self._send_frame(conn, json.dumps(
                    {"type": "end_game", "scores": [25000] * 4}).encode())
                try:
                    conn.close()
                except OSError:
                    pass
                return

    def join(self):
        self.thread.join(timeout=15)
        if self.error:
            raise self.error


def deal_tehais(my_hand, others):
    """Build tehais with only our own hand visible (live mjai style)."""
    return [[id_to_mjai(t) for t in my_hand]] + [[] for _ in range(3)]


def dahai_options(tiles):
    return [{"type": "dahai", "pai": id_to_mjai(t)} for t in tiles]


class TestReactiveLoop(unittest.TestCase):
    """Run the reactive session against the mock server."""

    def _run(self, script, policy_name="greedy", seed=1):
        from mahjong_mc.riichi_ws import WSClosed

        server = MockServer(script)
        port = server.start()
        ws = WSClient("127.0.0.1", port, "/ws/ranked", "tok",
                      timeout=10, secure=False)
        stats = {"games": 0, "wins": 0, "validated": None}
        try:
            _session(ws, policy_name, seed, stats,
                     stop_after_validation=False)
        except (WSClosed, OSError, socket.timeout):
            pass  # the mock closes after its script
        server.join()
        if server.error:
            raise server.error
        ws.close()
        return server.replies, stats

    # 234m 456m 789p 22s 33s: tenpai on 2s/3s (needs riichi for a yaku)
    TENPAI = [1, 2, 3, 4, 5, 6, 15, 16, 17, 19, 19, 20, 20]
    # 234m 456m 345p 66p 78s: tenpai on 6s/9s, tanyao (yaku without riichi)
    TANYAO_TENPAI = [1, 2, 3, 3, 4, 5, 11, 12, 13, 14, 14, 24, 25]

    def test_draw_turn_discard(self):
        hand = [0, 1, 2, 9, 10, 11, 18, 19, 20, 22, 22, 23, 23]
        script = [
            ("send", [{"type": "start_game", "id": 0}]),
            ("send", [{"type": "start_kyoku", "bakaze": "E",
                       "dora_marker": "5m", "kyoku": 1, "honba": 0,
                       "kyotaku": 0, "oya": 0, "scores": [25000] * 4,
                       "tehais": deal_tehais(hand, None)},
                      {"type": "tsumo", "actor": 0, "pai": "7m"},
                      {"type": "request_action", "request_id": 1,
                       "possible_actions": dahai_options(hand + [6])}]),
            ("expect", 1),
            ("end",),
        ]
        replies, _ = self._run(script)
        self.assertEqual(len(replies), 1)
        act = replies[0]
        self.assertEqual(act["type"], "dahai")
        self.assertEqual(act["actor"], 0)
        self.assertEqual(act["request_id"], 1)

    def test_request_id_echo(self):
        hand = [0, 1, 2, 9, 10, 11, 18, 19, 20, 22, 22, 23, 23]
        script = [
            ("send", [{"type": "start_game", "id": 0}]),
            ("send", [{"type": "start_kyoku", "bakaze": "E",
                       "dora_marker": "5m", "kyoku": 1, "honba": 0,
                       "kyotaku": 0, "oya": 0, "scores": [25000] * 4,
                       "tehais": deal_tehais(hand, None)},
                      {"type": "tsumo", "actor": 0, "pai": "7m"},
                      {"type": "request_action", "request_id": 7,
                       "possible_actions": dahai_options([0, 1, 2, 9, 10, 11,
                                                          18, 19, 20, 22, 23])}]),
            ("expect", 1),
            ("end",),
        ]
        replies, _ = self._run(script)
        self.assertEqual(replies[0]["request_id"], 7)

    def test_reach_flow(self):
        """Reach then a separate discard prompt (server echoes reach)."""
        hand = self.TENPAI
        script = [
            ("send", [{"type": "start_game", "id": 0}]),
            ("send", [{"type": "start_kyoku", "bakaze": "E",
                       "dora_marker": "5m", "kyoku": 1, "honba": 0,
                       "kyotaku": 0, "oya": 0, "scores": [25000] * 4,
                       "tehais": deal_tehais(hand, None)},
                      {"type": "tsumo", "actor": 0, "pai": "1m"},
                      {"type": "request_action", "request_id": 1,
                       "possible_actions": dahai_options(hand + [0])
                       + [{"type": "reach"}]}]),
            ("expect", 1),
            ("end",),
        ]
        replies, _ = self._run(script, policy_name="greedy")
        self.assertIn(replies[0]["type"], ("reach", "dahai"))

    def test_reach_then_discard_direct(self):
        """Deterministic: always-riichi policy, server echoes reach."""
        class AlwaysRiichi(ShantenPolicy):
            def decide_riichi(self, view):
                return view.can_riichi

        hand = self.TENPAI
        bot = MjaiBot(AlwaysRiichi(seed=1), 0)
        bot.reactive = True
        bot.on_event({"type": "start_game", "id": 0})
        bot.on_event({"type": "start_kyoku", "bakaze": "E",
                      "dora_marker": "5m", "kyoku": 1, "honba": 0,
                      "kyotaku": 0, "oya": 0, "scores": [25000] * 4,
                      "tehais": deal_tehais(hand, None)})
        bot.on_event({"type": "tsumo", "actor": 0, "pai": "1m"})
        possible = dahai_options(hand + [0]) + [{"type": "reach"}]
        act = bot.respond(possible, request_id=1)
        self.assertEqual(act["type"], "reach")
        self.assertEqual(sum(bot.counts[0]), 14)
        # the server echoes the reach, then re-sends the same tsumo
        bot.on_event({"type": "reach", "actor": 0})
        bot.on_event({"type": "tsumo", "actor": 0, "pai": "1m"})
        self.assertEqual(sum(bot.counts[0]), 14)  # not double counted
        act2 = bot.respond(dahai_options(hand + [0]), request_id=2)
        self.assertEqual(act2["type"], "dahai")
        bot.on_event({"type": "dahai", "actor": 0,
                      "pai": act2["pai"], "tsumogiri": True})
        self.assertEqual(sum(bot.counts[0]), 13)

    def test_claim_pass(self):
        hand = [0, 1, 2, 9, 10, 11, 18, 19, 20, 22, 22, 23, 23]
        script = [
            ("send", [{"type": "start_game", "id": 0}]),
            ("send", [{"type": "start_kyoku", "bakaze": "E",
                       "dora_marker": "5m", "kyoku": 1, "honba": 0,
                       "kyotaku": 0, "oya": 0, "scores": [25000] * 4,
                       "tehais": deal_tehais(hand, None)},
                      {"type": "tsumo", "actor": 0, "pai": "7m"},
                      {"type": "dahai", "actor": 0, "pai": "7m",
                       "tsumogiri": True},
                      {"type": "tsumo", "actor": 1, "pai": "?"},
                      {"type": "dahai", "actor": 1, "pai": "9s"},
                      {"type": "request_action", "request_id": 3,
                       "possible_actions": [{"type": "none"}]}]),
            ("expect", 1),
            ("end",),
        ]
        replies, _ = self._run(script)
        self.assertEqual(replies[0]["type"], "none")

    def test_ron_two_phase(self):
        """Same as above but the server echoes the bot's discard."""

        class NoRiichi(ShantenPolicy):
            def decide_riichi(self, view):
                return False

        hand = self.TANYAO_TENPAI
        # The mock cannot echo dynamically, so drive the bot directly
        # through two sessions with a fixed first discard.
        bot = MjaiBot(NoRiichi(seed=1), 0)
        bot.reactive = True
        bot.on_event({"type": "start_game", "id": 0})
        bot.on_event({"type": "start_kyoku", "bakaze": "E",
                      "dora_marker": "5m", "kyoku": 1, "honba": 0,
                      "kyotaku": 0, "oya": 0, "scores": [25000] * 4,
                      "tehais": deal_tehais(hand, None)})
        bot.on_event({"type": "tsumo", "actor": 0, "pai": "1m"})
        act = bot.respond(dahai_options(hand + [0]), request_id=1)
        self.assertEqual(act["type"], "dahai")
        # server echoes our discard, opponent feeds 6s
        bot.on_event({"type": "dahai", "actor": 0,
                      "pai": act["pai"], "tsumogiri": True})
        bot.on_event({"type": "tsumo", "actor": 1, "pai": "?"})
        bot.on_event({"type": "dahai", "actor": 1, "pai": "6s"})
        act2 = bot.respond([{"type": "hora", "actor": 0, "target": 1,
                             "pai": "6s"}, {"type": "none"}], request_id=2)
        self.assertEqual(act2["type"], "hora")
        self.assertEqual(act2["target"], 1)

    def test_furiten_blocks_ron(self):
        class NoRiichi(ShantenPolicy):
            def decide_riichi(self, view):
                return False

        hand = self.TANYAO_TENPAI
        bot = MjaiBot(NoRiichi(seed=1), 0)
        bot.reactive = True
        bot.on_event({"type": "start_game", "id": 0})
        bot.on_event({"type": "start_kyoku", "bakaze": "E",
                      "dora_marker": "5m", "kyoku": 1, "honba": 0,
                      "kyotaku": 0, "oya": 0, "scores": [25000] * 4,
                      "tehais": deal_tehais(hand, None)})
        bot.on_event({"type": "tsumo", "actor": 0, "pai": "1m"})
        bot.respond(dahai_options(hand + [0]), request_id=1)
        bot.on_event({"type": "dahai", "actor": 0, "pai": "1m",
                      "tsumogiri": True})
        # discard a 6s ourselves (becomes furiten), then it is fed again
        bot.on_event({"type": "tsumo", "actor": 0, "pai": "6s"})
        act = bot.respond(dahai_options(hand + [23]), request_id=2)
        bot.on_event({"type": "dahai", "actor": 0, "pai": "6s"})
        bot.on_event({"type": "tsumo", "actor": 1, "pai": "?"})
        bot.on_event({"type": "dahai", "actor": 1, "pai": "6s"})
        act2 = bot.respond([{"type": "hora", "actor": 0, "target": 1,
                             "pai": "6s"}, {"type": "none"}], request_id=3)
        self.assertEqual(act2["type"], "none")

    def test_ron_with_live_server_option_shape(self):
        """RiichiLab's hora option carries NO tile: ron must still be sent.

        Regression: the live server offers {"type": "hora", "actor": 0} with
        no pai/target, while the bot's ron action carries them. Comparing
        tiles made every ron look illegal, so the legalizer rewrote it to
        'none' -- the bot won 0 rons in 51 ranked games.
        """

        class NoRiichi(ShantenPolicy):
            def decide_riichi(self, view):
                return False

        hand = self.TANYAO_TENPAI
        bot = MjaiBot(NoRiichi(seed=1), 0)
        bot.reactive = True
        bot.on_event({"type": "start_game", "id": 0})
        bot.on_event({"type": "start_kyoku", "bakaze": "E",
                      "dora_marker": "5m", "kyoku": 1, "honba": 0,
                      "kyotaku": 0, "oya": 0, "scores": [25000] * 4,
                      "tehais": deal_tehais(hand, None)})
        bot.on_event({"type": "tsumo", "actor": 0, "pai": "1m"})
        act = bot.respond(dahai_options(hand + [0]), request_id=1)
        bot.on_event({"type": "dahai", "actor": 0,
                      "pai": act["pai"], "tsumogiri": True})
        bot.on_event({"type": "tsumo", "actor": 1, "pai": "?"})
        bot.on_event({"type": "dahai", "actor": 1, "pai": "6s"})
        act2 = bot.respond([{"type": "hora", "actor": 0},
                            {"type": "none"}], request_id=2)
        self.assertEqual(act2["type"], "hora")
        self.assertEqual(act2["request_id"], 2)

    def test_post_call_discard_uses_policy(self):
        """After our own pon the next prompt must be a discard, not a claim."""
        class AlwaysCall(ShantenPolicy):
            def decide_call(self, view, tile, options):
                return options[0] if options else None

        bot = MjaiBot(AlwaysCall(seed=1), 0)
        bot.reactive = True
        hand = [0, 0, 1, 2, 3, 9, 10, 11, 18, 19, 20, 24, 25]
        bot.on_event({"type": "start_game", "id": 0})
        bot.on_event({"type": "start_kyoku", "bakaze": "E",
                      "dora_marker": "5m", "kyoku": 1, "honba": 0,
                      "kyotaku": 0, "oya": 0, "scores": [25000] * 4,
                      "tehais": deal_tehais(hand, None)})
        bot.on_event({"type": "tsumo", "actor": 1, "pai": "?"})
        bot.on_event({"type": "dahai", "actor": 1, "pai": "1m"})
        act = bot.respond([{"type": "pon", "pai": "1m",
                            "consumed": ["1m", "1m"]},
                           {"type": "none"}], request_id=1)
        self.assertEqual(act["type"], "pon")
        bot.on_event({"type": "pon", "actor": 0, "target": 1,
                      "pai": "1m", "consumed": ["1m", "1m"]})
        self.assertEqual(bot._trigger, "discard")
        self.assertIsNone(bot.last_drawn)
        follow = bot.respond(dahai_options(
            [t for i, t in enumerate(bot.counts[0]) for _ in range(t)]),
            request_id=2)
        self.assertEqual(follow["type"], "dahai")

    def test_red_five_discard_matches_server_spelling(self):
        """Holding the red copy, only '5pr' is legal; send the server's name."""
        class Discard5p(ShantenPolicy):
            def choose_discard(self, view):
                return 13  # 5p

        bot = MjaiBot(Discard5p(seed=1), 0)
        bot.reactive = True
        hand = [0, 1, 2, 9, 13, 18, 19, 20, 24, 25, 27, 31, 33]
        bot.on_event({"type": "start_game", "id": 0})
        bot.on_event({"type": "start_kyoku", "bakaze": "E",
                      "dora_marker": "5m", "kyoku": 1, "honba": 0,
                      "kyotaku": 0, "oya": 0, "scores": [25000] * 4,
                      "tehais": deal_tehais(hand, None)})
        bot.on_event({"type": "tsumo", "actor": 0, "pai": "5m"})
        possible = [{"type": "dahai", "pai": "5pr"},
                    {"type": "dahai", "pai": "5m"},
                    {"type": "dahai", "pai": "W"}]
        act = bot.respond(possible, request_id=1)
        self.assertEqual(act["type"], "dahai")
        self.assertEqual(act["pai"], "5pr")

    def test_chombo_guard(self):
        """State drift: our discard isn't in possible_actions -> legal fallback."""
        bot = MjaiBot(make_policy("greedy", seed=1), 0)
        bot.reactive = True
        bot.on_event({"type": "start_game", "id": 0})
        hand = [0, 1, 2, 9, 10, 11, 18, 19, 20, 22, 22, 23, 23]
        bot.on_event({"type": "start_kyoku", "bakaze": "E",
                      "dora_marker": "5m", "kyoku": 1, "honba": 0,
                      "kyotaku": 0, "oya": 0, "scores": [25000] * 4,
                      "tehais": deal_tehais(hand, None)})
        bot.on_event({"type": "tsumo", "actor": 0, "pai": "7m"})
        # possible_actions deliberately excludes everything in hand
        possible = [{"type": "dahai", "pai": "5p"},
                    {"type": "dahai", "pai": "6p"},
                    {"type": "none"}]
        act = bot.respond(possible, request_id=9)
        self.assertIn(act["type"], ("dahai", "none"))
        if act["type"] == "dahai":
            self.assertIn(act["pai"], ("5p", "6p"))
        self.assertEqual(act["request_id"], 9)
        self.assertEqual(act["actor"], 0)

    def test_kan_from_draw(self):
        """Always-kan policy: ankan from the 4th copy, then replacement."""
        from mahjong_mc.engine import ANKAN

        class AlwaysKan(ShantenPolicy):
            def decide_kan(self, view, tile, options):
                return options[0] if options else None

            def decide_riichi(self, view):
                return False

        bot = MjaiBot(AlwaysKan(seed=1), 0)
        bot.reactive = True
        bot.on_event({"type": "start_game", "id": 0})
        # three 5m in hand; draw the 4th
        hand = [4, 4, 4, 0, 1, 2, 9, 10, 11, 18, 19, 20, 22]
        bot.on_event({"type": "start_kyoku", "bakaze": "E",
                      "dora_marker": "5m", "kyoku": 1, "honba": 0,
                      "kyotaku": 0, "oya": 0, "scores": [25000] * 4,
                      "tehais": deal_tehais(hand, None)})
        bot.on_event({"type": "tsumo", "actor": 0, "pai": "5m"})
        possible = [{"type": "ankan", "actor": 0,
                     "consumed": ["5m"] * 4}] + dahai_options(hand + [4])
        act = bot.respond(possible, request_id=1)
        self.assertEqual(act["type"], "ankan")
        self.assertEqual(act["consumed"], ["5m"] * 4)
        # server echoes ankan + dora + replacement tsumo, then asks discard
        bot.on_event({"type": "ankan", "actor": 0,
                      "consumed": ["5m"] * 4})
        bot.on_event({"type": "dora", "dora_marker": "6m"})
        bot.on_event({"type": "tsumo", "actor": 0, "pai": "3m"})
        act2 = bot.respond(dahai_options([0, 1, 2, 9, 10, 11, 18, 19, 20,
                                          22, 2]), request_id=2)
        self.assertEqual(act2["type"], "dahai")
        # state applies only when the server echoes the discard
        self.assertEqual(sum(bot.counts[0]), 11)  # 14 - 4 + 1
        bot.on_event({"type": "dahai", "actor": 0,
                      "pai": act2["pai"], "tsumogiri": True})
        self.assertEqual(sum(bot.counts[0]), 10)

    def test_latency_under_budget(self):
        """Each decision must fit the 3s grace budget with margin."""
        import time

        bot = MjaiBot(make_policy("gto", seed=1), 0)
        bot.reactive = True
        bot.on_event({"type": "start_game", "id": 0})
        hand = [0, 1, 2, 9, 10, 11, 18, 19, 20, 22, 22, 23, 23]
        bot.on_event({"type": "start_kyoku", "bakaze": "E",
                      "dora_marker": "5m", "kyoku": 1, "honba": 0,
                      "kyotaku": 0, "oya": 0, "scores": [25000] * 4,
                      "tehais": deal_tehais(hand, None)})
        bot.on_event({"type": "tsumo", "actor": 0, "pai": "7m"})
        t0 = time.perf_counter()
        for i in range(10):
            bot.respond(dahai_options(hand + [6]), request_id=i)
        elapsed = (time.perf_counter() - t0) / 10
        print(f"\n  [latency] gto decision: {elapsed*1000:.1f} ms avg")
        self.assertLess(elapsed, 1.0)


if __name__ == "__main__":
    unittest.main()
