"""Bounded direct transport for public login assets on unreliable browser connections."""
from __future__ import annotations

from urllib.parse import urlparse

import requests


def install(context, platform: str) -> None:
    if platform not in ("weixin-channels", "xiaohongshu"):
        return
    session = requests.Session()
    session.trust_env = False

    def handle(route, request):
        parsed = urlparse(request.url)
        public_asset = parsed.scheme == "https" and request.method == "GET" and (
            platform == "weixin-channels" and (
                parsed.hostname == "res.wx.qq.com"
                or parsed.hostname == "open.weixin.qq.com"
                and parsed.path.startswith(("/connect/qrconnect", "/connect/qrcode/"))
            )
            or platform == "xiaohongshu"
            and parsed.hostname in ("fe-static.xhscdn.com", "ci.xiaohongshu.com")
            and request.resource_type in ("script", "stylesheet")
        )
        if not public_asset:
            route.continue_()
            return
        try:
            headers = request.all_headers()
            headers["accept-encoding"] = "identity"
            response = session.get(request.url, headers=headers, timeout=(3, 5),
                                   allow_redirects=False)
            if response.status_code != 200:
                route.continue_()
                return
            response_headers = {
                key: value for key, value in response.headers.items()
                if key.lower() not in ("content-encoding", "content-length",
                                       "transfer-encoding", "connection", "set-cookie")
            }
            route.fulfill(status=200, headers=response_headers, body=response.content)
        except requests.RequestException:
            route.continue_()

    context.route("**/*", handle)
    context.on("close", lambda *_: session.close())
