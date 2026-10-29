"""Bounded collector transports. Script stdout is data; stderr is never an API response."""
from __future__ import annotations

import json
import ipaddress
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from easel.timeouts import TIMEOUT_TREND_STARTUP, TREND_POLL_INTERVAL
from .environment import proxy_environment

from .protocol import MAX_BYTES, MAX_SCRIPT_BYTES, MAX_WORKER_REQUEST_BYTES, CollectorError, decode_payload, safe_json, validate_payload, web_url, utc_now
from .process_limits import ProcessLimits
from .rss import parse_feed
from .sources import Source, expanded_options


def _stop(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=TIMEOUT_TREND_STARTUP)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=TIMEOUT_TREND_STARTUP)


def _python(source: Source, options: dict, environment: dict[str, str]) -> dict:
    env = {**environment, "PYTHONIOENCODING": "utf-8",
           "EASEL_TREND_SOURCE_ID": source.id}
    command = [options["python"], "-X", "utf8", options["script"], *options.get("args", [])]
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": False}
    # Files avoid pipe deadlocks and unbounded in-memory communicate() output.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                    cwd=os.path.dirname(options["script"]), env=env, shell=False, **flags)
        except OSError:
            raise CollectorError("start_failed") from None
        deadline = time.monotonic() + source.timeout
        try:
            while True:
                if os.fstat(stdout.fileno()).st_size > MAX_BYTES or os.fstat(stderr.fileno()).st_size > MAX_BYTES:
                    raise CollectorError("output_too_large")
                if proc.poll() is not None:
                    break
                if time.monotonic() >= deadline:
                    raise CollectorError("timeout")
                time.sleep(TREND_POLL_INTERVAL)
            if proc.returncode:
                raise CollectorError("process_failed")
            stdout.seek(0)
            return decode_payload(stdout.read(MAX_BYTES + 1))
        finally:
            if proc.poll() is None:
                _stop(proc)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # Do not forward a configured Authorization header to a different destination.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_bytes(source: Source, options: dict, environment: dict[str, str]) -> bytes:
    url = web_url(options["url"])
    accept = "application/rss+xml, application/atom+xml, application/xml, text/xml" if source.type == "rss" else "application/json"
    headers = {"Accept": accept, **options.get("headers", {})}
    body = None
    if "body" in options:
        body = json.dumps(options["body"], ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    proxies = {key[:-6].lower(): value for key, value in environment.items()
               if key.lower() in ("http_proxy", "https_proxy", "no_proxy") and value}
    parsed = urllib.parse.urlsplit(url)
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = parsed.hostname == "localhost"
    if loopback or urllib.request.proxy_bypass_environment(parsed.netloc, proxies):
        proxies = {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies), _NoRedirect())
    try:
        request = urllib.request.Request(url, data=body, headers=headers, method=options.get("method", "GET"))
        deadline = time.monotonic() + source.timeout
        with opener.open(request, timeout=source.timeout) as response:
            # read1 returns after one underlying read, allowing an overall time budget
            # even if the server keeps trickling small chunks before each socket timeout.
            chunks, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CollectorError("timeout")
                # urllib's socket timeout also bounds the next blocking read.
                if response.fp is not None and getattr(response.fp, "raw", None) is not None:
                    response.fp.raw._sock.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BYTES:
                    raise CollectorError("output_too_large")
            return b"".join(chunks)
    except (TimeoutError,):
        raise CollectorError("timeout") from None
    except urllib.error.URLError as error:
        raise CollectorError("timeout" if isinstance(error.reason, TimeoutError) else "http_failed") from None
    except (OSError, ValueError):
        raise CollectorError("http_failed") from None


def _collect_direct(source: Source, environment: dict[str, str]) -> dict:
    options = source.options  # Already expanded once by the trusted parent.
    if options.get("validate_only") is True:
        try:
            with Path(options["script"]).open("rb") as file:
                raw = file.read(MAX_SCRIPT_BYTES + 1)
            if len(raw) > MAX_SCRIPT_BYTES:
                raise CollectorError("output_too_large")
            compile(raw.decode("utf-8-sig"), "collector.py", "exec", dont_inherit=True)
        except (SyntaxError, UnicodeError, ValueError):
            raise CollectorError("invalid_script") from None
        return {"version": 1, "fetched_at": utc_now(), "items": []}
    merged = dict(environment)
    for key, value in options.get("env", {}).items():
        # Explicit source overrides win even when inherited proxy key casing differs.
        if os.name == "nt" or key.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
            for existing in list(merged):
                if existing.lower() == key.lower():
                    del merged[existing]
        merged[key] = value
    env = proxy_environment(merged, "localhost,127.0.0.1,::1")
    if source.type == "python":
        return _python(source, options, env)
    raw = _http_bytes(source, options, env)
    if source.type == "rss":
        try:
            return parse_feed(raw, options["url"])
        except CollectorError as error:
            if error.code == "invalid_response":
                raise CollectorError("invalid_feed") from None
            raise
    return decode_payload(raw)


def collect(source: Source, environment: dict[str, str]) -> dict:
    # Forward only runtime/network essentials and explicitly configured source variables.
    options = expanded_options(source, environment)
    allowed = {"path", "systemroot", "windir", "temp", "tmp", "lang", "lc_all", "tz",
               "http_proxy", "https_proxy", "all_proxy", "no_proxy", "easel_proxy", "tmpdir",
               "ssl_cert_file", "ssl_cert_dir", "requests_ca_bundle"}
    env = {k: v for k, v in environment.items() if k.lower() in allowed and isinstance(v, str)}
    env.update(options.get("env", {}))
    env["PYTHONIOENCODING"] = "utf-8"
    # Resolve secret references here, then send only the resolved per-source options to the worker.
    worker_source = {**source.__dict__, "options": options}
    request = json.dumps({"source": worker_source, "environment": env}, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(request) > MAX_WORKER_REQUEST_BYTES:
        raise CollectorError("invalid_response")
    limits = ProcessLimits(int(options.get("memory_mb", 256)), source.timeout)
    flags = ({"creationflags": subprocess.CREATE_NO_WINDOW | 0x4} if os.name == "nt"
             else {"start_new_session": True})
    with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        stdin.write(request)
        stdin.seek(0)
        process = None
        try:
            process = subprocess.Popen([sys.executable, "-I", "-X", "utf8", str(Path(__file__).with_name("worker.py"))],
                                       stdin=stdin, stdout=stdout, stderr=stderr, env=env, shell=False, **flags)
            try:
                limits.attach(process)
            except Exception:
                raise CollectorError("isolation_failed") from None
            deadline = time.monotonic() + source.timeout + TIMEOUT_TREND_STARTUP
            while process.poll() is None:
                limits.check(process)
                if os.fstat(stdout.fileno()).st_size > MAX_BYTES or os.fstat(stderr.fileno()).st_size > MAX_BYTES:
                    raise CollectorError("output_too_large")
                if time.monotonic() > deadline:
                    raise CollectorError("timeout")
                time.sleep(TREND_POLL_INTERVAL)
            if process.returncode:
                raise CollectorError("resource_limit")
            stdout.seek(0)
            result = safe_json(stdout.read(MAX_BYTES + 1))
            if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                raise CollectorError("invalid_response")
            if not result["ok"]:
                code = result.get("error")
                raise CollectorError(code if isinstance(code, str) and len(code) < 64 else "collector_failed")
            return validate_payload(result.get("payload"))
        except OSError:
            raise CollectorError("start_failed") from None
        finally:
            limits.close()  # Windows: kills the entire job, including detached descendants.
            if process is not None and os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process is not None and process.poll() is None:
                _stop(process)
