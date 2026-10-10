"""Channels login must block bulky resources without breaking QR or API requests."""
import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "shared" / "scripts"))
import web_publisher


class Context:
    def __init__(self):
        self.routes = []

    def route(self, pattern, handler):
        self.routes.append((pattern, handler))


@pytest.mark.parametrize("resource_type", ["media", "font"])
@pytest.mark.parametrize("url", ["https://static.example/asset", "https://static.example/a.WOFF2?v=1"])
def test_channels_blocks_heavy_resource_types(resource_type, url):
    context = Context()
    web_publisher._block_heavy(context, "weixin-channels")
    actions = []
    route = SimpleNamespace(abort=lambda: actions.append("abort"),
                            continue_=lambda: actions.append("continue"))
    context.routes[0][1](route, SimpleNamespace(resource_type=resource_type, url=url))
    assert context.routes[0][0] == "**/*"
    assert actions == ["abort"]


@pytest.mark.parametrize("resource_type", ["image", "xhr", "fetch", "document", "script", "stylesheet"])
@pytest.mark.parametrize("url", [
    "https://channels.example/qr.png",
    "https://channels.example/api?filename=preview.mp4",
    "https://channels.example/login?next=font.woff2",
])
def test_channels_preserves_qr_api_and_page_resources(resource_type, url):
    context = Context()
    web_publisher._block_heavy(context, "weixin-channels")
    actions = []
    route = SimpleNamespace(abort=lambda: actions.append("abort"),
                            continue_=lambda: actions.append("continue"))
    context.routes[0][1](route, SimpleNamespace(resource_type=resource_type, url=url))
    assert actions == ["continue"]


@pytest.mark.parametrize("platform", [platform for platform in web_publisher.PLATFORMS
                                     if platform != "weixin-channels"])
def test_other_platforms_are_not_filtered(platform):
    context = Context()
    web_publisher._block_heavy(context, platform)
    assert not context.routes


def test_route_installation_failure_is_not_silently_ignored():
    def fail(pattern, handler):
        raise RuntimeError("context closed")

    with pytest.raises(RuntimeError, match="context closed"):
        web_publisher._block_heavy(SimpleNamespace(route=fail), "weixin-channels")


@pytest.mark.parametrize("command", ["cmd_login_qr", "cmd_whoami"])
def test_login_commands_install_context_route_before_navigation(command):
    tree = ast.parse(Path(web_publisher.__file__).read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == command)
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    block = next(node for node in calls if isinstance(node.func, ast.Name)
                 and node.func.id == "_block_heavy")
    navigation = next(node for node in calls if isinstance(node.func, ast.Attribute)
                      and node.func.attr == "goto")
    assert block.lineno < navigation.lineno
    assert ast.unparse(block.args[0]) == "browser"
    assert ast.unparse(block.args[1]) == "a.platform"


@pytest.mark.parametrize("command", ["cmd_login", "cmd_publish"])
def test_interactive_login_and_publishing_are_not_filtered(command):
    tree = ast.parse(Path(web_publisher.__file__).read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == command)
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id == "_block_heavy" for node in ast.walk(function))
