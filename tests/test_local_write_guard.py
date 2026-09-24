"""`web.app.local_write_guard` 的行为测试。

这个中间件决定「谁能对本机工作台发写请求」，改错了只有两种后果：
网页端全挂，或者外部站点能驱动本机写操作。两种都得有测试钉住。

契约（两条判据按请求形态二选一）：
* 带 Origin → 必须在 `_LOCAL_ORIGINS` 里；
* 不带 Origin → 对端必须来自回环地址。

用不存在的路径 `/api/__guard_probe__` 做探针：中间件在路由之前执行，
因此 403 与 404 的差别恰好等价于「守卫拦没拦」，且完全不产生副作用。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from web import app as web

PROBE = '/api/__guard_probe__'
LOCAL_ORIGIN = 'http://127.0.0.1:7860'
FOREIGN_ORIGIN = 'https://evil.example'
LOOPBACK = ('127.0.0.1', 51234)
REMOTE = ('192.168.1.9', 51234)


def _client(peer: tuple[str, int] = LOOPBACK) -> TestClient:
    # TrustedHostMiddleware 只放行 localhost / 127.0.0.1，测试统一用回环 base_url；
    # peer 必须显式指定——TestClient 默认对端是字面量 'testclient'，不是 IP，
    # 因此默认值会走「不是回环 → 拒绝」分支，拿它测放行路径会得出错误结论。
    return TestClient(web.app, base_url='http://127.0.0.1:7860', client=peer)


# ---------------------------------------------------------------- 无 Origin
def test_write_without_origin_from_loopback_is_allowed():
    """curl / 本机脚本不带 Origin，必须放行。

    修复前这里是 403：`origin not in _LOCAL_ORIGINS` 把 `Origin: None` 判成非法来源，
    等于把本机命令行与自动化脚本一起封死。
    """
    response = _client(LOOPBACK).post(PROBE)
    assert response.status_code == 404, response.text
    assert response.status_code != 403


def test_every_write_method_without_origin_from_loopback_is_allowed():
    client = _client(LOOPBACK)
    for method in ('post', 'put', 'delete', 'patch'):
        assert getattr(client, method)(PROBE).status_code == 404, method


def test_write_without_origin_from_remote_peer_is_rejected():
    """对端不是回环时没有 Origin 可判，拿不准就拒绝。

    今天就绑 127.0.0.1，这条看着多余；一旦有人把绑定改成 0.0.0.0，
    它拦住的就是「局域网内无人值守写操作」。
    """
    response = _client(REMOTE).post(PROBE)
    assert response.status_code == 403
    assert '仅允许从本机工作台操作' in response.json()['detail']


# ---------------------------------------------------------------- 带 Origin
def test_write_from_foreign_origin_is_rejected_even_from_loopback():
    """Origin 存在时以 Origin 为准，不看对端——跨站请求才是守卫的本职目标。"""
    response = _client(LOOPBACK).post(PROBE, headers={'Origin': FOREIGN_ORIGIN})
    assert response.status_code == 403
    assert '仅允许从本机工作台操作' in response.json()['detail']


def test_write_from_foreign_origin_is_rejected_from_remote_peer():
    assert _client(REMOTE).post(PROBE, headers={'Origin': FOREIGN_ORIGIN}).status_code == 403


def test_write_from_local_origins_is_allowed():
    client = _client(LOOPBACK)
    for origin in ('http://127.0.0.1:7860', 'http://localhost:7860',
                   'http://127.0.0.1:5173', 'http://localhost:5173'):
        assert client.post(PROBE, headers={'Origin': origin}).status_code == 404, origin


# ---------------------------------------------------------------- 只读与预检
def test_reads_are_never_blocked():
    client = _client(REMOTE)
    for origin in (None, FOREIGN_ORIGIN):
        headers = {'Origin': origin} if origin else {}
        assert client.get(PROBE, headers=headers).status_code == 404
        assert client.head(PROBE, headers=headers).status_code == 404


def test_options_is_never_blocked():
    assert _client(REMOTE).options(PROBE, headers={'Origin': FOREIGN_ORIGIN}).status_code != 403


# ---------------------------------------------------------------- 剪藏通道
def test_clipper_extension_preflight_still_gets_cors_headers():
    """浏览器扩展的剪藏通道不能因为这次改动被顺带打断。"""
    origin = 'chrome-extension://' + 'a' * 32
    response = _client(LOOPBACK).options('/api/clipper', headers={'Origin': origin})
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == origin
    assert 'Vary' in response.headers


def test_non_extension_origin_on_clipper_falls_through_to_the_guard():
    assert _client(LOOPBACK).post('/api/clipper', headers={'Origin': FOREIGN_ORIGIN}).status_code == 403


# ---------------------------------------------------------------- 判据本身
def test_loopback_peer_helper():
    class Peer:
        def __init__(self, host):
            self.host = host

    class Stub:
        def __init__(self, client):
            self.client = client

    assert web._loopback_peer(Stub(Peer('127.0.0.1'))) is True
    assert web._loopback_peer(Stub(Peer('127.0.0.53'))) is True
    assert web._loopback_peer(Stub(Peer('::1'))) is True
    assert web._loopback_peer(Stub(Peer('192.168.1.9'))) is False
    assert web._loopback_peer(Stub(Peer('testclient'))) is False
    assert web._loopback_peer(Stub(Peer(''))) is False
    assert web._loopback_peer(Stub(None)) is False          # 取不到对端 → 拒绝，不猜
