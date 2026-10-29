"""Bound large native history messages without exposing private protocol data."""
import asyncio
import json
import os
import sys

import pytest

from easel.harnesses import rpc as transport
from easel.harnesses.acp import ACPAdapter, OpenCodeAdapter
from easel.harnesses.base import HarnessError, RunRequest


CHILD = r'''
import json
import sys

mode, size = sys.argv[1], int(sys.argv[2])

def send(message):
    print(json.dumps(message, ensure_ascii=False), flush=True)

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        result = {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}}
    elif method == "session/load":
        sys.stderr.write("private-stderr-token\n")
        sys.stderr.flush()
        if mode.startswith("rpc-error:"):
            code = json.loads(mode.split(":", 1)[1])
            send({"id": request["id"], "error": {
                "code": code, "message": "private-payload-token private-stderr-token",
                "data": {"prompt": "private-payload-token"}}})
            continue
        if mode == "boundary":
            payload = json.dumps({"id": request["id"], "result": {"ok": True}}).encode()
            sys.stdout.buffer.write(payload + b" " * (size - len(payload)) + b"\n")
            sys.stdout.buffer.flush()
            continue
        if mode in ("oversize", "unterminated"):
            sys.stdout.write('{"private-payload-token":"' + "x" * size)
            if mode == "oversize":
                sys.stdout.write('"}\n')
            sys.stdout.flush()
            sys.stdin.read()
            break
        if mode == "invalid":
            print("private-payload-token not-json", flush=True)
        elif mode == "invalid-utf8":
            sys.stdout.buffer.write(b'{"private-payload-token":"\xff"}\n')
            sys.stdout.buffer.flush()
        else:
            send({"method": "session/update", "params": {
                "sessionId": request["params"]["sessionId"],
                "update": {"sessionUpdate": "agent_message_chunk",
                           "content": {"type": "text", "text": "历史" * (size // 6)}}}})
        result = {"sessionId": request["params"]["sessionId"]}
    elif method == "session/prompt":
        send({"method": "session/update", "params": {
            "sessionId": request["params"]["sessionId"],
            "update": {"sessionUpdate": "agent_message_chunk",
                       "content": {"type": "text", "text": "OK"}}}})
        result = {"stopReason": "end_turn"}
    else:
        result = {}
    send({"id": request["id"], "result": result})
'''


def request_for(tmp_path, mode="history", size=5 * 1024 * 1024, **kwargs):
    return RunRequest("hello", tmp_path, dict(os.environ), native_id="old-session",
                      command=(sys.executable, "-c", CHILD, mode, str(size)), **kwargs)


async def reject(*args):
    raise AssertionError("No native tools expected")


@pytest.mark.parametrize("acp", [False, True])
def test_five_mib_utf8_notification_followed_by_response(tmp_path, acp):
    async def exercise():
        request = request_for(tmp_path)
        updates = []
        async with transport.RPC(request, list(request.command),
                                 lambda *update: updates.append(update), reject, acp=acp) as rpc:
            assert await rpc.call("session/load", {"sessionId": request.native_id}, timeout=10) == {
                "sessionId": request.native_id}
            assert len(updates) == 1
            assert len(updates[0][1]["update"]["content"]["text"].encode("utf-8")) > 4 * 1024 * 1024
        assert rpc.process.returncode is not None
    asyncio.run(exercise())


@pytest.mark.parametrize("adapter_type", [ACPAdapter, OpenCodeAdapter])
def test_old_acp_session_replays_giant_history_then_continues(tmp_path, adapter_type):
    async def exercise():
        request = request_for(tmp_path, session_key="giant-history")
        identifiers = []
        events = []
        adapter = adapter_type()
        try:
            for turn in range(2):
                await adapter.run(request, lambda *event: events.append(event), reject, identifiers.append)
            assert identifiers == [request.native_id] * 2
            assert events == [("token", "OK")] * 2
            await transport.close_sessions(request.session_key)
            await adapter.run(request, lambda *event: events.append(event), reject, identifiers.append)
            assert identifiers == [request.native_id] * 3
            assert events == [("token", "OK")] * 3
        finally:
            await transport.close_sessions(request.session_key)
        assert not transport._POOLS.get(asyncio.get_running_loop())
    asyncio.run(exercise())


