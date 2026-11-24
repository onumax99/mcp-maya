"""MCP tools for a running Maya session."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image

from .client import MayaClient, MayaError

INSTRUCTIONS = """\
Drives the Autodesk Maya session that has a commandPort open on this machine.
Everything runs on Maya's main thread, so Maya is unresponsive while a call runs.
Call maya_status first: it fails with setup steps if Maya is not reachable.
execute_python is the general tool; the others are read-only shortcuts."""

MAYA_TOOLS = Path(__file__).with_name("maya_tools.py").read_text(encoding="utf-8")
MAX_OUTPUT_CHARS = 20000

mcp = FastMCP("maya", instructions=INSTRUCTIONS)
client = MayaClient.from_env()


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    dropped = len(text) - MAX_OUTPUT_CHARS
    return text[:MAX_OUTPUT_CHARS] + "\n... [%d more characters not shown]" % dropped


def _call(function: str, **args):
    """Run one of the functions in maya_tools.py inside Maya."""
    code = "%s\n%s(ARGS)\n" % (MAYA_TOOLS, function)
    reply = client.run(code, args=args, scope="private", undo_chunk=False)
    if not reply["ok"]:
        raise MayaError(reply["error"])
    return reply["result"]


@mcp.tool()
def maya_status() -> dict:
    """Check the connection to Maya and report its version and the open scene."""
    return _call("status")


@mcp.tool()
def execute_python(code: str, undo_chunk: bool = True, timeout_s: float = 120.0) -> str:
    """Run Python inside Maya and return what it printed.

    The code runs in Maya's __main__ namespace, like the Script Editor, so
    imports and variables persist between calls. If the last statement is an
    expression its value is returned too. With undo_chunk the whole call is a
    single undo step in Maya. timeout_s only limits how long this tool waits:
    Maya keeps running the code after a timeout.
    """
    reply = client.run(code, scope="main", undo_chunk=undo_chunk, timeout=timeout_s)
    parts = []
    if reply["stdout"]:
        parts.append(reply["stdout"].rstrip("\n"))
    if not reply["ok"]:
        parts.append(reply["error"].rstrip("\n"))
        raise MayaError(_clip("\n".join(parts)))
    result = reply["result"]
    if result is not None:
        parts.append("=> " + (result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)))
    return _clip("\n".join(parts)) or "(no output)"


@mcp.tool()
def scene_summary() -> dict:
    """Overview of the open scene: file, units, up axis, time range, top-level nodes, node counts, selection."""
    return _call("scene_summary")


@mcp.tool()
def list_nodes(node_type: str = "", pattern: str = "*", long_names: bool = False, limit: int = 200) -> dict:
    """List nodes by type (e.g. "joint", "skinCluster") and/or name pattern (e.g. "*_l", "spine_*")."""
    return _call("list_nodes", node_type=node_type, pattern=pattern, long_names=long_names, limit=limit)


@mcp.tool()
def node_info(node: str) -> dict:
    """Type, hierarchy, channel values and connections of one node. Joints also report jointOrient."""
    return _call("node_info", node=node)


@mcp.tool()
def capture_viewport(
    width: int = 960, height: int = 540, frame: float | None = None, show_ornaments: bool = False
) -> Image:
    """Screenshot of Maya's active viewport, at the current frame unless frame is given."""
    with tempfile.TemporaryDirectory(prefix="mcp-maya-shot-") as folder:
        path = Path(folder) / "viewport.png"
        _call(
            "capture_viewport",
            path=str(path),
            width=width,
            height=height,
            frame=frame,
            show_ornaments=show_ornaments,
        )
        return Image(data=path.read_bytes(), format="png")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
