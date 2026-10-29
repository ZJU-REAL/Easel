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
import re
import sqlite3
import subprocess
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path

from easel.gateway_endpoint import websocket_url
from easel.openclaw_workspace import state_dir

# --- path resolution -------------------------------------------------------

PROFILE_DIR = state_dir()
PROFILE_STATE_DIR = PROFILE_DIR / "state"
PROFILE_DB = PROFILE_STATE_DIR / "openclaw.sqlite"

# Gateway loopback endpoint. 端口**不写死**：Easel 用 --profile easel，而 OpenClaw 对非默认
# profile 不用 18789，而是 20000 + fnv1a32(profile) % 40000（easel → 37289）。写死会造成
# 「gateway 明明活着，卡片桥接却连不上」。解析优先级见 easel/gateway_endpoint.py；
# 端口在每次 connect 时现取（web 进程长驻，用户可能改配置后重启 gateway）。

# Gateway WS handshake constants. Kept here as a single source of truth rather
# than buried in the connect payload — bump these to track OpenClaw's gateway
# protocol / client contract.
GATEWAY_PROTOCOL_MIN = 4
GATEWAY_PROTOCOL_MAX = 4
CLIENT_ID = "cli"
CLIENT_VERSION = "2026.9.2"

# The gateway question.* RPC surface (ask_user option cards) was introduced in
# the 2026.9.x line. On older gateways those methods answer INVALID_REQUEST and,
# worse, each connect attempt raises a fresh scope-upgrade pairing request. So
# on <2026.9 we skip the bridge entirely rather than poke the gateway per turn.
QUESTION_RPC_MIN_VERSION = (2026, 9, 0)


