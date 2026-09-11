"""Gateway question-answer bridge for the Easel web UI.

OpenClaw's `ask_user` tool registers a structured question on the Gateway
(`question.request`, backed by `question.list` / `question.get` /
`question.resolve` RPCs). The official Control UI renders these as a docked
option card and answers them through the `operator.questions` RPC surface.

The Easel web frontend is a custom React app that does not speak the Gateway
WebSocket protocol, so ask_user cards never render and the agent blocks for
the full timeout (default 900 s) before continuing with `no_answer`.

This module is a minimal read/answer bridge: it connects to the loopback
Gateway using the already-paired device identity (Ed25519 signature, v2
payload), lists pending questions for a session, and resolves answers.
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

# --- path resolution -------------------------------------------------------

HOME = Path.home()
# Easel runs OpenClaw under an isolated `easel` profile at ~/.openclaw-easel/;
# allow an override for non-default setups.
PROFILE_DIR = Path(os.environ.get("EASEL_OPENCLAW_STATE_DIR") or (HOME / ".openclaw-easel"))
PROFILE_STATE_DIR = PROFILE_DIR / "state"
PROFILE_DB = PROFILE_STATE_DIR / "openclaw.sqlite"

# Gateway loopback endpoint (default port 18789; overridable when reconfigured).
GATEWAY_HOST = os.environ.get("EASEL_GATEWAY_HOST", "127.0.0.1")
GATEWAY_PORT = int(os.environ.get("EASEL_GATEWAY_PORT", "18789"))

# Gateway WS handshake constants. Kept here as a single source of truth rather
# than buried in the connect payload — bump these to track OpenClaw's gateway
# protocol / client contract.
GATEWAY_PROTOCOL_MIN = 4
GATEWAY_PROTOCOL_MAX = 4
CLIENT_ID = "cli"
CLIENT_VERSION = "2026.9.2"


def _client_identity() -> dict:
    """Client metadata tuple, mirroring OpenClaw's own platform mapping.

    OpenClaw maps the Node platform to the *wire* identity it sends on connect
    (src/shared/gateway-client-platform.ts):
        darwin -> {"platform": "macos",   "deviceFamily": "Mac"}
        win32  -> {"platform": "windows", "deviceFamily": "Windows"}
        linux  -> {"platform": "linux",   "deviceFamily": "Linux"}

    Both fields matter: the Gateway compares them against the paired device
    record (resolvePinnedClientMetadata) and answers any mismatch with
    requirePairing("metadata-upgrade") -> NOT_PAIRED, which kills this bridge.
    Sending only "platform" (and using the raw "darwin" on macOS) reproduces
    exactly that failure once the device was paired by any other OpenClaw
    surface, which stores deviceFamily too.
    """
    if sys.platform.startswith("win"):
        return {"platform": "windows", "deviceFamily": "Windows"}
    if sys.platform == "darwin":
        return {"platform": "macos", "deviceFamily": "Mac"}
    return {"platform": "linux", "deviceFamily": "Linux"}


class GatewayQuestionError(RuntimeError):
    pass


# --- device identity -------------------------------------------------------

_DEVICE_CACHE: dict | None = None
_DEVICE_LOCK = threading.Lock()


def _load_device() -> dict:
    """Load the paired CLI device identity + auth token from the state DB."""
    global _DEVICE_CACHE
    with _DEVICE_LOCK:
        if _DEVICE_CACHE is not None:
            return _DEVICE_CACHE
        if not PROFILE_DB.is_file():
            raise GatewayQuestionError(
                f"gateway state db not found: {PROFILE_DB}")
        con = sqlite3.connect(f"file:{PROFILE_DB}?mode=ro", uri=True)
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT device_id, public_key_pem, private_key_pem "
                "FROM device_identities WHERE identity_key='primary'")
            row = cur.fetchone()
            if not row:
                raise GatewayQuestionError("no primary device identity in gateway db")
            device_id, public_key_pem, private_key_pem = row
            cur.execute(
                "SELECT token FROM device_auth_tokens WHERE device_id=? AND role='operator'",
                (device_id,))
            tok = cur.fetchone()
            if not tok:
                raise GatewayQuestionError("no operator auth token for primary device")
            # raw base64url public key (as stored in device_pairing_paired)
            cur.execute(
                "SELECT public_key FROM device_pairing_paired WHERE device_id=?",
                (device_id,))
            prow = cur.fetchone()
            raw_pub = prow[0] if prow else None
        finally:
            con.close()
        if not raw_pub:
            raise GatewayQuestionError("paired public key not found")
        _DEVICE_CACHE = {
            "device_id": device_id,
            "private_key_pem": private_key_pem,
            "public_key": raw_pub,
            "token": tok[0],
        }
        return _DEVICE_CACHE


def _sign(payload: str) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: F401

    dev = _load_device()
    key = serialization.load_pem_private_key(
        dev["private_key_pem"].encode(), password=None)
    sig = key.sign(payload.encode())
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode()


# --- websocket client ------------------------------------------------------

class GatewayClient:
    """Minimal Gateway WS RPC client (operator role, v2 device auth)."""

    def __init__(self, timeout: float = 12.0):
        import websocket  # local import: keep module import cheap

        self._ws_lib = websocket
        self.ws = None
        self.timeout = timeout
        self._seq = 0

    def connect(self) -> None:
        import websocket  # noqa: F401

        dev = _load_device()
        ws = self._ws_lib.create_connection(
            f"ws://{GATEWAY_HOST}:{GATEWAY_PORT}", timeout=self.timeout)
        try:
            first = json.loads(ws.recv())
            if first.get("event") != "connect.challenge":
                raise GatewayQuestionError(
                    f"expected connect.challenge, got {str(first)[:120]}")
            nonce = first["payload"]["nonce"]
            ts = first["payload"]["ts"]
        except Exception:
            ws.close()
            raise

        scopes = ["operator.admin", "operator.read", "operator.write"]
        payload = "|".join([
            "v2", dev["device_id"], "cli", "cli", "operator",
            ",".join(scopes), str(ts), dev["token"], nonce,
        ])
        sig = _sign(payload)
        conn = {
            "type": "req", "id": "1", "method": "connect",
            "params": {
                "minProtocol": GATEWAY_PROTOCOL_MIN, "maxProtocol": GATEWAY_PROTOCOL_MAX,
                "client": {"id": CLIENT_ID, "version": CLIENT_VERSION,
                           **_client_identity(), "mode": "cli"},
                "role": "operator", "scopes": scopes,
                "caps": [], "commands": [], "permissions": {},
                "auth": {"token": dev["token"]},
                "device": {
                    "id": dev["device_id"],
                    "publicKey": dev["public_key"],
                    "signature": sig,
                    "signedAt": ts,
                    "nonce": nonce,
                },
                "locale": "zh-CN",
                "userAgent": "easel-web/0.1",
            },
        }
        ws.send(json.dumps(conn))
        ok = False
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            msg = json.loads(ws.recv())
            if msg.get("id") == "1":
                ok = msg.get("ok", False)
                if not ok:
                    raise GatewayQuestionError(
                        f"gateway connect failed: {json.dumps(msg.get('error'))[:200]}")
                break
        if not ok:
            ws.close()
            raise GatewayQuestionError("gateway connect timed out")
        self.ws = ws

    def _rpc(self, method: str, params: dict, timeout: float | None = None):
        if self.ws is None:
            self.connect()
        self._seq += 1
        req_id = str(self._seq)
        self.ws.send(json.dumps({
            "type": "req", "id": req_id, "method": method, "params": params,
        }))
        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == req_id:
                if not msg.get("ok", False):
                    raise GatewayQuestionError(
                        f"{method} failed: {json.dumps(msg.get('error'))[:200]}")
                return msg.get("payload")
        raise GatewayQuestionError(f"{method} timed out")

    def list_questions(self, session_key: str | None = None,
                       status: str | None = None) -> list[dict]:
        payload = self._rpc("question.list", {}) or {}
        items = payload.get("questions") or []
        out = []
        for q in items:
            if session_key and q.get("sessionKey") != session_key:
                continue
            if status and q.get("status") != status:
                continue
            out.append(q)
        return out

    def get_question(self, question_id: str) -> dict | None:
        payload = self._rpc("question.get", {"id": question_id})
        return (payload or {}).get("question")

    def resolve(self, question_id: str, answers: dict,
                resolved_by: str | None = None) -> dict:
        params = {
            "id": question_id,
            "answers": {"answers": answers},
        }
        if resolved_by:
            params["resolvedBy"] = resolved_by
        return self._rpc("question.resolve", params) or {}

    def close(self) -> None:
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None


def pending_questions_for_session(session_key: str) -> list[dict]:
    """Convenience: list pending questions belonging to a session."""
    client = GatewayClient()
    try:
        return client.list_questions(session_key=session_key, status="pending")
    finally:
        client.close()
