import json
import os
import subprocess
import sys
import time


runtime = sys.argv[1]
arguments = sys.argv[2:]
mode = next((arg.split("=", 1)[1] for arg in arguments if arg.startswith("--fake-mode=")),
            os.environ.get("FAKE_HARNESS_MODE", "normal"))
audit = next((arg.split("=", 1)[1] for arg in arguments if arg.startswith("--fake-audit=")),
             os.environ.get("FAKE_HARNESS_AUDIT", os.path.join(os.getcwd(), "audit.jsonl")))
thread_id = "native-thread"
turn_id = "native-turn"
session_id = "native-session"
pending_prompt = None


def send(message):
    if runtime in ("acp", "hermes"):
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
        result = {"sessionId": session_id,
                  "configOptions": [{"category": "model", "id": "model", "type": "select"}]}
        if runtime == "hermes" and method == "session/new":
            result["models"] = {"availableModels": [
                {"modelId": "provider/alpha", "name": "Alpha"},
                {"modelId": "provider/beta"}], "currentModelId": "provider/alpha"}
        reply(message, result)
    elif method in ("session/set_config_option", "session/set_model"):
        reply(message, {})
    elif method in ("turn/interrupt", "session/cancel"):
        if method == "session/cancel" and pending_prompt is not None and mode != "ignore-cancel":
            if mode == "slow-cancel":
                time.sleep(0.3)
            with open(audit, "a", encoding="utf-8") as stream:
                stream.write(json.dumps({"method": "fixture/cancel-completed"}) + "\n")
            reply(pending_prompt, {"stopReason": "cancelled"})
        if "id" in message:
            reply(message, {})
    elif method in ("turn/start", "session/prompt"):
        if mode == "permission":
            permission()
        if mode in ("hang", "slow-cancel", "ignore-cancel"):
            pending_prompt = message
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