@lru_cache(maxsize=1)
def _openclaw_version() -> tuple[int, int, int] | None:
    """Best-effort parse of `openclaw --version` → (year, month, patch)."""
    try:
        from .openclaw_cmd import openclaw_base_cmd

        result = subprocess.run(
            openclaw_base_cmd() + ["--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", result.stdout)
        if not m:
            return None
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except Exception:
        return None


def question_bridge_supported() -> bool:
    """Whether this OpenClaw version exposes the question.* RPC.

    Unknown/unparseable version → assume supported (fail open): the caller's
    runtime circuit breaker still catches a persistently failing connect, so we
    don't silently disable cards on a version string we merely couldn't parse.
    """
    ver = _openclaw_version()
    if ver is None:
        return True
    return ver >= QUESTION_RPC_MIN_VERSION


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


class GatewayQuestionClosedError(GatewayQuestionError):
    """A question is no longer answerable, not a missing gateway capability."""

    STATUSES = {
        "QUESTION_NOT_FOUND": "not_found",
        "QUESTION_ALREADY_TERMINAL": "closed",
        "QUESTION_REQUESTER_INACTIVE": "cancelled",
        "QUESTION_EXPIRED": "expired",
        "QUESTION_CANCELLED": "cancelled",
        "QUESTION_CLOSED": "closed",
    }

    def __init__(self, reason: str):
        self.reason = reason
        self.status = self.STATUSES[reason]
        super().__init__(f"question is closed or expired ({reason})")


class GatewayUnsupportedError(GatewayQuestionError):
    """The gateway does not expose the question RPC surface.

    OpenClaw only added the `question.*` RPCs (backing ask_user cards) in the
    2026.9.x line. On older gateways (e.g. 2026.6.x) those methods answer
    INVALID_REQUEST; there is simply nothing to poll, so the bridge degrades to
    a quiet no-op instead of erroring on every turn.
    """


# --- device identity -------------------------------------------------------

# Device identity file written by OpenClaw's loadOrCreateDeviceIdentity
# (state/identity/device.json): {version, deviceId, publicKeyPem,
# privateKeyPem, createdAtMs}. This is the authoritative store in current
# OpenClaw; the legacy `device_identities` DB table is vestigial (present in
# the DDL but no longer populated), which is why reading it raised
# "no primary device identity in gateway db" on 2026.9.4.
DEVICE_IDENTITY_FILE = PROFILE_STATE_DIR / "identity" / "device.json"

_DEVICE_CACHE: dict | None = None
_DEVICE_LOCK = threading.Lock()


def _raw_pubkey_b64url(public_key_pem: str) -> str:
    """Derive the raw base64url Ed25519 public key from a PEM (the on-wire form
    the gateway pairing layer stores/compares), mirroring OpenClaw's
    publicKeyRawBase64UrlFromPem."""
    from cryptography.hazmat.primitives import serialization

    pub = serialization.load_pem_public_key(public_key_pem.encode())
    raw = pub.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _load_device_from_file() -> dict | None:
    """Load identity from state/identity/device.json (current OpenClaw store).

    Under Easel's gateway config (auth.mode=none, loopback) the operator token
    is not required — silent local pairing accepts an empty token — so we do
    not need the DB's device_auth_tokens row here.
    """
    if not DEVICE_IDENTITY_FILE.is_file():
        return None
    try:
        data = json.loads(DEVICE_IDENTITY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    device_id = data.get("deviceId")
    private_key_pem = data.get("privateKeyPem")
    public_key_pem = data.get("publicKeyPem")
    if not (device_id and private_key_pem and public_key_pem):
        return None
    return {
        "device_id": device_id,
        "private_key_pem": private_key_pem,
        "public_key": _raw_pubkey_b64url(public_key_pem),
        "token": "",
    }


def _load_device_from_db() -> dict | None:
    """Legacy fallback: read identity from the device_identities DB table.

    Populated by older OpenClaw builds (~2026.9.2) that had not yet moved the
    identity to a file. Returns None when the table/rows are absent so the file
    loader stays the primary path.
    """
    if not PROFILE_DB.is_file():
        return None
    con = sqlite3.connect(f"file:{PROFILE_DB}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        try:
            cur.execute(
                "SELECT device_id, public_key_pem, private_key_pem "
                "FROM device_identities WHERE identity_key='primary'")
        except sqlite3.OperationalError:
            return None  # table doesn't exist on this schema
        row = cur.fetchone()
        if not row:
            return None
        device_id, public_key_pem, private_key_pem = row
        cur.execute(
            "SELECT token FROM device_auth_tokens WHERE device_id=? AND role='operator'",
            (device_id,))
        tok = cur.fetchone()
        cur.execute(
            "SELECT public_key FROM device_pairing_paired WHERE device_id=?",
            (device_id,))
        prow = cur.fetchone()
    finally:
        con.close()
    raw_pub = prow[0] if prow else _raw_pubkey_b64url(public_key_pem)
    return {
        "device_id": device_id,
        "private_key_pem": private_key_pem,
        "public_key": raw_pub,
        "token": tok[0] if tok else "",
    }


def _load_device() -> dict:
    """Load the CLI device identity (file first, legacy DB table as fallback)."""
    global _DEVICE_CACHE
    with _DEVICE_LOCK:
        if _DEVICE_CACHE is not None:
            return _DEVICE_CACHE
        dev = _load_device_from_file() or _load_device_from_db()
        if dev is None:
            raise GatewayQuestionError(
                f"no device identity found (looked in {DEVICE_IDENTITY_FILE} "
                f"and {PROFILE_DB}); run the gateway once to create it")
        _DEVICE_CACHE = dev
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
        # suppress_origin: websocket-client otherwise auto-sends an Origin
        # header, which the gateway reads as a browser request and refuses to
        # silent-local-pair (NOT_PAIRED). A CLI operator must present no Origin.
        ws = self._ws_lib.create_connection(
            websocket_url(), timeout=self.timeout,
            suppress_origin=True)
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
        try:
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
                raise GatewayQuestionError("gateway connect timed out")
        except Exception:
            # 被网关拒绝（NOT_PAIRED/scope-upgrade）或收到非 JSON 帧时同样要关连接：
            # 否则每轮 connect 都在网关侧留下一个悬挂 socket/配对申请，直到 GC。
            ws.close()
            raise
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
                    err = msg.get("error") or {}
                    detail = json.dumps(err)[:200]
                    details = err.get("details")
                    reason = details.get("reason") if isinstance(details, dict) else None
                    reason = reason if isinstance(reason, str) else None
                    if reason in GatewayQuestionClosedError.STATUSES:
                        raise GatewayQuestionClosedError(reason)
                    missing_method = reason in {
                        "METHOD_NOT_FOUND", "UNKNOWN_METHOD", "UNSUPPORTED_METHOD",
                    }
                    message = err.get("message")
                    unknown_method = (not reason and isinstance(message, str)
                                      and re.fullmatch(r"unknown method:\s*" + re.escape(method),
                                                       message.strip(), flags=re.IGNORECASE))
                    if (err.get("code") == "METHOD_NOT_FOUND"
                            or err.get("code") == "INVALID_REQUEST" and (missing_method or unknown_method)):
                        raise GatewayUnsupportedError(
                            f"{method} not supported by this gateway: {detail}")
                    raise GatewayQuestionError(f"{method} failed: {detail}")
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
