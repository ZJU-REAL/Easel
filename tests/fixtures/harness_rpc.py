import json
import os
import subprocess
import sys
import time


runtime = sys.argv[1]
mode = os.environ.get("FAKE_HARNESS_MODE", "normal")
audit = os.environ["FAKE_HARNESS_AUDIT"]
thread_id = "native-thread"
turn_id = "native-turn"
session_id = "native-session"


def send(message):
    if runtime == "acp":
        message = {"jsonrpc": "2.0", **message}
    print(json.dumps(message), flush=True)


def receive():
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    message = json.loads(line)
    with open(audit, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(message) + "\n")
    return message


def reply(message, result):
    send({"id": message["id"], "result": result})


def permission():
    if runtime == "codex":
        send({"id": "permission-request", "method": "item/commandExecution/requestApproval",
              "params": {"threadId": thread_id, "turnId": turn_id, "itemId": "tool",
                         "command": os.environ.get("FAKE_HARNESS_COMMAND", "read public file")}})
    else:
        send({"id": "permission-request", "method": "session/request_permission",
              "params": {"sessionId": session_id, "toolCall": {"title": "read public file"},
                         "options": [{"optionId": "always", "name": "Always", "kind": "allow_always"},
                                     {"optionId": "once", "name": "Allow", "kind": "allow_once"},
                                     {"optionId": "deny", "name": "Reject", "kind": "reject_once"}]}})
    while receive().get("id") != "permission-request":
        pass


while True:
    message = receive()
    method = message.get("method")
    if method == "initialize":
        reply(message, {"protocolVersion": 1, "agentCapabilities": {"loadSession": mode != "no-resume"}})
    elif method == "initialized":
        pass
    elif method == "model/list":
        if mode == "models-error":
            send({"id": message["id"], "error": {"message": "invalid secret-test-key"}})
        elif message["params"].get("cursor"):
            reply(message, {"data": [{"model": "second-model", "displayName": "Second"},
                                    {"model": "first-model"}], "nextCursor": None})
        else:
            reply(message, {"data": [{"model": "first-model", "displayName": "First", "isDefault": True},
                                    {"model": "hidden-model", "hidden": True},
                                    {"model": "bad\nmodel"}], "nextCursor": "next"})
    elif method in ("thread/start", "thread/resume"):
        if mode == "stable-resume" and method == "thread/resume":
            thread_id = message["params"]["threadId"]
        reply(message, {"thread": {"id": thread_id}})
    elif method in ("session/new", "session/load"):
        if method == "session/load":
            session_id = "replacement" if mode == "wrong-resume" else message["params"]["sessionId"]
        reply(message, {"sessionId": session_id,
                        "configOptions": [{"category": "model", "id": "model", "type": "select"}]})
    elif method == "session/set_config_option":
        reply(message, {})
    elif method in ("turn/interrupt", "session/cancel"):
        if "id" in message:
            reply(message, {})
    elif method in ("turn/start", "session/prompt"):
        if mode == "permission":
            permission()
        if mode == "hang":
            if runtime == "codex":
                reply(message, {"turn": {"id": turn_id}})
            continue
        if mode == "exit":
            sys.exit(0)
        if mode == "error":
            send({"id": message["id"], "error": {"code": -32000, "message": "invalid model secret-test-key"}})
            continue
        if runtime == "codex":
            common = {"threadId": thread_id, "turnId": turn_id, "itemId": "text"}
            send({"method": "item/reasoning/summaryTextDelta", "params": {**common, "delta": "思考"}})
            send({"method": "item/agentMessage/delta", "params": {**common, "delta": "你好"}})
            send({"method": "item/completed",
                  "params": {**common, "item": {"type": "agentMessage", "id": "text", "text": "你好"}}})
            if mode == "fatal":
                send({"method": "error", "params": {**common, "willRetry": False}})
            else:
                send({"method": "turn/completed",
                      "params": {**common, "turn": {"id": turn_id, "status": "completed"}}})
            reply(message, {"turn": {"id": turn_id}})
        else:
            for update, text in (("agent_thought_chunk", "思考"), ("agent_message_chunk", "你好")):
                send({"method": "session/update", "params": {
                    "sessionId": session_id, "update": {"sessionUpdate": update,
                                                      "content": {"type": "text", "text": text}}}})
            reply(message, {"stopReason": "end_turn"})
    elif method == "tree":
        child = subprocess.Popen([sys.executable, "-c",
                                  "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(120)"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.1)
        reply(message, {"pid": child.pid})
    elif method == "stderr":
        sys.stderr.write("noise" * 100000)
        sys.stderr.flush()
        reply(message, {})
    elif method == "environment":
        reply(message, {"cwd": os.getcwd(), "root": os.environ.get("EASEL_ROOT")})
    elif method == "malformed":
        print("not-json", flush=True)
    elif method == "quit":
        sys.exit(0)
    elif "id" in message:
        reply(message, {})
