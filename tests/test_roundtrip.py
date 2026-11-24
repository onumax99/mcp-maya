import socket

import pytest

from mcp_maya.client import MayaClient, MayaConnectionError, MayaError, wrap_mel


def test_trailing_expression_is_the_result(client):
    reply = client.run("x = 20\nx + 22")
    assert reply == {"ok": True, "result": 42, "error": None, "stdout": ""}


def test_stdout_is_captured(client):
    reply = client.run("print('hello')\nprint('world')")
    assert reply["stdout"] == "hello\nworld\n"
    assert reply["result"] is None


def test_main_scope_persists_between_calls(client):
    client.run("mcp_maya_test_value = 7")
    assert client.run("mcp_maya_test_value * 2")["result"] == 14


COUNT_UP = "mcp_maya_runs = globals().get('mcp_maya_runs', 0) + 1\nmcp_maya_runs"


def test_code_runs_once_per_call(client):
    # the fake port reruns any line whose value is None, as Maya's does
    first = client.run(COUNT_UP)["result"]
    assert client.run(COUNT_UP)["result"] == first + 1


def test_code_runs_once_even_if_the_port_repeats_the_line(make_port):
    client = MayaClient(port=make_port(always_twice=True).port, timeout=5)
    first = client.run(COUNT_UP)["result"]
    assert client.run(COUNT_UP)["result"] == first + 1


def test_private_scope_sees_args_and_does_not_leak(client):
    reply = client.run("leaked = ARGS['n'] + 1\nleaked", args={"n": 1}, scope="private")
    assert reply["result"] == 2
    assert client.run("'leaked' in globals()")["result"] is False


def test_error_reports_traceback_from_callers_code(client):
    reply = client.run("def f():\n    return 1 / 0\nprint('before')\nf()")
    assert reply["ok"] is False
    assert reply["stdout"] == "before\n"
    assert "ZeroDivisionError" in reply["error"]
    assert "return 1 / 0" in reply["error"]
    assert "bridge.py" not in reply["error"]


def test_syntax_error_is_reported(client):
    reply = client.run("def broken(:")
    assert reply["ok"] is False
    assert "SyntaxError" in reply["error"]


def test_result_that_is_not_json_becomes_repr(client):
    assert client.run("{1, 2}")["result"] == "{1, 2}"


def test_code_larger_than_command_port_buffer(client, port):
    big = "data = %r\nlen(data)" % ("x" * 100000)
    assert client.run(big)["result"] == 100000
    assert len(port.received[-1]) < 4096


def test_undo_chunk_closed_even_when_code_raises(client, fake_cmds):
    client.run("raise RuntimeError('boom')")
    assert [sorted(c) for c in fake_cmds.undo_calls] == [["chunkName", "openChunk"], ["closeChunk"]]


def test_no_undo_chunk_when_disabled(client, fake_cmds):
    client.run("1", undo_chunk=False)
    assert fake_cmds.undo_calls == []


def test_port_that_never_replies_still_returns(make_port):
    silent = make_port(reply=False)
    assert MayaClient(port=silent.port, timeout=5).run("6 * 7")["result"] == 42


def test_connection_refused_explains_how_to_open_the_port():
    with socket.create_server(("127.0.0.1", 0)) as s:
        free_port = s.getsockname()[1]
    with pytest.raises(MayaConnectionError) as excinfo:
        MayaClient(port=free_port).run("1")
    assert 'cmds.commandPort(name="127.0.0.1:%d", sourceType="python")' % free_port in str(excinfo.value)


def test_line_the_port_cannot_run_is_reported(port):
    # MEL-wrapped line sent to a python port: the bridge never executes
    with pytest.raises(MayaError, match="did not run the request"):
        MayaClient(port=port.port, timeout=5, source_type="mel").run("1")


def test_wrap_mel_escapes_backslashes_and_quotes():
    assert wrap_mel(r"""open('C:\\a', "r")""") == r'''python("open('C:\\\\a', \"r\")");'''
