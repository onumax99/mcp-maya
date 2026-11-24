"""Talks to Maya's commandPort and runs code through bridge.py."""
from __future__ import annotations

import atexit
import json
import os
import shutil
import socket
import tempfile
import time
import uuid
from pathlib import Path

BRIDGE = Path(__file__).with_name("bridge.py")

OPEN_PORT_HINT = """\
In Maya's Script Editor (Python tab) run:
    import maya.cmds as cmds
    cmds.commandPort(name="{host}:{port}", sourceType="{source_type}")"""


class MayaError(RuntimeError):
    """The code raised inside Maya, or Maya gave no usable answer."""


class MayaConnectionError(MayaError):
    """Nothing is listening on the configured commandPort."""


def wrap_mel(python_line: str) -> str:
    """Wrap a line of Python so a MEL-type commandPort can run it."""
    escaped = python_line.replace("\\", "\\\\").replace('"', '\\"')
    return 'python("%s");' % escaped


class MayaClient:
    def __init__(self, host="127.0.0.1", port=7001, timeout=120.0, source_type="python"):
        if source_type not in ("python", "mel"):
            raise ValueError("source_type must be 'python' or 'mel', got %r" % source_type)
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.source_type = source_type
        self._workdir: Path | None = None

    @classmethod
    def from_env(cls) -> "MayaClient":
        return cls(
            host=os.environ.get("MAYA_HOST", "127.0.0.1"),
            port=os.environ.get("MAYA_PORT", "7001"),
            timeout=os.environ.get("MAYA_TIMEOUT", "120"),
            source_type=os.environ.get("MAYA_SOURCE_TYPE", "python"),
        )

    def run(self, code, *, args=None, scope="main", undo_chunk=True, timeout=None) -> dict:
        """Run code in Maya and return bridge.py's response dict.

        scope="main" runs in Maya's __main__ (like the Script Editor);
        anything else runs in a throwaway namespace that sees `args` as ARGS.
        """
        workdir = self._ensure_workdir()
        token = uuid.uuid4().hex
        request_path = workdir / (token + ".request.json")
        response_path = workdir / (token + ".response.json")
        request = {
            "code": code,
            "args": args,
            "scope": scope,
            "undo_chunk": undo_chunk,
            "response_path": str(response_path),
        }
        request_path.write_text(json.dumps(request), encoding="utf-8")
        try:
            reply = self._send(self._command(request_path), response_path, timeout or self.timeout)
            if not response_path.exists():
                raise MayaError(
                    "Maya did not run the request (is the commandPort sourceType %r?). "
                    "commandPort replied: %r" % (self.source_type, reply)
                )
            return json.loads(response_path.read_text(encoding="utf-8"))
        finally:
            request_path.unlink(missing_ok=True)
            response_path.unlink(missing_ok=True)

    def _command(self, request_path: Path) -> str:
        # ascii() keeps the line pure ASCII whatever the paths contain.
        # "or True": a python commandPort evals the line and, when that gives None,
        # runs it a second time with exec. A non-None value stops the rerun.
        line = (
            "exec(compile(open({bridge}, encoding='utf-8').read(), {bridge}, 'exec'), "
            "{{'__name__': '__mcp_maya_bridge__', 'REQUEST_PATH': {request}}}) or True"
        ).format(bridge=ascii(str(BRIDGE)), request=ascii(str(request_path)))
        return wrap_mel(line) if self.source_type == "mel" else line

    def _send(self, command: str, response_path: Path, timeout: float) -> str:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=5)
        except OSError as exc:
            hint = OPEN_PORT_HINT.format(host=self.host, port=self.port, source_type=self.source_type)
            raise MayaConnectionError(
                "Cannot reach Maya on %s:%d (%s).\n%s" % (self.host, self.port, exc, hint)
            ) from exc
        with sock:
            sock.sendall((command + "\n").encode("ascii"))
            # Maya answers once the code has finished, ending its reply with NUL.
            # A port opened with noreturn never answers, so also watch for the file.
            sock.settimeout(0.2)
            deadline = time.monotonic() + timeout
            reply = b""
            while not reply.endswith(b"\x00"):
                if time.monotonic() > deadline:
                    raise MayaError(
                        "No answer from Maya after %gs. The code may still be running there." % timeout
                    )
                try:
                    data = sock.recv(4096)
                except socket.timeout:
                    if response_path.exists():
                        break
                    continue
                if not data:
                    break
                reply += data
        return reply.rstrip(b"\x00").decode("utf-8", "replace").strip()

    def _ensure_workdir(self) -> Path:
        if self._workdir is None:
            self._workdir = Path(tempfile.mkdtemp(prefix="mcp-maya-"))
            atexit.register(shutil.rmtree, self._workdir, ignore_errors=True)
        return self._workdir
