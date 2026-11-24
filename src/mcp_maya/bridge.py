"""Maya-side half of mcp-maya.

The server never imports this file. For every call it writes a request file and
sends Maya one short line through the commandPort that exec()s this file with
REQUEST_PATH set. Passing code and results through files keeps both directions
clear of the commandPort buffer limit (4096 bytes unless the port says otherwise).
"""
import ast
import contextlib
import io
import json
import linecache
import os
import sys
import traceback

FILENAME = "<mcp-maya>"


def _jsonable(value):
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


def _execute(code, namespace):
    """Run code like a REPL cell: the value of a trailing expression is returned."""
    # lets tracebacks show the offending source line
    linecache.cache[FILENAME] = (len(code), None, code.splitlines(True), FILENAME)
    tree = ast.parse(code, FILENAME, "exec")
    last = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last = ast.Expression(tree.body.pop().value)
    exec(compile(tree, FILENAME, "exec"), namespace)
    if last is not None:
        return eval(compile(last, FILENAME, "eval"), namespace)
    return None


def main(request_path):
    from maya import cmds

    # A request must run exactly once even if Maya is handed its line twice:
    # the first run leaves the response file, and the server removes both files
    # once it has read the answer.
    try:
        with io.open(request_path, encoding="utf-8") as f:
            request = json.load(f)
    except FileNotFoundError:
        return
    if os.path.exists(request["response_path"]):
        return

    if request.get("scope") == "main":
        import __main__

        namespace = __main__.__dict__
    else:
        namespace = {"__name__": "__mcp_maya__", "ARGS": request.get("args")}

    response = {"ok": True, "result": None, "error": None}
    captured = io.StringIO()
    undo_chunk = request.get("undo_chunk", True)
    if undo_chunk:
        cmds.undoInfo(openChunk=True, chunkName="mcp-maya")
    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            response["result"] = _jsonable(_execute(request["code"], namespace))
    except BaseException:  # sys.exit() or an Esc interrupt must not escape into Maya
        etype, value, tb = sys.exc_info()
        # start the traceback at the caller's code, not at this file
        while tb is not None and tb.tb_frame.f_code.co_filename != FILENAME:
            tb = tb.tb_next
        response["ok"] = False
        response["error"] = "".join(traceback.format_exception(etype, value, tb))
    finally:
        if undo_chunk:
            cmds.undoInfo(closeChunk=True)
    response["stdout"] = captured.getvalue()

    # write-then-rename so the server never reads a half-written file
    tmp = request["response_path"] + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(response, f)
    os.replace(tmp, request["response_path"])


main(REQUEST_PATH)  # noqa: F821 - injected by the commandPort one-liner
