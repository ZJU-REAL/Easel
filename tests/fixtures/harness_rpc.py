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
pending_prompt = None


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
    elif method == "account/read":
        reply(message, {"account": None if mode in ("logged-out", "external") else {
            "type": "chatgpt", "email": "private@example.test", "accessToken": "do-not-expose"},
            "requiresOpenaiAuth": mode != "external"})
    elif method == "account/login/start":
        result = {"type": message["params"]["type"], "loginId": "native-login"}
        if message["params"]["type"] == "chatgptDeviceCode":
            result.update(verificationUrl="https://auth.openai.com/codex/device", userCode="TEST-1234")
        else:
            result["authUrl"] = "https://chatgpt.com/fake-login?state=test"
        if mode == "login-bad-url":
            result["authUrl"] = "https://evil.example/steal"
        if mode in ("login-success", "login-failure"):
            send({"method": "account/login/completed", "params": {
                "loginId": "native-login", "success": mode == "login-success", "error": "private-token"}})
        send({"method": "account/login/completed", "params": {"loginId": "unrelated", "success": True}})
        reply(message, result)
    elif method == "account/login/cancel":
        reply(message, {"status": "canceled"})
        send({"method": "account/login/completed", "params": {
            "loginId": "native-login", "success": False, "error": "private-token"}})
    elif method == "account/rateLimits/read":
        if mode == "quota-unavailable":
            send({"id": message["id"], "error": {"message": "private-token quota unavailable"}})
        else:
            reply(message, {"rateLimits": {"primary": {"usedPercent": 25,
                "windowDurationMins": 300, "resetsAt": 1900000000, "secret": "do-not-expose"}}})
    elif method == "model/list":
        if mode == "capabilities":
            reply(message, {"data": [{"model": "test-model", "isDefault": True,
                "supportedReasoningEfforts": [{"reasoningEffort": "low"}, {"reasoningEffort": "high"}],
                "defaultReasoningEffort": "high", "inputModalities": ["text", "image"]}]})
        elif mode == "models-error":
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
        if mode == "stderr-exit":
            print("401 unauthorized do-not-expose", file=sys.stderr, flush=True)
            time.sleep(0.05)
            sys.exit(1)
        if mode == "error":
            send({"id": message["id"], "error": {"code": -32000, "message": "invalid model secret-test-key"}})
            continue
        if runtime == "codex":
            common = {"threadId": thread_id, "turnId": turn_id, "itemId": "text"}
            if mode == "progress":
                progress_command = os.environ.get("FAKE_PROGRESS_COMMAND", "cat README.md")
                for method, item in [
                    ("item/started", {"type": "commandExecution", "command": progress_command}),
                    ("item/completed", {"type": "commandExecution", "command": progress_command, "exitCode": 0}),
                    ("item/completed", {"type": "fileChange", "status": "completed", "changes": [{"path": "outputs/draft.txt"}]}),
                ]:
                    send({"method": method, "params": {**common, "item": item}})
                for owner, tokens in [(thread_id, 123), ("other-thread", 9999)]:
                    send({"method": "thread/tokenUsage/updated", "params": {
                        "threadId": owner, "turnId": turn_id, "tokenUsage": {
                            "total": {"totalTokens": tokens, "inputTokens": 100, "outputTokens": 23,
                                      "cachedInputTokens": 50}}}})
            send({"method": "item/reasoning/summaryTextDelta", "params": {**common, "delta": "思考"}})
            send({"method": "item/agentMessage/delta", "params": {**common, "delta": "你好"}})
            send({"method": "item/completed",
                  "params": {**common, "item": {"type": "agentMessage", "id": "text", "text": "你好"}}})
            if mode in ("fatal", "auth-error"):
                send({"method": "error", "params": {**common, "willRetry": False,
                      "error": {"message": "401 unauthorized private-token"} if mode == "auth-error" else {}}})
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
