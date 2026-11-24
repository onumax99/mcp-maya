"""Stand-ins for Maya so the client/bridge round trip can be tested without it."""
import socket
import sys
import threading
import types

import pytest

from mcp_maya.client import MayaClient


class FakeCmds:
    def __init__(self):
        self.undo_calls = []

    def undoInfo(self, **kwargs):
        self.undo_calls.append(kwargs)


@pytest.fixture
def fake_cmds(monkeypatch):
    cmds = FakeCmds()
    maya = types.ModuleType("maya")
    maya.cmds = cmds
    monkeypatch.setitem(sys.modules, "maya", maya)
    return cmds


class FakeCommandPort:
    """Accepts connections and runs each received line the way a python commandPort does."""

    def __init__(self, reply=True, always_twice=False):
        self.reply = reply
        self.always_twice = always_twice
        self.received = []
        self._server = socket.create_server(("127.0.0.1", 0))
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            with conn:
                line = conn.recv(4096).decode("utf-8")
                self.received.append(line)
                try:
                    answer = repr(self._run(line))
                except Exception as exc:  # what Maya does: report, don't die
                    answer = "# Error: %s" % exc
                if self.reply:
                    conn.sendall(answer.encode("utf-8") + b"\n\x00")
                else:
                    # like a noreturn port: stay connected, say nothing
                    conn.settimeout(2)
                    try:
                        conn.recv(1)
                    except OSError:
                        pass

    def _run(self, line):
        # Observed on Maya 2025: the line is eval'd, and run again with exec
        # when eval gives None (or cannot parse it as an expression).
        try:
            result = eval(line)
        except SyntaxError:
            result = None
        if result is None or self.always_twice:
            exec(line)
        return result

    def close(self):
        self._server.close()


@pytest.fixture
def make_port(fake_cmds):
    servers = []

    def make(**kwargs):
        servers.append(FakeCommandPort(**kwargs))
        return servers[-1]

    yield make
    for server in servers:
        server.close()


@pytest.fixture
def port(make_port):
    return make_port()


@pytest.fixture
def client(port):
    return MayaClient(port=port.port, timeout=5)
