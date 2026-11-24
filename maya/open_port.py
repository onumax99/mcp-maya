"""Run inside Maya (Script Editor, Python tab) to let mcp-maya connect.

While the port is open, any program on this computer can run code in this Maya
session. It is bound to 127.0.0.1, so other machines cannot reach it.
Call close_port() when you are done.
"""
from maya import cmds

PORT = "127.0.0.1:7001"


def open_port(name=PORT):
    try:
        cmds.commandPort(name=name, sourceType="python")
    except RuntimeError as exc:  # raised when the port is already open
        print("mcp-maya: commandPort %s not opened: %s" % (name, exc))
    else:
        print("mcp-maya: commandPort %s opened" % name)


def close_port(name=PORT):
    try:
        cmds.commandPort(name=name, close=True)
    except RuntimeError as exc:
        print("mcp-maya: commandPort %s not closed: %s" % (name, exc))
    else:
        print("mcp-maya: commandPort %s closed" % name)


open_port()