@pytest.mark.parametrize("mode", ["oversize", "unterminated"])
@pytest.mark.parametrize("notification", [False, True])
def test_oversize_line_fails_safely_and_closes_pooled_connection(tmp_path, monkeypatch, mode, notification):
    limit = 32 * 1024
    monkeypatch.setattr(transport, "MAX_MESSAGE_BYTES", limit, raising=False)

    async def exercise():
        request = request_for(tmp_path, mode=mode, size=limit + 1, session_key="oversize-history")
        with pytest.raises(HarnessError, match=f"单行消息超过 {limit} 字节上限") as caught:
            async with transport.connection(request, list(request.command), lambda *args: None,
                                            reject, acp=True) as rpc:
                if notification:
                    await rpc.send({"id": 1, "method": "session/load",
                                    "params": {"sessionId": request.native_id}})
                    await asyncio.wait_for(rpc.wait_notification(asyncio.get_running_loop().create_future()), 5)
                else:
                    await rpc.call("session/load", {"sessionId": request.native_id}, timeout=5)
        assert "private-payload-token" not in str(caught.value)
        assert "private-stderr-token" not in str(caught.value)
        assert not rpc.pending
        assert rpc.process.returncode is not None
        assert rpc.reader.done() and rpc.stderr.done()
        assert not transport._POOLS.get(asyncio.get_running_loop())
    asyncio.run(exercise())


@pytest.mark.parametrize("mode", ["invalid", "invalid-utf8"])
def test_invalid_message_errors_do_not_include_private_data(tmp_path, mode):
    async def exercise():
        request = request_for(tmp_path, mode=mode)
        with pytest.raises(HarnessError, match="无效 JSON-RPC") as caught:
            async with transport.RPC(request, list(request.command), lambda *args: None, reject) as rpc:
                await rpc.call("session/load", {"sessionId": request.native_id}, timeout=5)
        assert "private-payload-token" not in str(caught.value)
        assert "private-stderr-token" not in str(caught.value)
    asyncio.run(exercise())


@pytest.mark.parametrize("code", [-32700, -32600, -32602, "INVALID_REQUEST"])
def test_native_invalid_request_does_not_echo_private_error_message(tmp_path, code):
    async def exercise():
        request = request_for(tmp_path, mode=f"rpc-error:{json.dumps(code)}")
        with pytest.raises(HarnessError, match="请求格式或参数无效") as caught:
            async with transport.RPC(request, list(request.command), lambda *args: None, reject) as rpc:
                await rpc.call("session/load", {"sessionId": request.native_id}, timeout=5)
        assert "private-payload-token" not in str(caught.value)
        assert "private-stderr-token" not in str(caught.value)
    asyncio.run(exercise())


def test_callback_failure_reports_exception_type_not_private_details(tmp_path):
    async def exercise():
        request = request_for(tmp_path, size=1024)

        def fail(method, params):
            raise RuntimeError("private-payload-token private-stderr-token")

        with pytest.raises(HarnessError, match="协议读取失败（RuntimeError）") as caught:
            async with transport.RPC(request, list(request.command), fail, reject) as rpc:
                await rpc.call("session/load", {"sessionId": request.native_id}, timeout=5)
        assert "private-payload-token" not in str(caught.value)
        assert "private-stderr-token" not in str(caught.value)
    asyncio.run(exercise())


@pytest.mark.parametrize("extra", [-1, 0, 1])
def test_line_limit_counts_utf8_bytes_excluding_newline(tmp_path, monkeypatch, extra):
    limit = 32 * 1024
    monkeypatch.setattr(transport, "MAX_MESSAGE_BYTES", limit)

    async def exercise():
        request = request_for(tmp_path, mode="boundary", size=limit + extra)
        async with transport.RPC(request, list(request.command), lambda *args: None, reject) as rpc:
            if extra > 0:
                with pytest.raises(HarnessError, match="单行消息超过"):
                    await rpc.call("session/load", {"sessionId": request.native_id}, timeout=5)
            else:
                assert await rpc.call("session/load", {"sessionId": request.native_id}, timeout=5) == {"ok": True}
    asyncio.run(exercise())


def test_default_64_mib_limit_is_enforced(tmp_path):
    assert transport.MAX_MESSAGE_BYTES == 64 * 1024 * 1024

    async def exercise():
        request = request_for(tmp_path, mode="unterminated", size=transport.MAX_MESSAGE_BYTES + 1)
        with pytest.raises(HarnessError, match="单行消息超过 67108864 字节上限"):
            async with transport.connection(request, list(request.command), lambda *args: None,
                                            reject, acp=True) as rpc:
                await rpc.call("session/load", {"sessionId": request.native_id}, timeout=15)
        assert rpc.process.returncode is not None
    asyncio.run(exercise())
